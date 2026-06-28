"""Climate entities for ebusd Vaillant heating zones."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.climate import (
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    _STAT_HVAC_ACTION_COOLING,
    _STAT_HVAC_ACTION_HEATING,
    CONF_AWAY_MODE_DURATION,
    CONF_QUICK_VETO_DURATION,
    DEFAULT_AWAY_MODE_DURATION,
    DEFAULT_QUICK_VETO_DURATION,
    DOMAIN,
    EBUSD_TO_HA_HVAC,
    HA_TO_EBUSD_HVAC,
)
from .coordinator import EbusdCoordinator
from .device import build_device_info
from .discovery import (
    DiscoveredClimate,
    DiscoveredFlowTempRange,
    TopicConfig,
    _get,
)

_LOGGER = logging.getLogger(__name__)

_HA_HVAC_MODE = {
    "auto": HVACMode.AUTO,
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "off": HVACMode.OFF,
}

_HOLIDAY_RESET = "01.01.2015"
_DATE_FMT = "%d.%m.%Y"
_TIME_FMT = "%H:%M:%S"
_QUICK_VETO_CANCEL_DATE = "01.01.2015"
_QUICK_VETO_CANCEL_TIME = "00:00:00"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EbusdCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities_by_name: dict[str, EbusdClimateEntity] = {}
    flow_temp_by_key: dict[str, EbusdFlowTempRangeEntity] = {}
    away_duration = entry.options.get(CONF_AWAY_MODE_DURATION, DEFAULT_AWAY_MODE_DURATION)
    quick_veto_duration = entry.options.get(CONF_QUICK_VETO_DURATION, DEFAULT_QUICK_VETO_DURATION)

    def _on_discover(entities: list) -> None:
        new = []
        for e in entities:
            if isinstance(e, DiscoveredClimate):
                if e.name in entities_by_name:
                    hass.async_create_task(
                        entities_by_name[e.name].async_update_config(e, coordinator)
                    )
                else:
                    entity = EbusdClimateEntity(hass, e, away_duration, quick_veto_duration)
                    entities_by_name[e.name] = entity
                    new.append(entity)
            elif isinstance(e, DiscoveredFlowTempRange):
                if e.key not in flow_temp_by_key:
                    entity = EbusdFlowTempRangeEntity(hass, e, coordinator)
                    flow_temp_by_key[e.key] = entity
                    new.append(entity)

        if new:
            async_add_entities(new)

    coordinator.add_listener(_on_discover)


class EbusdClimateEntity(ClimateEntity):
    """Climate entity for a heating zone: target temperature, HVAC mode, and boost/away presets."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_preset_modes = [PRESET_NONE, PRESET_BOOST, PRESET_AWAY]
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        config: DiscoveredClimate,
        away_duration: int = DEFAULT_AWAY_MODE_DURATION,
        quick_veto_duration: int = DEFAULT_QUICK_VETO_DURATION,
    ) -> None:
        self.hass = hass
        self._config = config
        self._away_duration = away_duration
        self._quick_veto_duration = quick_veto_duration
        self._attr_name = None  # primary entity of the Zone device; device name is the label
        self._attr_unique_id = f"ebusd_climate_{config.key}"
        self._attr_device_info = build_device_info(config)
        self._attr_min_temp = config.min_temp
        self._attr_max_temp = config.max_temp
        self._attr_target_temperature_step = config.temp_step

        self._attr_hvac_modes = [_HA_HVAC_MODE[m] for m in config.hvac_modes if m in _HA_HVAC_MODE]
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_hvac_action = HVACAction.OFF

        self._attr_current_temperature: float | None = None
        self._attr_target_temperature: float | None = None
        self._attr_target_temperature_high: float | None = None
        self._attr_target_temperature_low: float | None = None

        self._holiday_start: str | None = None
        self._holiday_end: str | None = None
        self._quick_veto_end_date: str | None = None
        self._quick_veto_end_time: str | None = None

        self._run_data_statuscode: str | None = None
        self._hc_statuscode: str | None = None

        features = (
            ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.PRESET_MODE
        )
        if config.target_temperature:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if config.target_temperature_high or config.target_temperature_low:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        self._attr_supported_features = features

        self._unsubscribe: list[Any] = []

    async def async_added_to_hass(self) -> None:
        await self._subscribe(self._config.mode, self._handle_mode)
        if self._config.current_temperature:
            await self._subscribe(self._config.current_temperature, self._handle_current_temp)
        if self._config.target_temperature:
            await self._subscribe(self._config.target_temperature, self._handle_target_temp)
        if self._config.target_temperature_high:
            await self._subscribe(self._config.target_temperature_high, self._handle_target_high)
        if self._config.target_temperature_low:
            await self._subscribe(self._config.target_temperature_low, self._handle_target_low)
        if self._config.holiday_start:
            await self._subscribe(self._config.holiday_start, self._handle_holiday_start)
        if self._config.holiday_end:
            await self._subscribe(self._config.holiday_end, self._handle_holiday_end)
        if self._config.quick_veto_end_date:
            await self._subscribe(
                self._config.quick_veto_end_date, self._handle_quick_veto_end_date
            )
        if self._config.quick_veto_end_time:
            await self._subscribe(
                self._config.quick_veto_end_time, self._handle_quick_veto_end_time
            )
        if self._config.run_data_status:
            await self._subscribe(self._config.run_data_status, self._handle_run_data_statuscode)
        if self._config.hc_status:
            await self._subscribe(self._config.hc_status, self._handle_hc_statuscode)

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubscribe:
            unsub()

    async def async_update_config(
        self, config: DiscoveredClimate, coordinator: EbusdCoordinator
    ) -> None:
        """Subscribe to any temperature topics that became available after initial creation."""
        if config.target_temperature and not self._config.target_temperature:
            await self._subscribe(config.target_temperature, self._handle_target_temp)
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE
            val = coordinator.get_current_value(config.target_temperature)
            if val is not None:
                self._handle_target_temp(val)
        if config.target_temperature_high and not self._config.target_temperature_high:
            await self._subscribe(config.target_temperature_high, self._handle_target_high)
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            val = coordinator.get_current_value(config.target_temperature_high)
            if val is not None:
                self._handle_target_high(val)
        if config.target_temperature_low and not self._config.target_temperature_low:
            await self._subscribe(config.target_temperature_low, self._handle_target_low)
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            val = coordinator.get_current_value(config.target_temperature_low)
            if val is not None:
                self._handle_target_low(val)
        if config.run_data_status and not self._config.run_data_status:
            await self._subscribe(config.run_data_status, self._handle_run_data_statuscode)
            val = coordinator.get_current_value(config.run_data_status)
            if val is not None:
                self._handle_run_data_statuscode(val)
        if config.hc_status and not self._config.hc_status:
            await self._subscribe(config.hc_status, self._handle_hc_statuscode)
            val = coordinator.get_current_value(config.hc_status)
            if val is not None:
                self._handle_hc_statuscode(val)
        self._config = config
        self.async_write_ha_state()

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
    def _determine_hvac_action(self) -> HVACAction:
        """Derive hvac_action from current mode, run data status, and per-zone Hc{n}Status."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        global_heating = self._run_data_statuscode in _STAT_HVAC_ACTION_HEATING
        global_cooling = self._run_data_statuscode in _STAT_HVAC_ACTION_COOLING

        if self._hc_statuscode is not None:
            # Hc{n}Status=1 means this circuit is contributing; 0 means idle for this zone
            zone_active = self._hc_statuscode not in ("0", "false", "inactive", "off")
            if global_heating and zone_active:
                return HVACAction.HEATING
            if global_cooling and zone_active:
                return HVACAction.COOLING
            if global_heating or global_cooling:
                return HVACAction.IDLE
        else:
            if global_heating:
                return HVACAction.HEATING
            if global_cooling:
                return HVACAction.COOLING

        if self._attr_hvac_mode == HVACMode.HEAT:
            return HVACAction.HEATING
        if self._attr_hvac_mode == HVACMode.COOL:
            return HVACAction.COOLING
        if self._attr_hvac_mode == HVACMode.AUTO:
            return HVACAction.IDLE
        return HVACAction.OFF

    @callback
    def _handle_mode(self, value: str) -> None:
        ha_mode = EBUSD_TO_HA_HVAC.get(str(value), "off")
        self._attr_hvac_mode = _HA_HVAC_MODE.get(ha_mode, HVACMode.OFF)
        self._attr_hvac_action = self._determine_hvac_action()

    @callback
    def _handle_run_data_statuscode(self, value: Any) -> None:
        self._run_data_statuscode = str(value)
        self._attr_hvac_action = self._determine_hvac_action()

    @callback
    def _handle_hc_statuscode(self, value: Any) -> None:
        self._hc_statuscode = str(value)
        self._attr_hvac_action = self._determine_hvac_action()

    @callback
    def _handle_current_temp(self, value: Any) -> None:
        try:
            self._attr_current_temperature = float(value)
        except TypeError, ValueError:
            pass

    @callback
    def _handle_target_temp(self, value: Any) -> None:
        try:
            self._attr_target_temperature = float(value)
        except TypeError, ValueError:
            pass

    @callback
    def _handle_target_high(self, value: Any) -> None:
        try:
            self._attr_target_temperature_high = float(value)
        except TypeError, ValueError:
            pass

    @callback
    def _handle_target_low(self, value: Any) -> None:
        try:
            self._attr_target_temperature_low = float(value)
        except TypeError, ValueError:
            pass

    @callback
    def _handle_holiday_start(self, value: Any) -> None:
        self._holiday_start = str(value)

    @callback
    def _handle_holiday_end(self, value: Any) -> None:
        self._holiday_end = str(value)

    @callback
    def _handle_quick_veto_end_date(self, value: Any) -> None:
        self._quick_veto_end_date = str(value)

    @callback
    def _handle_quick_veto_end_time(self, value: Any) -> None:
        self._quick_veto_end_time = str(value)

    @property
    def preset_mode(self) -> str | None:
        if not (self._attr_supported_features & ClimateEntityFeature.PRESET_MODE):
            return None
        if self._quick_veto_end_date and self._quick_veto_end_time:
            try:
                veto_end = datetime.strptime(
                    f"{self._quick_veto_end_date} {self._quick_veto_end_time}",
                    f"{_DATE_FMT} {_TIME_FMT}",
                )
                if veto_end > datetime.now():
                    return PRESET_BOOST
            except ValueError:
                pass
        if self._holiday_start and self._holiday_end:
            try:
                now = datetime.now().date()
                start = datetime.strptime(self._holiday_start, _DATE_FMT).date()
                end = datetime.strptime(self._holiday_end, _DATE_FMT).date()
                if start <= now <= end:
                    return PRESET_AWAY
            except ValueError:
                pass
        return PRESET_NONE

    async def _publish(self, topic: str, payload: str) -> None:
        _LOGGER.debug("MQTT publish: %s -> %s", topic, payload)
        await mqtt.async_publish(self.hass, topic, payload)

    async def _cancel_quick_veto(self) -> None:
        if self._config.quick_veto_duration and self._config.quick_veto_duration.write_topic:
            await self._publish(self._config.quick_veto_duration.write_topic, "0")
        if self._config.quick_veto_end_date and self._config.quick_veto_end_date.write_topic:
            await self._publish(
                self._config.quick_veto_end_date.write_topic, _QUICK_VETO_CANCEL_DATE
            )
        if self._config.quick_veto_end_time and self._config.quick_veto_end_time.write_topic:
            await self._publish(
                self._config.quick_veto_end_time.write_topic, _QUICK_VETO_CANCEL_TIME
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        current = self.preset_mode
        if current == PRESET_BOOST and preset_mode != PRESET_BOOST:
            await self._cancel_quick_veto()
        if preset_mode == PRESET_AWAY and current != PRESET_AWAY:
            today = datetime.now().date()
            start_str = today.strftime(_DATE_FMT)
            end_str = (today + timedelta(days=self._away_duration)).strftime(_DATE_FMT)
            if self._config.holiday_start:
                await self._publish(self._config.holiday_start.write_topic, start_str)
            if self._config.holiday_end:
                await self._publish(self._config.holiday_end.write_topic, end_str)
        elif preset_mode != PRESET_AWAY and current == PRESET_AWAY:
            if self._config.holiday_start:
                await self._publish(self._config.holiday_start.write_topic, _HOLIDAY_RESET)
            if self._config.holiday_end:
                await self._publish(self._config.holiday_end.write_topic, _HOLIDAY_RESET)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        ebusd_mode = HA_TO_EBUSD_HVAC.get(hvac_mode.value, "auto")
        cfg = self._config.mode
        if cfg.write_topic is None:
            return
        if cfg.write_key:
            payload = json.dumps({cfg.write_key: ebusd_mode})
        else:
            payload = ebusd_mode
        await self._publish(cfg.write_topic, payload)

    async def _publish_quick_veto(self, temp: float) -> None:
        qv = self._config.quick_veto_temp
        if qv and qv.write_topic:
            await self._publish(qv.write_topic, str(temp))
        qd = self._config.quick_veto_duration
        if qd and qd.write_topic:
            await self._publish(qd.write_topic, str(self._quick_veto_duration))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE in kwargs and self._config.target_temperature:
            await self._publish_quick_veto(kwargs[ATTR_TEMPERATURE])

        high = kwargs.get("target_temp_high")
        low = kwargs.get("target_temp_low")
        if high is not None and self._config.target_temperature_high:
            cfg = self._config.target_temperature_high
            if cfg.write_topic:
                await self._publish(cfg.write_topic, str(high))
        if low is not None and self._config.target_temperature_low:
            await self._publish_quick_veto(low)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)


class _EbusdSetpointBase(ClimateEntity):
    """Shared base for simple setpoint-only climate entities (no modes or presets)."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_hvac_action = HVACAction.IDLE

    def __init__(self, hass: HomeAssistant, coordinator: EbusdCoordinator) -> None:
        self.hass = hass
        self._coordinator = coordinator
        self._run_data_statuscode: str | None = None
        self._unsubscribe: list[Any] = []

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

    def _seed(self, topic_cfg: TopicConfig, handler: Any) -> None:
        if (v := self._coordinator.get_current_value(topic_cfg)) is not None:
            handler(v)

    async def _subscribe_run_data_status(self, topic_cfg: TopicConfig | None) -> None:
        if topic_cfg is None:
            return
        await self._subscribe(topic_cfg, self._handle_run_data_statuscode)
        self._seed(topic_cfg, self._handle_run_data_statuscode)

    @callback
    def _handle_run_data_statuscode(self, value: Any) -> None:
        self._run_data_statuscode = str(value)
        self._attr_hvac_action = self._compute_hvac_action()

    def _compute_hvac_action(self) -> HVACAction:
        if self._run_data_statuscode in _STAT_HVAC_ACTION_HEATING:
            return HVACAction.HEATING
        if self._run_data_statuscode in _STAT_HVAC_ACTION_COOLING:
            return HVACAction.COOLING
        return HVACAction.IDLE

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubscribe:
            unsub()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        pass


