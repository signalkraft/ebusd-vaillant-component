"""Sensor entities for ebusd Vaillant."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EbusdCoordinator
from .device import build_device_info
from .discovery import DiscoveredSensor, _get


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
            if isinstance(e, DiscoveredSensor) and e.key not in seen:
                seen.add(e.key)
                new.append(EbusdSensor(hass, e))
        if new:
            async_add_entities(new)

    coordinator.add_listener(_on_discover)


class _EbusdNumericSensor(SensorEntity):
    """Base class: subscribes to one MQTT topic and exposes a float value."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, read_topic: str, field: str) -> None:
        self.hass = hass
        self._read_topic = read_topic
        self._field = field
        self._attr_native_value: float | None = None
        self._unsubscribe: Any = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _handle(msg: mqtt.ReceiveMessage) -> None:
            try:
                payload = json.loads(msg.payload)
            except json.JSONDecodeError, ValueError:
                payload = msg.payload
            value = _get(payload, self._field)
            if value is not None:
                try:
                    self._attr_native_value = float(value)
                    self.async_write_ha_state()
                except TypeError, ValueError:
                    pass

        self._unsubscribe = await mqtt.async_subscribe(self.hass, self._read_topic, _handle)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()


class EbusdSensor(_EbusdNumericSensor):
    """Generic numeric sensor for ebusd Vaillant (energy, power, COP, pressure)."""

    def __init__(self, hass: HomeAssistant, config: DiscoveredSensor) -> None:
        super().__init__(hass, config.topic.read_topic, config.topic.field)
        self._attr_name = config.name
        self._attr_unique_id = f"{config.unique_id_prefix}_{config.key}"
        self._attr_device_class = (
            SensorDeviceClass(config.device_class) if config.device_class else None
        )
        self._attr_state_class = SensorStateClass(config.state_class)
        self._attr_native_unit_of_measurement = config.unit
        self._attr_device_info = build_device_info(config)
