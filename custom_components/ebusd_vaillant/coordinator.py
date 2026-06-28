"""Persistent MQTT listener that discovers ebusd entities as topics appear."""

from __future__ import annotations

import json
import logging
from asyncio import Task
from collections.abc import Callable
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    _DISCOVERY_TOPICS_HC,
    _DISCOVERY_TOPICS_HWC,
    _DISCOVERY_TOPICS_PRESSURE,
    _DISCOVERY_TOPICS_ZONE,
    CONF_MAX_ZONES,
    CONF_PRIME_VALUES,
    CONF_ZONES_WITH_TEMP_ONLY,
    DEFAULT_MAX_ZONES,
    DEFAULT_PRIME_VALUES,
    DEFAULT_ZONES_WITH_TEMP_ONLY,
    DISCOVERY_DEVICE_NAMES,
)
from .discovery import (
    DiscoveredClimate,
    DiscoveredCoolTempLimit,
    DiscoveredFlowTempRange,
    DiscoveredPressureSensor,
    DiscoveredWaterHeater,
    TopicConfig,
    _analyze,
    _get,
)

_LOGGER = logging.getLogger(__name__)

DiscoveredEntity = DiscoveredClimate | DiscoveredWaterHeater | DiscoveredPressureSensor


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
            e.run_data_status is not None,
            e.hc_status is not None,
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
        self._bg_tasks: list[Task] = []
        self._stopping: bool = False

    async def async_start(self) -> None:
        self._unsub = await mqtt.async_subscribe(
            self._hass, f"{self._prefix}/#", self._handle_message
        )
        _LOGGER.debug("ebusd coordinator: listening on %s/#", self._prefix)
        if self._entry.options.get(CONF_PRIME_VALUES, DEFAULT_PRIME_VALUES):
            self._schedule_task(self._discovery_prime(), "ebusd discovery prime")

    async def _discovery_prime(self) -> None:
        """Publish ?1 to minimal discovery topics for common device names.

        Triggers ebusd to publish the few values needed for _analyze() to
        discover entities.  Unknown devices/topics are silently ignored.
        Once entities are discovered, _prime_values() handles the full set.
        """
        max_zones = self._entry.options.get(CONF_MAX_ZONES, DEFAULT_MAX_ZONES)
        topics: list[str] = [
            *[
                self._prefix + "/" + dev + "/" + t
                for dev in DISCOVERY_DEVICE_NAMES
                for t in _DISCOVERY_TOPICS_HWC
            ],
            *[
                self._prefix + "/" + dev + "/" + t
                for dev in DISCOVERY_DEVICE_NAMES
                for t in _DISCOVERY_TOPICS_PRESSURE
            ],
            *[
                self._prefix + "/" + dev + "/" + t.format(n=z)
                for dev in DISCOVERY_DEVICE_NAMES
                for z in range(1, max_zones + 1)
                for t in _DISCOVERY_TOPICS_ZONE
            ],
            *[
                self._prefix + "/" + dev + "/" + t.format(n=hc)
                for dev in DISCOVERY_DEVICE_NAMES
                for hc in range(1, max_zones + 1)
                for t in _DISCOVERY_TOPICS_HC
            ],
        ]
        _LOGGER.info("Priming discovery: sending %d get requests", len(topics))
        for topic in topics:
            if self._stopping:
                return
            await mqtt.async_publish(self._hass, topic + "/get", "?1")

    def async_stop(self) -> None:
        self._stopping = True
        if self._unsub:
            self._unsub()
            self._unsub = None
        for task in self._bg_tasks:
            task.cancel()
        self._bg_tasks.clear()

    def _schedule_task(self, coro, name: str) -> None:
        task = self._hass.async_create_background_task(coro, name)
        self._bg_tasks.append(task)

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
            zones_with_temp_only=self._entry.options.get(
                CONF_ZONES_WITH_TEMP_ONLY, DEFAULT_ZONES_WITH_TEMP_ONLY
            ),
        )
        if entities:
            listener(entities)
            if self._entry.options.get(CONF_PRIME_VALUES, DEFAULT_PRIME_VALUES):
                self._schedule_task(self._prime_values(entities), "ebusd prime values")

    def _collect_read_topics(self, entities: list[DiscoveredEntity]) -> set[str]:
        """Collect all unique read topics from discovered entities."""
        topics: set[str] = set()
        for entity in entities:
            if isinstance(entity, DiscoveredPressureSensor):
                topics.add(entity.topic.read_topic)
                continue
            if isinstance(entity, DiscoveredWaterHeater):
                topic_attrs = [
                    entity.mode,
                    entity.target_temperature,
                    entity.current_temperature,
                    entity.sf_mode,
                    entity.holiday_start,
                    entity.holiday_end,
                    entity.holiday_start_time,
                    entity.holiday_end_time,
                ]
            elif isinstance(entity, DiscoveredFlowTempRange):
                topic_attrs = [
                    entity.min_flow_temp,
                    entity.max_flow_temp,
                    entity.current_flow_temp,
                    entity.run_data_status,
                ]
            elif isinstance(entity, DiscoveredCoolTempLimit):
                topic_attrs = [
                    entity.cool_temp,
                    entity.run_data_status,
                ]
            else:  # DiscoveredClimate
                topic_attrs = [
                    entity.mode,
                    entity.current_temperature,
                    entity.target_temperature,
                    entity.target_temperature_high,
                    entity.target_temperature_low,
                    entity.holiday_start,
                    entity.holiday_end,
                    entity.holiday_start_time,
                    entity.holiday_end_time,
                    entity.quick_veto_temp,
                    entity.quick_veto_duration,
                    entity.quick_veto_end_date,
                    entity.quick_veto_end_time,
                    entity.run_data_status,
                    entity.hc_status,
                ]
            for cfg in topic_attrs:
                if cfg is not None:
                    topics.add(cfg.read_topic)
        return topics

    async def _prime_values(self, entities: list[DiscoveredEntity]) -> None:
        """Publish ?1 to /get topics to prime polling priority for all known values."""
        topics = self._collect_read_topics(entities)
        for topic in topics:
            if self._stopping:
                return
            get_topic = f"{topic}/get"
            _LOGGER.debug("Priming value: %s", get_topic)
            await mqtt.async_publish(self._hass, get_topic, "?1")

    @callback
    def _handle_message(self, msg: mqtt.ReceiveMessage) -> None:
        parts = msg.topic.split("/")
        if len(parts) < 3:
            return
        device, msg_name = parts[1], parts[2]
        if device in ("global", "Broadcast") or msg.topic.endswith("/get"):
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
            zones_with_temp_only=self._entry.options.get(
                CONF_ZONES_WITH_TEMP_ONLY, DEFAULT_ZONES_WITH_TEMP_ONLY
            ),
        )
        new_sigs = frozenset(_entity_sig(e) for e in entities)
        if new_sigs == self._known_entity_sigs:
            return  # no change in entity set or config  -  skip listener calls
        self._known_entity_sigs = new_sigs
        _LOGGER.debug("Discovered entities: %s", sorted(e.name for e in entities))
        for listener in self._listeners:
            listener(entities)
        if self._entry.options.get(CONF_PRIME_VALUES, DEFAULT_PRIME_VALUES):
            self._schedule_task(self._prime_values(entities), "ebusd prime values")