class EbusdFlowTempRangeEntity(_EbusdSetpointBase):
    """Min/max heating circuit flow temperature range (Hc{n}MinFlowTempDesired / Max)."""

    _attr_hvac_modes = [HVACMode.AUTO]
    _attr_hvac_mode = HVACMode.AUTO
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

    def __init__(
        self, hass: HomeAssistant, config: DiscoveredFlowTempRange, coordinator: EbusdCoordinator
    ) -> None:
        super().__init__(hass, coordinator)
        self._config = config
        self._attr_name = "Heating Flow Temperature"
        self._attr_unique_id = f"ebusd_flow_temp_range_{config.key}"
        self._attr_device_info = build_device_info(config)
        self._attr_min_temp = config.min_temp
        self._attr_max_temp = config.max_temp
        self._attr_target_temperature_step = config.temp_step
        self._attr_target_temperature_low: float | None = None
        self._attr_target_temperature_high: float | None = None
        self._attr_current_temperature: float | None = None

    async def async_added_to_hass(self) -> None:
        await self._subscribe(self._config.min_flow_temp, self._handle_min)
        await self._subscribe(self._config.max_flow_temp, self._handle_max)
        if self._config.current_flow_temp:
            await self._subscribe(self._config.current_flow_temp, self._handle_current_flow_temp)
            self._seed(self._config.current_flow_temp, self._handle_current_flow_temp)
        await self._subscribe_run_data_status(self._config.run_data_status)
        self._seed(self._config.min_flow_temp, self._handle_min)
        self._seed(self._config.max_flow_temp, self._handle_max)
        self.async_write_ha_state()

    @callback
    def _handle_min(self, value: Any) -> None:
        try:
            self._attr_target_temperature_low = float(value)
        except TypeError, ValueError:
            pass

    @callback
    def _handle_max(self, value: Any) -> None:
        try:
            self._attr_target_temperature_high = float(value)
        except TypeError, ValueError:
            pass

    @callback
    def _handle_current_flow_temp(self, value: Any) -> None:
        try:
            self._attr_current_temperature = float(value)
        except TypeError, ValueError:
            pass

    async def async_set_temperature(self, **kwargs: Any) -> None:
        low = kwargs.get("target_temp_low")
        high = kwargs.get("target_temp_high")
        if low is not None and self._config.min_flow_temp.write_topic:
            await mqtt.async_publish(self.hass, self._config.min_flow_temp.write_topic, str(low))
        if high is not None and self._config.max_flow_temp.write_topic:
            await mqtt.async_publish(self.hass, self._config.max_flow_temp.write_topic, str(high))
