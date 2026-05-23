"""Datetime entities for ebusd Vaillant quick veto end time."""

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EbusdCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities_by_key: dict[str, EbusdQuickVetoEndEntity] = {}

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
