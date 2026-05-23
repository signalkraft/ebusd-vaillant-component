"""Water heater entities for ebusd Vaillant hot water circuits."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EbusdCoordinator
from .discovery import DiscoveredWaterHeater, TopicConfig, _get

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
            if isinstance(e, DiscoveredWaterHeater) and e.name not in seen:
                seen.add(e.name)
                new.append(EbusdWaterHeaterEntity(hass, e, coordinator))
        if new:
            async_add_entities(new)

    coordinator.add_listener(_on_discover)


class EbusdWaterHeaterEntity(WaterHeaterEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "ebusd_water_heater"
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )

    def __init__(
        self, hass: HomeAssistant, config: DiscoveredWaterHeater, coordinator: EbusdCoordinator
    ) -> None:
        self.hass = hass
        self._config = config
        self._coordinator = coordinator
        self._attr_name = config.name
        self._attr_unique_id = f"ebusd_water_heater_{config.key}"
        self._attr_min_temp = config.min_temp
        self._attr_max_temp = config.max_temp
        self._attr_target_temperature_step = config.temp_step
        self._attr_operation_list = config.operation_modes
        self._attr_current_operation: str | None = None
        self._attr_current_temperature: float | None = None
        self._attr_target_temperature: float | None = None
        self._unsubscribe: list[Any] = []

    async def async_added_to_hass(self) -> None:
        await self._subscribe(self._config.mode, self._handle_mode)
        await self._subscribe(self._config.target_temperature, self._handle_target_temp)
        if self._config.current_temperature:
            await self._subscribe(self._config.current_temperature, self._handle_current_temp)
        self._seed_from_coordinator()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubscribe:
            unsub()

    def _seed_from_coordinator(self) -> None:
        if (v := self._coordinator.get_current_value(self._config.mode)) is not None:
            self._handle_mode(v)
        if (v := self._coordinator.get_current_value(self._config.target_temperature)) is not None:
            self._handle_target_temp(v)
        if self._config.current_temperature:
            if (
                v := self._coordinator.get_current_value(self._config.current_temperature)
            ) is not None:
                self._handle_current_temp(v)

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
    def _handle_mode(self, value: str) -> None:
        mode = str(value)
        if mode in self._attr_operation_list:
            self._attr_current_operation = mode
        else:
            _LOGGER.warning("Unknown HWC operation mode from ebusd: %s", mode)
            self._attr_current_operation = mode

    @callback
    def _handle_target_temp(self, value: Any) -> None:
        try:
            self._attr_target_temperature = float(value)
        except (TypeError, ValueError):  # fmt: skip
            pass

    @callback
    def _handle_current_temp(self, value: Any) -> None:
        try:
            self._attr_current_temperature = float(value)
        except (TypeError, ValueError):  # fmt: skip
            pass

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        cfg = self._config.target_temperature
        if cfg.write_topic:
            await mqtt.async_publish(self.hass, cfg.write_topic, str(temp))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        cfg = self._config.mode
        if cfg.write_topic:
            await mqtt.async_publish(self.hass, cfg.write_topic, operation_mode)

    async def async_turn_on(self) -> None:
        await self.async_set_operation_mode("auto")

    async def async_turn_off(self) -> None:
        await self.async_set_operation_mode("off")
