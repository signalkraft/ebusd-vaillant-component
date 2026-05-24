"""Datetime entities for ebusd Vaillant."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EbusdCoordinator
from .discovery import DiscoveredClimate, TopicConfig, _get

_LOGGER = logging.getLogger(__name__)

_DATE_FMT = "%d.%m.%Y"
_TIME_FMT = "%H:%M:%S"
_HOLIDAY_RESET = "01.01.2015"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EbusdCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities_by_key: dict[str, DateTimeEntity] = {}

    def _on_discover(entities: list) -> None:
        new = []
        for e in entities:
            if not isinstance(e, DiscoveredClimate):
                continue
            key = f"{e.key}_quick_veto_end"
            if key not in entities_by_key:
                entity = EbusdQuickVetoEndEntity(hass, e)
                entities_by_key[key] = entity
                new.append(entity)
            key = f"{e.key}_holiday_start"
            if key in entities_by_key:
                hass.async_create_task(entities_by_key[key].async_update_config(e))
            else:
                entity = EbusdHolidayEntity(
                    hass,
                    coordinator,
                    e,
                    "holiday_start",
                    "holiday_start_time",
                    "Holiday Start",
                    "holiday_start",
                )
                entities_by_key[key] = entity
                new.append(entity)
            key = f"{e.key}_holiday_end"
            if key in entities_by_key:
                hass.async_create_task(entities_by_key[key].async_update_config(e))
            else:
                entity = EbusdHolidayEntity(
                    hass,
                    coordinator,
                    e,
                    "holiday_end",
                    "holiday_end_time",
                    "Holiday End",
                    "holiday_end",
                )
                entities_by_key[key] = entity
                new.append(entity)
        if new:
            async_add_entities(new)

    coordinator.add_listener(_on_discover)


class EbusdQuickVetoEndEntity(DateTimeEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, config: DiscoveredClimate) -> None:
        self.hass = hass
        self._config = config
        self._attr_name = f"{config.name} Quick Veto End"
        self._attr_unique_id = f"ebusd_quick_veto_end_{config.key}"
        self._attr_native_value: datetime | None = None
        self._end_date: str | None = None
        self._end_time: str | None = None
        self._unsubscribe: list[Any] = []

    async def async_added_to_hass(self) -> None:
        if self._config.quick_veto_end_date:
            await self._subscribe(self._config.quick_veto_end_date, self._handle_end_date)
        if self._config.quick_veto_end_time:
            await self._subscribe(self._config.quick_veto_end_time, self._handle_end_time)

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
                self._update_native_value()
                self.async_write_ha_state()

        unsub = await mqtt.async_subscribe(self.hass, topic_cfg.read_topic, _wrap)
        self._unsubscribe.append(unsub)

    @callback
    def _handle_end_date(self, value: Any) -> None:
        self._end_date = str(value)

    @callback
    def _handle_end_time(self, value: Any) -> None:
        self._end_time = str(value)

    def _update_native_value(self) -> None:
        if not self._end_date or not self._end_time:
            self._attr_native_value = None
            return
        try:
            self._attr_native_value = datetime.strptime(
                f"{self._end_date} {self._end_time}", f"{_DATE_FMT} {_TIME_FMT}"
            ).replace(tzinfo=UTC)
        except ValueError:
            self._attr_native_value = None

    async def async_set_value(self, value: datetime) -> None:
        pass


class EbusdHolidayEntity(DateTimeEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: EbusdCoordinator,
        config: DiscoveredClimate,
        date_attr: str,
        time_attr: str,
        name_suffix: str,
        unique_id_suffix: str,
    ) -> None:
        self.hass = hass
        self._coordinator = coordinator
        self._config = config
        self._date_attr = date_attr
        self._time_attr = time_attr
        self._attr_name = f"{config.name} {name_suffix}"
        self._attr_unique_id = f"ebusd_{unique_id_suffix}_{config.key}"
        self._attr_native_value: datetime | None = None
        self._date: str | None = None
        self._time: str | None = None
        time_cfg = getattr(config, time_attr)
        if not time_cfg:
            self._time = "00:00:00"
        self._unsubscribe: list[Any] = []

    async def async_added_to_hass(self) -> None:
        date_cfg = getattr(self._config, self._date_attr)
        if date_cfg:
            await self._subscribe(date_cfg, self._handle_date)
        time_cfg = getattr(self._config, self._time_attr)
        if time_cfg:
            await self._subscribe(time_cfg, self._handle_time)

    async def async_update_config(self, config: DiscoveredClimate) -> None:
        old_time_cfg = getattr(self._config, self._time_attr)
        new_time_cfg = getattr(config, self._time_attr)
        if new_time_cfg and not old_time_cfg:
            await self._subscribe(new_time_cfg, self._handle_time)
            val = self._coordinator.get_current_value(new_time_cfg)
            if val is not None:
                self._time = str(val)
            else:
                self._time = "00:00:00"
            self._update_native_value()
            self.async_write_ha_state()
        self._config = config

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
                self._update_native_value()
                self.async_write_ha_state()

        unsub = await mqtt.async_subscribe(self.hass, topic_cfg.read_topic, _wrap)
        self._unsubscribe.append(unsub)

    @callback
    def _handle_date(self, value: Any) -> None:
        self._date = str(value)

    @callback
    def _handle_time(self, value: Any) -> None:
        self._time = str(value)

    def _update_native_value(self) -> None:
        if not self._date or not self._time or self._date == _HOLIDAY_RESET:
            self._attr_native_value = None
            return
        try:
            self._attr_native_value = datetime.strptime(
                f"{self._date} {self._time}", f"{_DATE_FMT} {_TIME_FMT}"
            ).replace(tzinfo=UTC)
        except ValueError:
            self._attr_native_value = None

    async def async_set_value(self, value: datetime) -> None:
        date_str = value.strftime(_DATE_FMT)
        date_cfg = getattr(self._config, self._date_attr)
        if date_cfg and date_cfg.write_topic:
            _LOGGER.debug("MQTT publish: %s -> %s", date_cfg.write_topic, date_str)
            await mqtt.async_publish(self.hass, date_cfg.write_topic, date_str)
