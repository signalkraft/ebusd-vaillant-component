"""Sensor entities for ebusd Vaillant."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import EbusdCoordinator
from .device import build_device_info
from .discovery import DiscoveredSensor, DiscoveredTimeProgram, _get
from .time_program import build_schedule, next_change, parse_slot_counts, slot_at

TIME_PROGRAM_STATES = ["active", "inactive"]


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
            elif isinstance(e, DiscoveredTimeProgram) and e.key not in seen:
                seen.add(e.key)
                new.append(EbusdTimeProgramSensor(hass, e))
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


def _decode(payload: Any) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError, ValueError:
        return payload


class EbusdTimeProgramSensor(SensorEntity):
    """Read-only weekly time program (schedule) of a zone, hot water or circulation."""

    # State is "active" while the current time lies inside a time slot.  Attributes:
    # schedule (full week), slot_start / slot_end / slot_temperature, next_change.

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = TIME_PROGRAM_STATES
    _attr_translation_key = "ebusd_time_program"

    def __init__(self, hass: HomeAssistant, config: DiscoveredTimeProgram) -> None:
        self.hass = hass
        self._config = config
        self._attr_name = config.name
        self._attr_unique_id = f"ebusd_time_program_{config.key}"
        self._attr_device_info = build_device_info(config)
        self._counts: list[int] | None = None
        self._slot_payloads: dict[str, list[Any]] = {
            day: [None] * len(topics) for day, topics in config.slots.items()
        }
        self._received = False
        self._unsubscribers: list[Any] = []
        self._unsub_timer: Any = None
        self._attr_native_value: str | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_timeframes(msg: mqtt.ReceiveMessage) -> None:
            counts = parse_slot_counts(_decode(msg.payload))
            if counts is not None:
                self._counts = counts
                self._received = True
                self._refresh()

        self._unsubscribers.append(
            await mqtt.async_subscribe(
                self.hass, self._config.timeframes.read_topic, _on_timeframes
            )
        )
        for day, topics in self._config.slots.items():
            for idx, topic in enumerate(topics):
                self._unsubscribers.append(
                    await mqtt.async_subscribe(
                        self.hass, topic.read_topic, self._slot_handler(day, idx)
                    )
                )

    def _slot_handler(self, day: str, idx: int):
        @callback
        def _handle(msg: mqtt.ReceiveMessage) -> None:
            self._slot_payloads[day][idx] = _decode(msg.payload)
            self._received = True
            self._refresh()

        return _handle

    @callback
    def _refresh(self, _now: Any = None) -> None:
        """Recompute state + attributes and schedule the next re-evaluation."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if not self._received:
            return
        schedule = build_schedule(self._counts, self._slot_payloads, self._config.has_temperature)
        now = dt_util.now()
        current = slot_at(schedule, now)
        change = next_change(schedule, now)
        self._attr_native_value = "active" if current else "inactive"
        attrs: dict[str, Any] = {
            "program": self._config.program,
            "schedule": schedule,
            "slot_start": current["start"] if current else None,
            "slot_end": current["end"] if current else None,
            "next_change": change.isoformat() if change else None,
        }
        if self._config.has_temperature:
            attrs["slot_temperature"] = current.get("temperature") if current else None
        self._attr_extra_state_attributes = attrs
        if change is not None:
            self._unsub_timer = async_track_point_in_time(self.hass, self._refresh, change)
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
