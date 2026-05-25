"""Persistent MQTT listener that discovers ebusd entities as topics appear."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_MAX_ZONES, DEFAULT_MAX_ZONES
from .discovery import (
    DiscoveredClimate,
    DiscoveredPressureSensor,
    DiscoveredWaterHeater,
    TopicConfig,
    _analyze,
    _get,
)

_LOGGER = logging.getLogger(__name__)

DiscoveredEntity = DiscoveredClimate | DiscoveredWaterHeater


def _entity_sig(e: DiscoveredClimate | DiscoveredWaterHeater | DiscoveredPressureSensor) -> tuple:
    """Return a signature tuple that changes when an entity gains new topic configuration."""
    if isinstance(e, DiscoveredClimate):
        return (
            e.name,
            e.target_temperature is not None,
            e.target_temperature_high is not None,
            e.target_temperature_low is not None,
            e.holiday_start_time is not None,
            e.holiday_end_time is not None,
        )
    if isinstance(e, DiscoveredWaterHeater):
        return (
            e.name,
            e.holiday_start is not None,
            e.holiday_end is not None,
            e.holiday_start_time is not None,
            e.holiday_end_time is not None,
            e.sf_mode is not None,
        )
    return (e.name,)


Listener = Callable[[list[DiscoveredEntity]], None]


class EbusdCoordinator:
    """Subscribes to ebusd/# and notifies listeners whenever new entities are discovered."""

    def __init__(
        self, hass: HomeAssistant, prefix: str, display_name: str, entry: ConfigEntry
    ) -> None:
        self._hass = hass
        self._prefix = prefix
        self._display_name = display_name
        self._entry = entry
        self._by_device: dict[str, dict[str, Any]] = {}
        self._listeners: list[Listener] = []
        self._known_entity_sigs: frozenset[tuple] = frozenset()
        self._unsub: Callable | None = None

    async def async_start(self) -> None:
        self._unsub = await mqtt.async_subscribe(
            self._hass, f"{self._prefix}/#", self._handle_message
        )
        _LOGGER.debug("ebusd coordinator: listening on %s/#", self._prefix)

    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    @property
    def mqtt_values(self) -> dict[str, dict[str, Any]]:
        return dict(self._by_device)

    def get_current_value(self, topic_cfg: TopicConfig) -> Any:
        """Return the cached value for a topic config, or None if not yet received."""
        parts = topic_cfg.read_topic.split("/")
        if len(parts) < 3:
            return None
        device, msg = parts[1], parts[2]
        payload = self._by_device.get(device, {}).get(msg)
        return _get(payload, topic_cfg.field)

    def add_listener(self, listener: Listener) -> None:
        """Register a listener. Fires immediately with current state, then on each new discovery."""
        self._listeners.append(listener)
        entities = _analyze(
            self._by_device,
            self._prefix,
            self._display_name,
            max_zones=self._entry.options.get(CONF_MAX_ZONES, DEFAULT_MAX_ZONES),
        )
        if entities:
            listener(entities)

    @callback
    def _handle_message(self, msg: mqtt.ReceiveMessage) -> None:
        parts = msg.topic.split("/")
        if len(parts) < 3:
            return
        device, msg_name = parts[1], parts[2]
        if device in ("global", "Broadcast"):
            return

        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError, ValueError:
            payload = msg.payload

        device_msgs = self._by_device.setdefault(device, {})
        if device_msgs.get(msg_name) == payload:
            return  # unchanged  -  skip re-analysis

        device_msgs[msg_name] = payload
        entities = _analyze(
            self._by_device,
            self._prefix,
            self._display_name,
            max_zones=self._entry.options.get(CONF_MAX_ZONES, DEFAULT_MAX_ZONES),
        )
        new_sigs = frozenset(_entity_sig(e) for e in entities)
        if new_sigs == self._known_entity_sigs:
            return  # no change in entity set or config  -  skip listener calls
        self._known_entity_sigs = new_sigs
        _LOGGER.debug("Discovered entities: %s", sorted(e.name for e in entities))
        for listener in self._listeners:
            listener(entities)
