"""Switch entities for ebusd Vaillant away mode and hot water boost."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_AWAY_MODE_DURATION, DEFAULT_AWAY_MODE_DURATION, DOMAIN
from .coordinator import EbusdCoordinator
from .discovery import DiscoveredClimate, DiscoveredWaterHeater, TopicConfig, _get

_LOGGER = logging.getLogger(__name__)

_HOLIDAY_RESET = "01.01.2015"
_DATE_FMT = "%d.%m.%Y"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EbusdCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities_by_key: dict[
        str, EbusdAwayModeSwitch | EbusdHwcAwayModeSwitch | EbusdHwcBoostSwitch
    ] = {}
    away_duration = entry.options.get(CONF_AWAY_MODE_DURATION, DEFAULT_AWAY_MODE_DURATION)

    def _on_discover(entities: list) -> None:
        new = []
        for e in entities:
            if isinstance(e, DiscoveredClimate):
                key = f"{e.key}_away_mode"
                if key not in entities_by_key:
                    entity = EbusdAwayModeSwitch(hass, e, away_duration)
                    entities_by_key[key] = entity
                    new.append(entity)
            elif isinstance(e, DiscoveredWaterHeater):
                if e.holiday_start and e.holiday_end:
                    key = f"{e.key}_away_mode"
                    if key not in entities_by_key:
                        entity = EbusdHwcAwayModeSwitch(hass, e, away_duration)
                        entities_by_key[key] = entity
                        new.append(entity)
                if e.sf_mode:
                    key2 = f"{e.key}_boost"
                    if key2 not in entities_by_key:
                        entity = EbusdHwcBoostSwitch(hass, e)
                        entities_by_key[key2] = entity
                        new.append(entity)
        if new:
            async_add_entities(new)

    coordinator.add_listener(_on_discover)


class EbusdAwayModeSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:airplane-takeoff"

    def __init__(self, hass: HomeAssistant, config: DiscoveredClimate, away_duration: int) -> None:
        self.hass = hass
        self._config = config
        self._away_duration = away_duration
        self._attr_name = f"{config.name} Away Mode"
        self._attr_unique_id = f"ebusd_away_mode_{config.key}"
        self._holiday_start: str | None = None
        self._holiday_end: str | None = None
        self._unsubscribe: list[Any] = []

    async def async_added_to_hass(self) -> None:
        if self._config.holiday_start:
            await self._subscribe(self._config.holiday_start, self._handle_holiday_start)
        if self._config.holiday_end:
            await self._subscribe(self._config.holiday_end, self._handle_holiday_end)

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubscribe:
            unsub()

    async def _subscribe(self, topic_cfg: TopicConfig, handler: Any) -> None:
        @callback
        def _wrap(msg: mqtt.ReceiveMessage) -> None:
            try:
                payload = json.loads(msg.payload)
            except json.JSONDecodeError, ValueError:
                payload = msg.payload
            value = _get(payload, topic_cfg.field)
            if value is not None:
                handler(value)
                self.async_write_ha_state()

        unsub = await mqtt.async_subscribe(self.hass, topic_cfg.read_topic, _wrap)
        self._unsubscribe.append(unsub)

    @callback
    def _handle_holiday_start(self, value: Any) -> None:
        self._holiday_start = str(value)

    @callback
    def _handle_holiday_end(self, value: Any) -> None:
        self._holiday_end = str(value)

    @property
    def is_on(self) -> bool:
        if not self._holiday_start or not self._holiday_end:
            return False
        try:
            now = datetime.now().date()
            start = datetime.strptime(self._holiday_start, _DATE_FMT).date()
            end = datetime.strptime(self._holiday_end, _DATE_FMT).date()
            return start <= now <= end
        except ValueError:
            return False

    async def _publish(self, topic: str, payload: str) -> None:
        _LOGGER.debug("MQTT publish: %s -> %s", topic, payload)
        await mqtt.async_publish(self.hass, topic, payload)

    async def async_turn_on(self, **kwargs: Any) -> None:
        today = datetime.now().date()
        start_str = today.strftime(_DATE_FMT)
        end_str = (today + timedelta(days=self._away_duration)).strftime(_DATE_FMT)
        await self._publish(self._config.holiday_start.write_topic, start_str)
        await self._publish(self._config.holiday_end.write_topic, end_str)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._publish(self._config.holiday_start.write_topic, _HOLIDAY_RESET)
        await self._publish(self._config.holiday_end.write_topic, _HOLIDAY_RESET)


class EbusdHwcAwayModeSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:airplane-takeoff"

    def __init__(
        self, hass: HomeAssistant, config: DiscoveredWaterHeater, away_duration: int
    ) -> None:
        self.hass = hass
        self._config = config
        self._away_duration = away_duration
        self._attr_name = f"{config.name} Away Mode"
        self._attr_unique_id = f"ebusd_away_mode_{config.key}"
        self._holiday_start: str | None = None
        self._holiday_end: str | None = None
        self._unsubscribe: list[Any] = []

    async def async_added_to_hass(self) -> None:
        if self._config.holiday_start:
            await self._subscribe(self._config.holiday_start, self._handle_holiday_start)
        if self._config.holiday_end:
            await self._subscribe(self._config.holiday_end, self._handle_holiday_end)

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubscribe:
            unsub()

    async def _subscribe(self, topic_cfg: TopicConfig, handler: Any) -> None:
        @callback
        def _wrap(msg: mqtt.ReceiveMessage) -> None:
            try:
                payload = json.loads(msg.payload)
            except json.JSONDecodeError, ValueError:
                payload = msg.payload
            value = _get(payload, topic_cfg.field)
            if value is not None:
                handler(value)
                self.async_write_ha_state()

        unsub = await mqtt.async_subscribe(self.hass, topic_cfg.read_topic, _wrap)
        self._unsubscribe.append(unsub)

    @callback
    def _handle_holiday_start(self, value: Any) -> None:
        self._holiday_start = str(value)

    @callback
    def _handle_holiday_end(self, value: Any) -> None:
        self._holiday_end = str(value)

    @property
    def is_on(self) -> bool:
        if not self._holiday_start or not self._holiday_end:
            return False
        try:
            now = datetime.now().date()
            start = datetime.strptime(self._holiday_start, _DATE_FMT).date()
            end = datetime.strptime(self._holiday_end, _DATE_FMT).date()
            return start <= now <= end
        except ValueError:
            return False

    async def _publish(self, topic: str, payload: str) -> None:
        _LOGGER.debug("MQTT publish: %s -> %s", topic, payload)
        await mqtt.async_publish(self.hass, topic, payload)

    async def async_turn_on(self, **kwargs: Any) -> None:
        today = datetime.now().date()
        start_str = today.strftime(_DATE_FMT)
        end_str = (today + timedelta(days=self._away_duration)).strftime(_DATE_FMT)
        if self._config.holiday_start:
            await self._publish(self._config.holiday_start.write_topic, start_str)
        if self._config.holiday_end:
            await self._publish(self._config.holiday_end.write_topic, end_str)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._config.holiday_start:
            await self._publish(self._config.holiday_start.write_topic, _HOLIDAY_RESET)
        if self._config.holiday_end:
            await self._publish(self._config.holiday_end.write_topic, _HOLIDAY_RESET)


class EbusdHwcBoostSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:water-boiler-alert"

    def __init__(self, hass: HomeAssistant, config: DiscoveredWaterHeater) -> None:
        self.hass = hass
        self._config = config
        self._attr_name = f"{config.name} Boost"
        self._attr_unique_id = f"ebusd_boost_{config.key}"
        self._sf_mode: str | None = None
        self._unsubscribe: list[Any] = []

    async def async_added_to_hass(self) -> None:
        if self._config.sf_mode:
            await self._subscribe(self._config.sf_mode, self._handle_sf_mode)

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubscribe:
            unsub()

    async def _subscribe(self, topic_cfg: TopicConfig, handler: Any) -> None:
        @callback
        def _wrap(msg: mqtt.ReceiveMessage) -> None:
            try:
                payload = json.loads(msg.payload)
            except (json.JSONDecodeError, ValueError):  # fmt: skip
                payload = msg.payload
            value = _get(payload, topic_cfg.field)
            if value is not None:
                handler(value)
                self.async_write_ha_state()

        unsub = await mqtt.async_subscribe(self.hass, topic_cfg.read_topic, _wrap)
        self._unsubscribe.append(unsub)

    @callback
    def _handle_sf_mode(self, value: Any) -> None:
        self._sf_mode = str(value)

    @property
    def is_on(self) -> bool:
        return self._sf_mode == "load"

    async def _publish(self, topic: str, payload: str) -> None:
        _LOGGER.debug("MQTT publish: %s -> %s", topic, payload)
        await mqtt.async_publish(self.hass, topic, payload)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._config.sf_mode and self._config.sf_mode.write_topic:
            await self._publish(self._config.sf_mode.write_topic, "load")

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._config.sf_mode and self._config.sf_mode.write_topic:
            await self._publish(self._config.sf_mode.write_topic, "auto")
