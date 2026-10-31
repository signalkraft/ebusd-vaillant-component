"""Parse ebusd timer messages into a weekly schedule and evaluate it.

Pure functions (no Home Assistant imports) so they can be unit-tested directly.

ebusd message layout (ctlv2, ``15.ctlv2.csv``):

* ``Z1Timer_Timeframes``: 7 fields ``slotcount`` .. ``slotcount_6``, the number
  of active slots per day, Monday first.
* ``Z1Timer_Monday0`` .. ``Z1Timer_Sunday2``: ``htm`` (start), ``htm_1`` (end)
  and, except for circulation, ``slottemp`` (target temperature).
  An end of ``24:00`` means midnight at the end of that day.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .discovery import TIMER_DAYS, payload_values

DAY_KEYS: tuple[str, ...] = tuple(d.lower() for d in TIMER_DAYS)
_MINUTES_PER_DAY = 24 * 60

Slot = dict[str, Any]  # {"start": "07:00", "end": "20:30", "temperature": 21.0}
Schedule = dict[str, list[Slot]]


def _to_minutes(value: Any) -> int | None:
    """Convert an ``HH:MM`` string (``24:00`` allowed) to minutes after midnight."""
    if not isinstance(value, str):
        return None
    hh, sep, mm = value.strip().partition(":")
    if not sep:
        return None
    try:
        minutes = int(hh) * 60 + int(mm)
    except ValueError:
        return None
    if not 0 <= minutes <= _MINUTES_PER_DAY:
        return None
    return minutes


def parse_slot_counts(payload: Any) -> list[int] | None:
    """Return the 7 per-day slot counts (Monday first), or None if unusable."""
    values = payload_values(payload)
    if len(values) < len(DAY_KEYS):
        return None
    try:
        return [int(v) for v in values[: len(DAY_KEYS)]]
    except TypeError, ValueError:
        return None


def parse_slot(payload: Any, has_temperature: bool = True) -> Slot | None:
    """Parse one ``*Timer_{Day}{n}`` payload into a slot dict, or None if invalid."""
    values = payload_values(payload)
    if len(values) < 2:
        return None
    start, end = _to_minutes(values[0]), _to_minutes(values[1])
    if start is None or end is None or end <= start:
        return None  # includes unused slots reported as 00:00-00:00
    slot: Slot = {"start": values[0], "end": values[1]}
    if has_temperature:
        temp = values[2] if len(values) > 2 else None
        try:
            slot["temperature"] = float(temp) if temp is not None else None
        except TypeError, ValueError:
            slot["temperature"] = None
    return slot


def build_schedule(
    counts: list[int] | None,
    slot_payloads: dict[str, list[Any]],
    has_temperature: bool = True,
) -> Schedule:
    """Combine slot counts and raw slot payloads into ``{day: [slot, ...]}``.

    Only the first ``counts[day]`` slots of a day are used: the controller keeps
    stale data in unused slot registers.  Without counts (Timeframes not received
    yet), every slot with a valid, non-empty time range is used.
    """
    schedule: Schedule = {}
    for i, day in enumerate(DAY_KEYS):
        limit = counts[i] if counts is not None else None
        slots: list[Slot] = []
        for idx, raw in enumerate(slot_payloads.get(day, [])):
            if limit is not None and idx >= limit:
                break
            slot = parse_slot(raw, has_temperature)
            if slot is not None:
                slots.append(slot)
        slots.sort(key=lambda s: _to_minutes(s["start"]))
        schedule[day] = slots
    return schedule


def slot_at(schedule: Schedule, when: datetime) -> Slot | None:
    """Return the slot active at *when*, or None."""
    minute = when.hour * 60 + when.minute
    for slot in schedule.get(DAY_KEYS[when.weekday()], []):
        if _to_minutes(slot["start"]) <= minute < _to_minutes(slot["end"]):
            return slot
    return None


def _state_key(slot: Slot | None) -> tuple:
    return (slot is not None, slot.get("temperature") if slot else None)


def next_change(schedule: Schedule, now: datetime) -> datetime | None:
    """Return the next time the active state or slot temperature changes.

    Adjacent slots with the same temperature (e.g. 00:00-07:00 and 07:00-20:30,
    both 21 °C) are treated as one continuous period.  Returns None when the
    schedule is constant for the whole week (empty or always on at one value).
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    boundaries: set[datetime] = set()
    for offset in range(8):
        day = DAY_KEYS[(now.weekday() + offset) % 7]
        base = midnight + timedelta(days=offset)
        boundaries.add(base)
        for slot in schedule.get(day, []):
            boundaries.add(base + timedelta(minutes=_to_minutes(slot["start"])))
            boundaries.add(base + timedelta(minutes=_to_minutes(slot["end"])))
    current = _state_key(slot_at(schedule, now))
    for boundary in sorted(b for b in boundaries if b > now):
        if _state_key(slot_at(schedule, boundary)) != current:
            return boundary
    return None
