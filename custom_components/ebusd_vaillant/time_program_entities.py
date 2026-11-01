"""Select / number / time entities that edit a weekly time program."""

from __future__ import annotations

from datetime import time

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity

from .device import build_device_info
from .discovery import TIMER_DAYS, TIMER_SLOTS_PER_DAY, DiscoveredTimeProgram
from .time_program import DAY_KEYS
from .time_program_editor import TimeProgramEditor, from_time, get_editor, to_time

# Only programs without a target temperature are editable for now.
EDITABLE_PROGRAMS = ("circulation",)


def editable(config: object) -> bool:
    return isinstance(config, DiscoveredTimeProgram) and config.program in EDITABLE_PROGRAMS


class _EditorEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config: DiscoveredTimeProgram, suffix: str, name: str):
        self.hass = hass
        self._editor: TimeProgramEditor = get_editor(hass, config)
        self._attr_name = f"{self._editor.label} {name}"
        self._attr_unique_id = f"ebusd_tp_edit_{config.key}_{suffix}"
        self._attr_device_info = build_device_info(config)

    async def async_added_to_hass(self) -> None:
        await self._editor.async_acquire()
        self.async_on_remove(self._editor.add_listener(self._changed))
        self.async_on_remove(self._editor.release)

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._editor.ready

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        return {"pending_write": self._editor.has_pending}


class EbusdTimeProgramDaySelect(_EditorEntity, SelectEntity):
    _attr_icon = "mdi:calendar-week"
    _attr_options = [d.capitalize() for d in DAY_KEYS]

    def __init__(self, hass: HomeAssistant, config: DiscoveredTimeProgram) -> None:
        super().__init__(hass, config, "day", "day")

    @property
    def current_option(self) -> str:
        return self._editor.selected_day.capitalize()

    async def async_select_option(self, option: str) -> None:
        self._editor.select_day(option.lower())


class EbusdTimeProgramSlotCount(_EditorEntity, NumberEntity):
    _attr_icon = "mdi:counter"
    _attr_native_min_value = 0
    _attr_native_max_value = TIMER_SLOTS_PER_DAY
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, hass: HomeAssistant, config: DiscoveredTimeProgram) -> None:
        super().__init__(hass, config, "slots", "slots")

    @property
    def native_value(self) -> float:
        return self._editor.count()

    async def async_set_native_value(self, value: float) -> None:
        await self._editor.async_set_count(int(value))


class EbusdTimeProgramSlotTime(_EditorEntity, TimeEntity):
    _attr_icon = "mdi:clock-outline"

    def __init__(self, hass: HomeAssistant, config: DiscoveredTimeProgram, idx: int, end: bool):
        part = "end" if end else "start"
        super().__init__(hass, config, f"slot{idx + 1}_{part}", f"slot {idx + 1} {part}")
        self._idx = idx
        self._end = end

    @property
    def available(self) -> bool:
        return self._editor.ready and self._idx < self._editor.count()

    @property
    def native_value(self) -> time | None:
        slot = self._editor.slot(self._idx)
        return to_time(slot[1 if self._end else 0]) if slot else None

    async def async_set_value(self, value: time) -> None:
        text = from_time(value)
        if self._end:
            await self._editor.async_set_slot_time(self._idx, end=text)
        else:
            await self._editor.async_set_slot_time(self._idx, start=text)
