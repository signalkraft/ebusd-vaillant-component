"""Sensor entities for ebusd Vaillant."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPressure
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EbusdCoordinator
from .device import build_device_info
from .discovery import DiscoveredPressureSensor, _get

_LOGGER = logging.getLogger(__name__)


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
            if isinstance(e, DiscoveredPressureSensor) and e.key not in seen:
                seen.add(e.key)
                new.append(EbusdPressureSensor(hass, e))
        if new:
            async_add_entities(new)

    coordinator.add_listener(_on_discover)


class EbusdPressureSensor(SensorEntity):
    """Pressure sensor measuring heating system water pressure in bar."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPressure.BAR

    def __init__(self, hass: HomeAssistant, config: DiscoveredPressureSensor) -> None:
        self.hass = hass
        self._config = config
        self._attr_name = "Water Pressure"
        self._attr_unique_id = f"ebusd_pressure_{config.key}"
        self._attr_device_info = build_device_info(config)
        self._attr_native_value: float | None = None
        self._unsubscribe: Any = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _handle(msg: mqtt.ReceiveMessage) -> None:
            try:
                payload = json.loads(msg.payload)
            except json.JSONDecodeError, ValueError:
                payload = msg.payload
            value = _get(payload, self._config.topic.field)
            if value is not None:
                try:
                    self._attr_native_value = float(value)
                except TypeError, ValueError:
                    pass
                self.async_write_ha_state()

        self._unsubscribe = await mqtt.async_subscribe(
            self.hass, self._config.topic.read_topic, _handle
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
