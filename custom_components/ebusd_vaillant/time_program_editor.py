"""Editable view of one weekly time program (currently: circulation).

One ``TimeProgramEditor`` per program is shared by the select (weekday), number
(slot count) and time (slot start/end) entities.  It subscribes to the ebusd
read topics, keeps the raw per-day slot data and writes changes back through the
``{Cc,Hwc,Z1}Timer_{Day}/set`` message:  ``slotindex;slotcount;start;end``.

Limits: HA ``time`` entities cannot hold ``24:00``, so an end of 24:00 is shown
as 23:59 and 23:59 is written as 24:00.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import time
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .discovery import TIMER_DAYS, TIMER_SLOTS_PER_DAY, DiscoveredTimeProgram, payload_values
from .time_program import DAY_KEYS, _to_minutes, parse_slot_counts

_LOGGER = logging.getLogger(__name__)

# 10 minutes steps are currently the default in the offical vaillant app
TIME_STEP_MINUTES = 10
# Edits are collected and sent to the bus this many seconds after the last one
WRITE_DELAY_SECONDS = 10
EDITORS_KEY = f"{DOMAIN}_time_program_editors"


def to_time(value: str | None) -> time | None:
    """``HH:MM`` (24:00 allowed) -> datetime.time; 24:00 is shown as 23:59."""
    minutes = _to_minutes(value)
    if minutes is None:
        return None
    if minutes >= 24 * 60:
        return time(23, 59)
    return time(minutes // 60, minutes % 60)


def from_time(value: time) -> str:
    """datetime.time -> ``HH:MM``; 23:59 is written as 24:00."""
    # The controller only accepts 10-minute steps: snap to the nearest one.
    minutes = min(round((value.hour * 60 + value.minute) / TIME_STEP_MINUTES) * TIME_STEP_MINUTES, 24 * 60)
    if value.hour == 23 and value.minute == 59:
        minutes = 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _decode(payload: Any) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError, ValueError, TypeError:
        return payload


def get_editor(hass: HomeAssistant, config: DiscoveredTimeProgram) -> TimeProgramEditor:
    editors: dict[str, TimeProgramEditor] = hass.data.setdefault(EDITORS_KEY, {})
    if config.key not in editors:
        editors[config.key] = TimeProgramEditor(hass, config)
    return editors[config.key]


class TimeProgramEditor:
    def __init__(self, hass: HomeAssistant, config: DiscoveredTimeProgram) -> None:
        self.hass = hass
        self.config = config
        self.label = config.name.removesuffix(" Time Program")
        self.selected_day: str = DAY_KEYS[dt_util.now().weekday()]
        self.counts: list[int] | None = None
        # day -> slot index -> (start, end) as "HH:MM" strings (None = unknown)
        self.slots: dict[str, list[tuple[str, str] | None]] = {
            d: [None] * TIMER_SLOTS_PER_DAY for d in DAY_KEYS
        }
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._users = 0
        # day -> (slots, count) edited locally, not yet sent to the bus
        self._pending: dict[str, tuple[list[tuple[str, str]], int]] = {}
        self._unsub_timer: Callable[[], None] | None = None
        timeframes_topic = config.timeframes.read_topic
        self._base, _, tf_name = timeframes_topic.rpartition("/")
        self._msg_prefix = tf_name.removesuffix("_Timeframes")

    # -- state ---------------------------------------------------------------

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    @property
    def ready(self) -> bool:
        return self.counts is not None

    def count(self, day: str | None = None) -> int:
        day = day or self.selected_day
        if self.counts is None:
            return 0
        return min(self.counts[DAY_KEYS.index(day)], TIMER_SLOTS_PER_DAY)

    def slot(self, idx: int) -> tuple[str, str] | None:
        return self.slots[self.selected_day][idx]

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def select_day(self, day: str) -> None:
        self.selected_day = day
        self._notify()

    # -- lifecycle -----------------------------------------------------------

    async def async_acquire(self) -> None:
        self._users += 1
        if self._users > 1:
            return

        @callback
        def _on_counts(msg: mqtt.ReceiveMessage) -> None:
            counts = parse_slot_counts(_decode(msg.payload))
            if counts is not None:
                if self.counts is not None:
                    for day in self._pending:  # keep staged counts
                        i = DAY_KEYS.index(day)
                        counts[i] = self.counts[i]
                self.counts = counts
                self._notify()

        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, self.config.timeframes.read_topic, _on_counts)
        )
        for day, topics in self.config.slots.items():
            for idx, topic in enumerate(topics):
                self._unsubs.append(
                    await mqtt.async_subscribe(
                        self.hass, topic.read_topic, self._slot_handler(day, idx)
                    )
                )

    @callback
    def release(self) -> None:
        self._users -= 1
        if self._users <= 0:
            if self._pending:
                self.hass.async_create_task(self.async_flush())
            for unsub in self._unsubs:
                unsub()
            self._unsubs.clear()

    def _slot_handler(self, day: str, idx: int):
        @callback
        def _handle(msg: mqtt.ReceiveMessage) -> None:
            if day in self._pending:
                return  # staged edit not sent yet
            values = payload_values(_decode(msg.payload))
            if len(values) >= 2 and _to_minutes(values[0]) is not None:
                self.slots[day][idx] = (str(values[0]), str(values[1]))
                self._notify()

        return _handle

    # -- writing -------------------------------------------------------------

    @callback
    def _stage_day(self, day: str, slots: list[tuple[str, str]], count: int | None = None) -> None:
        """Apply an edit locally and (re)start the send timer."""
        count = len(slots) if count is None else count
        for idx, slot in enumerate(slots):
            self.slots[day][idx] = slot
        if self.counts is not None:
            self.counts[DAY_KEYS.index(day)] = count
        self._pending[day] = (slots, count)
        if self._unsub_timer:
            self._unsub_timer()
        self._unsub_timer = async_call_later(self.hass, WRITE_DELAY_SECONDS, self._timer_fired)
        self._notify()

    @callback
    def _timer_fired(self, _now: Any) -> None:
        self._unsub_timer = None
        self.hass.async_create_task(self.async_flush())

    async def async_flush(self) -> None:
        """Send all staged days to the bus now."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        pending, self._pending = self._pending, {}
        for day, (slots, count) in pending.items():
            await self._send_day(day, slots, count)
        self._notify()

    async def _send_day(self, day: str, slots: list[tuple[str, str]], count: int) -> None:
        """Rewrite a whole day: slots 0..n-1 in order, each carrying the count.

        The controller ignores a lone slot write; it only accepts a day when all
        of its slots arrive in sequence (this is what the myVAILLANT app sends).
        """
        topic = f"{self._base}/{self._msg_prefix}_{TIMER_DAYS[DAY_KEYS.index(day)]}/set"
        for idx, (start, end) in enumerate(slots):
            payload = f"{idx};{count};{start};{end}"
            _LOGGER.debug("Writing time program: %s <- %s", topic, payload)
            await mqtt.async_publish(self.hass, topic, payload)
        # ask ebusd to re-read the controller
        await mqtt.async_publish(self.hass, f"{self._base}/{self._msg_prefix}_Timeframes/get", "?1")
        for idx in range(len(slots)):
            await mqtt.async_publish(
                self.hass, f"{self.config.slots[day][idx].read_topic}/get", "?1"
            )

    def _day_slots(self, day: str, count: int) -> list[tuple[str, str]]:
        """The first *count* slots of *day*; empty ones get a 10-minute default."""
        result: list[tuple[str, str]] = []
        for idx in range(count):
            start, end = self.slots[day][idx] or ("00:00", "00:00")
            s, e = _to_minutes(start), _to_minutes(end)
            if s is None or e is None or e <= s:
                # Empty slot: 10 minutes right after the previous slot.
                prev_end = _to_minutes(result[-1][1]) if result else None
                first = 8 * 60 if prev_end is None else prev_end + TIME_STEP_MINUTES
                if first + TIME_STEP_MINUTES > 24 * 60:
                    raise ServiceValidationError("No room left in the day for another slot")
                last = first + TIME_STEP_MINUTES
                start = f"{first // 60:02d}:{first % 60:02d}"
                end = f"{last // 60:02d}:{last % 60:02d}"
            result.append((start, end))
        return result

    async def async_set_slot_time(
        self, idx: int, *, start: str | None = None, end: str | None = None
    ):
        day = self.selected_day
        count = max(self.count(day), idx + 1)
        slots = self._day_slots(day, count)
        current = slots[idx]
        new_start, new_end = start or current[0], end or current[1]
        s, e = _to_minutes(new_start), _to_minutes(new_end)
        if start and not end and s is not None and e is not None and e <= s:
            # Moving the start past the end: shift the end to keep the duration.
            old_s, old_e = _to_minutes(current[0]), _to_minutes(current[1])
            duration = old_e - old_s if old_s is not None and old_e is not None else 0
            e = min(s + max(duration, 1), 24 * 60)
            new_end = f"{e // 60:02d}:{e % 60:02d}"
        if s is None or e is None or e <= s:
            raise ServiceValidationError(
                f"End time must be after start time (got {new_start} - {new_end})"
            )
        slots[idx] = (new_start, new_end)
        self._stage_day(day, slots)

    async def async_set_count(self, count: int) -> None:
        """Change the number of slots of the selected day (whole day is sent after the delay)."""
        day = self.selected_day
        if count == 0:
            first = self.slots[day][0] or ("00:00", "00:00")
            self._stage_day(day, [first], count=0)
            return
        self._stage_day(day, self._day_slots(day, count))
