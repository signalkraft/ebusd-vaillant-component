"""Time entities for ebusd Vaillant time programs."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EbusdCoordinator
from .discovery import TIMER_SLOTS_PER_DAY
from .time_program_entities import EbusdTimeProgramSlotTime, editable


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EbusdCoordinator = hass.data[DOMAIN][entry.entry_id]
    seen: set[str] = set()

    def _on_discover(entities: list) -> None:
        new = []
        for e in entities:
            if editable(e) and e.key not in seen:
                seen.add(e.key)
                for idx in range(TIMER_SLOTS_PER_DAY):
                    for end in (False, True):
                        new.append(EbusdTimeProgramSlotTime(hass, e, idx, end))
        if new:
            async_add_entities(new)

    coordinator.add_listener(_on_discover)
