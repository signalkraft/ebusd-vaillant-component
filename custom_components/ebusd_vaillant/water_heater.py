"""Water heater entities for ebusd Vaillant hot water circuits."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
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

from .const import CONF_AWAY_MODE_DURATION, DEFAULT_AWAY_MODE_DURATION, DOMAIN
from .coordinator import EbusdCoordinator
from .device import build_device_info
from .discovery import DiscoveredWaterHeater, TopicConfig, _get

_LOGGER = logging.getLogger(__name__)

_HOLIDAY_RESET = "01.01.2015"
_DATE_FMT = "%d.%m.%Y"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EbusdCoordinator = hass.data[DOMAIN][entry.entry_id]
    seen: set[str] = set()
    away_duration = entry.options.get(CONF_AWAY_MODE_DURATION, DEFAULT_AWAY_MODE_DURATION)
    entities_by_key: dict[str, EbusdWaterHeaterEntity] = {}

    def _on_discover(entities: list) -> None:
        new = []
        for e in entities:
            if isinstance(e, DiscoveredWaterHeater):
                if e.name in entities_by_key:
                    hass.async_create_task(entities_by_key[e.name].async_update_config(e))
                elif e.name not in seen:
                    seen.add(e.name)
                    entity = EbusdWaterHeaterEntity(hass, e, coordinator, away_duration)
                    entities_by_key[e.name] = entity
                    new.append(entity)
        if new:
            async_add_entities(new)

    coordinator.add_listener(_on_discover)


class EbusdWaterHeaterEntity(WaterHeaterEntity):
    """Water heater for a hot water circuit: temperature, operation mode, away mode, and on/off."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "ebusd_water_heater"

    def __init__(
        self,
        hass: HomeAssistant,
        config: DiscoveredWaterHeater,
        coordinator: EbusdCoordinator,
        away_duration: int = DEFAULT_AWAY_MODE_DURATION,
    ) -> None:
        self.hass = hass
        self._config = config
        self._coordinator = coordinator
        self._away_duration = away_duration
        self._attr_name = None  # primary entity of the Hot Water device; device name is the label
        self._attr_unique_id = f"ebusd_water_heater_{config.key}"
        self._attr_device_info = build_device_info(config)
        self._attr_min_temp = config.min_temp
        self._attr_max_temp = config.max_temp
        self._attr_target_temperature_step = config.temp_step
        if config.sf_mode:
            self._attr_operation_list = [*config.operation_modes, "boost"]
        else:
            self._attr_operation_list = config.operation_modes
        self._attr_current_operation: str | None = None
        self._attr_current_temperature: float | None = None
        self._attr_target_temperature: float | None = None
        self._holiday_start: str | None = None
        self._holiday_end: str | None = None
        self._sf_mode: str | None = None
        self._raw_operation: str | None = None
        self._unsubscribe: list[Any] = []

        features = (
            WaterHeaterEntityFeature.TARGET_TEMPERATURE
            | WaterHeaterEntityFeature.OPERATION_MODE
            | WaterHeaterEntityFeature.ON_OFF
            | WaterHeaterEntityFeature.AWAY_MODE
        )
        self._attr_supported_features = features

    async def async_added_to_hass(self) -> None:
        await self._subscribe(self._config.mode, self._handle_mode)
        await self._subscribe(self._config.target_temperature, self._handle_target_temp)
        if self._config.current_temperature:
            await self._subscribe(self._config.current_temperature, self._handle_current_temp)
        if self._config.holiday_start:
            await self._subscribe(self._config.holiday_start, self._handle_holiday_start)
        if self._config.holiday_end:
            await self._subscribe(self._config.holiday_end, self._handle_holiday_end)
        if self._config.sf_mode:
            await self._subscribe(self._config.sf_mode, self._handle_sf_mode)
        self._seed_from_coordinator()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubscribe:
            unsub()

    async def async_update_config(self, config: DiscoveredWaterHeater) -> None:
        if config.holiday_start and not self._config.holiday_start:
            await self._subscribe(config.holiday_start, self._handle_holiday_start)
            if (v := self._coordinator.get_current_value(config.holiday_start)) is not None:
                self._handle_holiday_start(v)
        if config.holiday_end and not self._config.holiday_end:
            await self._subscribe(config.holiday_end, self._handle_holiday_end)
            if (v := self._coordinator.get_current_value(config.holiday_end)) is not None:
                self._handle_holiday_end(v)
        if config.sf_mode and not self._config.sf_mode:
            await self._subscribe(config.sf_mode, self._handle_sf_mode)
            if (v := self._coordinator.get_current_value(config.sf_mode)) is not None:
                self._handle_sf_mode(v)
            self._attr_operation_list = [*config.operation_modes, "boost"]
        self._config = config
        self.async_write_ha_state()

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
        if self._config.holiday_start:
            if (v := self._coordinator.get_current_value(self._config.holiday_start)) is not None:
                self._handle_holiday_start(v)
        if self._config.holiday_end:
            if (v := self._coordinator.get_current_value(self._config.holiday_end)) is not None:
                self._handle_holiday_end(v)
        if self._config.sf_mode:
            if (v := self._coordinator.get_current_value(self._config.sf_mode)) is not None:
                self._handle_sf_mode(v)

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
        self._raw_operation = str(value)
        self._attr_current_operation = "boost" if self._sf_mode == "load" else self._raw_operation

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

    @callback
    def _handle_holiday_start(self, value: Any) -> None:
        self._holiday_start = str(value)

    @callback
    def _handle_holiday_end(self, value: Any) -> None:
        self._holiday_end = str(value)

    @callback
    def _handle_sf_mode(self, value: Any) -> None:
        self._sf_mode = str(value)
        if self._raw_operation is not None:
            self._attr_current_operation = (
                "boost" if self._sf_mode == "load" else self._raw_operation
            )

    @property
    def is_away_mode_on(self) -> bool | None:
        if not self._holiday_start or not self._holiday_end:
            return None
        try:
            now = datetime.now().date()
            start = datetime.strptime(self._holiday_start, _DATE_FMT).date()
            end = datetime.strptime(self._holiday_end, _DATE_FMT).date()
            return start <= now <= end
        except ValueError:
            return None

    async def _publish(self, topic: str, payload: str) -> None:
        _LOGGER.debug("MQTT publish: %s -> %s", topic, payload)
        await mqtt.async_publish(self.hass, topic, payload)

    async def async_turn_away_mode_on(self) -> None:
        today = datetime.now().date()
        start_str = today.strftime(_DATE_FMT)
        end_str = (today + timedelta(days=self._away_duration)).strftime(_DATE_FMT)
        await self._publish(self._config.holiday_start.write_topic, start_str)
        await self._publish(self._config.holiday_end.write_topic, end_str)

    async def async_turn_away_mode_off(self) -> None:
        await self._publish(self._config.holiday_start.write_topic, _HOLIDAY_RESET)
        await self._publish(self._config.holiday_end.write_topic, _HOLIDAY_RESET)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        cfg = self._config.target_temperature
        if cfg.write_topic:
            await mqtt.async_publish(self.hass, cfg.write_topic, str(temp))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == "boost":
            if self._config.sf_mode and self._config.sf_mode.write_topic:
                await self._publish(self._config.sf_mode.write_topic, "load")
            return
        if self._config.sf_mode and self._config.sf_mode.write_topic and self._sf_mode == "load":
            await self._publish(self._config.sf_mode.write_topic, "auto")
        cfg = self._config.mode
        if cfg.write_topic:
            await self._publish(cfg.write_topic, operation_mode)

    async def async_turn_on(self) -> None:
        await self.async_set_operation_mode("auto")

    async def async_turn_off(self) -> None:
        await self.async_set_operation_mode("off")
