"""Discover ebusd devices from MQTT topic data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TopicConfig:
    """How to read/write a single value over MQTT."""

    read_topic: str
    # dot-notation path into the JSON payload, e.g. "value.value" or "hcmode.value"
    field: str
    write_topic: str | None = None
    # for multi-field write payloads: the key to wrap the value in, e.g. "hcmode"
    write_key: str | None = None


@dataclass
class DiscoveredClimate:
    device_id: str
    key: str  # stable identifier for unique_id (device_id + zone), never changes
    name: str
    mode: TopicConfig
    hvac_modes: list[str]
    current_temperature: TopicConfig | None = None
    target_temperature: TopicConfig | None = None
    target_temperature_high: TopicConfig | None = None
    target_temperature_low: TopicConfig | None = None
    holiday_start: TopicConfig | None = None
    holiday_end: TopicConfig | None = None
    holiday_start_time: TopicConfig | None = None
    holiday_end_time: TopicConfig | None = None
    quick_veto_temp: TopicConfig | None = None
    quick_veto_duration: TopicConfig | None = None
    quick_veto_end_date: TopicConfig | None = None
    quick_veto_end_time: TopicConfig | None = None
    min_temp: float = 5.0
    max_temp: float = 30.0
    temp_step: float = 0.5


@dataclass
class DiscoveredSensor:
    device_id: str
    key: str
    name: str
    topic: TopicConfig
    device_class: str | None
    state_class: str
    unit: str | None
    unique_id_prefix: str


@dataclass
class DiscoveredWaterHeater:
    device_id: str
    key: str  # stable identifier for unique_id (device_id + hwc), never changes
    name: str
    mode: TopicConfig
    target_temperature: TopicConfig
    current_temperature: TopicConfig | None = None
    operation_modes: list[str] = field(default_factory=lambda: ["auto", "day", "off"])
    sf_mode: TopicConfig | None = None
    holiday_start: TopicConfig | None = None
    holiday_end: TopicConfig | None = None
    holiday_start_time: TopicConfig | None = None
    holiday_end_time: TopicConfig | None = None
    min_temp: float = 40.0
    max_temp: float = 80.0
    temp_step: float = 1.0


def _get(payload: Any, dot_path: str) -> Any:
    """Extract a value from a nested dict using dot-notation path.

    Returns the payload directly when dot_path is empty (scalar value).
    """
    if not dot_path:
        return payload
    obj = payload
    for key in dot_path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _infer_field(payload: Any) -> str:
    """Derive dot-path from payload structure.

    Format 0 (scalar value):
        "plain_string"  or  42  →  ""

    Format 1 (scalar wrapper):
        {"value": {"value": X}}  →  "value.value"

    Format 2 (named sub-fields):
        {"fieldname": {"value": X}}  →  "fieldname.value"
    """
    if not isinstance(payload, dict):
        return "value.value" if payload is None else ""
    if "value" in payload:
        return "value.value"
    for key, val in payload.items():
        if isinstance(val, dict) and "value" in val:
            return f"{key}.value"
    return "value.value"


# Extensible key-pattern table.
# Each role maps to an ordered list of candidate key name patterns.
# "{n}" is replaced with the zone number where applicable.
# Exact match is tried first, then case-insensitive fallback.
_ROLE_PATTERNS: dict[str, list[str]] = {
    "hwc_op_mode": ["HwcOpMode", "HwcOPMode"],
    "hwc_target_temp": ["HwcTempDesired"],
    "hwc_current_temp": [
        "HwcStorageTemp",
        "HwcStorageTempBottom",
        "HwcStorageTempTop",
        "DisplayedHwcStorageTemp",
    ],
    "zone_op_mode": [
        "Z{n}OpMode",
        "z{n}OpModeHeating",
        "z{n}OpModeCooling",
        "z{n}OpMode",
    ],
    "zone_room_temp": ["Z{n}RoomTemp", "z{n}RoomTemp"],
    "zone_day_temp": [
        "Z{n}DayTemp",
        "Z{n}ManualTemp",
        "z{n}HeatingRoomTempDesiredManualControlled",
    ],
    "zone_cooling_temp": [
        "Z{n}CoolingTemp",
        "Z{n}CoolingTempDesired",
        "Z{n}CoolingManualTemp",
        "z{n}CoolingRoomTempDesiredManualControlled",
    ],
    "zone_night_temp": ["Z{n}NightTemp", "z{n}SetBackTemp"],
    "zone_circuit_type": ["Hc{n}CircuitType"],
    "zone_room_zone_mapping": ["Z{n}RoomZoneMapping"],
    "zone_holiday_start": [
        "Z{n}HolidayStartDate",
        "Z{n}HolidayStartPeriod",
        "z{n}HolidayStartDate",
    ],
    "zone_holiday_end": [
        "Z{n}HolidayEndDate",
        "Z{n}HolidayEndPeriod",
        "z{n}HolidayEndDate",
    ],
    "zone_quick_veto_temp": ["Z{n}QuickVetoTemp"],
    "zone_quick_veto_duration": ["Z{n}QuickVetoDuration"],
    "zone_quick_veto_end_date": ["Z{n}QuickVetoEndDate"],
    "zone_quick_veto_end_time": ["Z{n}QuickVetoEndTime"],
    "zone_holiday_start_time": ["z{n}HolidayStartTime", "Z{n}HolidayStartTime"],
    "zone_holiday_end_time": ["z{n}HolidayEndTime", "Z{n}HolidayEndTime"],
    "hwc_sf_mode": ["HwcSFMode"],
    "hwc_holiday_start": ["HwcHolidayStartPeriod", "HwcHolidayStartDate"],
    "hwc_holiday_end": ["HwcHolidayEndPeriod", "HwcHolidayEndDate"],
    "hwc_holiday_start_time": ["HwcHolidayStartTime"],
    "hwc_holiday_end_time": ["HwcHolidayEndTime"],
}


@dataclass(frozen=True)
class SensorConfig:
    """Descriptor for an auto-discovered numeric sensor.

    topic_keys: ordered tuple of MQTT topic names — first found wins.
    key: optional override for the entity key suffix (defaults to topic_keys[0].lower()).
    unique_id_prefix: prefix used to build the entity unique_id.
    """

    topic_keys: tuple[str, ...]
    name: str
    state_class: str
    unit: str | None = None
    device_class: str | None = None
    key: str | None = None
    unique_id_prefix: str = "ebusd_sensor"


def _power(topic: str, name: str) -> SensorConfig:
    return SensorConfig((topic,), name, "measurement", "kW", "power")


def _energy(topic: str, name: str) -> SensorConfig:
    return SensorConfig((topic,), name, "total_increasing", "kWh", "energy")


def _cop(topic: str, name: str) -> SensorConfig:
    return SensorConfig((topic,), name, "measurement")


def _pressure(topics: tuple[str, ...], name: str, key: str) -> SensorConfig:
    return SensorConfig(
        topics,
        name,
        "measurement",
        "bar",
        "pressure",
        key=key,
        unique_id_prefix="ebusd_pressure",
    )


# Sensors auto-discovered when a matching ebusd topic is present.
# HA Energy dashboard compatible: cumulative kWh values use total_increasing.
_SENSOR_CONFIGS: list[SensorConfig] = [
    _pressure(("WaterPressure", "DisplaySystemPressure"), "Water Pressure", "pressure"),
    _power("PowerConsumptionHmu", "Heat Pump Electrical Power"),
    _power("CurrentConsumedPower", "Electrical Power Consumed"),
    _power("CurrentYieldPower", "Heat Power Generated"),
    _energy("TotalEnergyUsage", "Consumed Electrical Energy"),
    _energy("ConsumptionTotal", "Total Electrical Consumption"),
    _energy("YieldHc", "Heat Generated Heating"),
    _energy("YieldHwc", "Heat Generated Domestic Hot Water"),
    _energy("YieldCooling", "Heat Generated Cooling"),
    _energy("YieldTotal", "Earned Environment Energy"),
    _energy("SolarYieldTotal", "Solar Energy Generated"),
    _energy("PrEnergySumHc", "Consumed Electrical Energy Heating"),
    _energy("PrEnergySumHwc", "Consumed Electrical Energy Domestic Hot Water"),
    _energy("YieldHcDay", "Heat Generated Heating Today"),
    _energy("YieldHwcDay", "Heat Generated Domestic Hot Water Today"),
    _energy("YieldCoolDay", "Heat Generated Cooling Today"),
    _energy("YieldHcMonth", "Heat Generated Heating This Month"),
    _energy("YieldHwcMonth", "Heat Generated Domestic Hot Water This Month"),
    _energy("YieldCoolingMonth", "Heat Generated Cooling This Month"),
    _cop("CopHc", "COP Heating"),
    _cop("CopHcMonth", "COP Heating This Month"),
    _cop("CopHwc", "COP Domestic Hot Water"),
    _cop("CopHwcMonth", "COP Domestic Hot Water This Month"),
    _cop("CopCooling", "COP Cooling"),
    _cop("CopCoolingMonth", "COP Cooling This Month"),
]


def _resolve_key(msgs: dict[str, Any], role: str, **fmt_kwargs: Any) -> str | None:
    """Resolve a message role to an actual key present in msgs.

    Tries each pattern in order: exact match first, then case-insensitive
    fallback.  Returns the matched key (as it appears in *msgs*) or *None*.
    """
    patterns = _ROLE_PATTERNS[role]
    for pat in patterns:
        key = pat.format(**fmt_kwargs)
        if key in msgs:
            return key
    lower_map = {k.lower(): k for k in msgs}
    for pat in patterns:
        key = pat.format(**fmt_kwargs)
        if key.lower() in lower_map:
            return lower_map[key.lower()]
    return None


def _find_topic(msgs: dict[str, Any], patterns: list[str]) -> tuple[str | None, str | None]:
    """Find the first matching topic for a list of candidate names.

    At top level: tries every pattern in exact match first, then every pattern
    in case-insensitive match — so an exact match on a later pattern wins over
    a case-insensitive match on an earlier one. Falls back to searching the
    candidates as sub-fields inside multi-value messages.
    Returns (msg_key, field_path) or (None, None).
    """
    for pat in patterns:
        if pat in msgs:
            return pat, _infer_field(msgs[pat])
    lower_map = {k.lower(): k for k in msgs}
    for pat in patterns:
        actual = lower_map.get(pat.lower())
        if actual is not None:
            return actual, _infer_field(msgs[actual])

    for msg_name, payload in msgs.items():
        if not isinstance(payload, dict):
            continue
        low_payload = {k.lower(): k for k in payload}
        for pat in patterns:
            sub = pat if pat in payload else low_payload.get(pat.lower())
            if sub is not None:
                return msg_name, f"{sub}.value"
    return None, None


def _find_nested(
    msgs: dict[str, Any], role: str, **fmt_kwargs: Any
) -> tuple[str | None, str | None]:
    """Resolve a role to a (msg_key, field_path) pair."""
    patterns = [p.format(**fmt_kwargs) for p in _ROLE_PATTERNS[role]]
    return _find_topic(msgs, patterns)


def _topic_config(
    prefix: str,
    device: str,
    msg: str,
    field: str,
    writable: bool = True,
    write_key: str | None = None,
) -> TopicConfig:
    read = f"{prefix}/{device}/{msg}"
    write = f"{read}/set" if writable else None
    return TopicConfig(read_topic=read, field=field, write_topic=write, write_key=write_key)


def _analyze(
    by_device: dict[str, dict[str, Any]],
    prefix: str,
    display_name: str = "Vaillant",
    max_zones: int = 4,
) -> list[DiscoveredClimate | DiscoveredWaterHeater | DiscoveredSensor]:
    """Build a list of discovered entities from per-device message dicts."""
    entities: list[DiscoveredClimate | DiscoveredWaterHeater | DiscoveredSensor] = []

    for device_id, msgs in by_device.items():
        # --- Water heater: HwcOpMode + HwcTempDesired required ---
        hwc_op_key = _resolve_key(msgs, "hwc_op_mode")
        hwc_target_key = _resolve_key(msgs, "hwc_target_temp")
        if hwc_op_key and hwc_target_key:
            hwc_current_key = _resolve_key(msgs, "hwc_current_temp") or "HwcStorageTemp"
            hwc_h_start_key, hwc_h_start_field = _find_nested(msgs, "hwc_holiday_start")
            hwc_h_end_key, hwc_h_end_field = _find_nested(msgs, "hwc_holiday_end")
            hwc_h_st_key, hwc_h_st_field = _find_nested(msgs, "hwc_holiday_start_time")
            hwc_h_et_key, hwc_h_et_field = _find_nested(msgs, "hwc_holiday_end_time")
            hwc_sf_key = _resolve_key(msgs, "hwc_sf_mode")
            entities.append(
                DiscoveredWaterHeater(
                    device_id=device_id,
                    key=f"{device_id}_hwc",
                    name=f"{display_name} Hot Water",
                    mode=_topic_config(
                        prefix, device_id, hwc_op_key, _infer_field(msgs[hwc_op_key])
                    ),
                    target_temperature=_topic_config(
                        prefix, device_id, hwc_target_key, _infer_field(msgs[hwc_target_key])
                    ),
                    current_temperature=_topic_config(
                        prefix,
                        device_id,
                        hwc_current_key,
                        _infer_field(msgs.get(hwc_current_key)),
                        writable=False,
                    ),
                    sf_mode=(
                        _topic_config(prefix, device_id, hwc_sf_key, _infer_field(msgs[hwc_sf_key]))
                        if hwc_sf_key
                        else None
                    ),
                    holiday_start=_topic_config(
                        prefix,
                        device_id,
                        hwc_h_start_key or "HwcHolidayStartPeriod",
                        hwc_h_start_field or "value.value",
                    ),
                    holiday_end=_topic_config(
                        prefix,
                        device_id,
                        hwc_h_end_key or "HwcHolidayEndPeriod",
                        hwc_h_end_field or "value.value",
                    ),
                    holiday_start_time=(
                        _topic_config(
                            prefix, device_id, hwc_h_st_key, hwc_h_st_field, writable=False
                        )
                        if hwc_h_st_key
                        else None
                    ),
                    holiday_end_time=(
                        _topic_config(
                            prefix, device_id, hwc_h_et_key, hwc_h_et_field, writable=False
                        )
                        if hwc_h_et_key
                        else None
                    ),
                )
            )

        # --- Zone-based heating: Z{n}OpMode + live Z{n}RoomTemp value required ---
        for zone in range(1, max_zones + 1):
            op_key = _resolve_key(msgs, "zone_op_mode", n=zone)
            room_key = _resolve_key(msgs, "zone_room_temp", n=zone)
            if not op_key or not room_key:
                continue
            room_field = _infer_field(msgs.get(room_key))
            if _get(msgs.get(room_key), room_field) is None:
                continue

            ct_key = _resolve_key(msgs, "zone_circuit_type", n=zone)
            if ct_key:
                ct_field = _infer_field(msgs[ct_key])
                if _get(msgs[ct_key], ct_field) == "inactive":
                    continue

            zrm_key = _resolve_key(msgs, "zone_room_zone_mapping", n=zone)
            if zrm_key:
                zrm_field = _infer_field(msgs[zrm_key])
                if _get(msgs[zrm_key], zrm_field) == "none":
                    continue

            hvac_modes = ["auto", "heat", "cool", "off"]

            day_key = _resolve_key(msgs, "zone_day_temp", n=zone)
            cooling_key = _resolve_key(msgs, "zone_cooling_temp", n=zone)
            night_key = _resolve_key(msgs, "zone_night_temp", n=zone)

            current_temp = (
                _topic_config(prefix, device_id, room_key, room_field, writable=False)
                if room_key
                else None
            )

            if day_key and cooling_key:
                t_target = None
                t_high = _topic_config(
                    prefix, device_id, cooling_key, _infer_field(msgs[cooling_key])
                )
                t_low = _topic_config(prefix, device_id, day_key, _infer_field(msgs[day_key]))
            elif day_key and night_key:
                t_target = None
                t_high = _topic_config(prefix, device_id, day_key, _infer_field(msgs[day_key]))
                t_low = _topic_config(prefix, device_id, night_key, _infer_field(msgs[night_key]))
            elif day_key:
                t_target = _topic_config(prefix, device_id, day_key, _infer_field(msgs[day_key]))
                t_high = None
                t_low = None
            else:
                t_target = None
                t_high = None
                t_low = None

            # Holiday & quick-veto topics: resolve first, fall back to canonical name.
            # Always created so write topics are available even before data arrives.
            h_start_key = _resolve_key(msgs, "zone_holiday_start", n=zone)
            h_start_field = _infer_field(msgs[h_start_key]) if h_start_key else "value.value"
            holiday_start = _topic_config(
                prefix,
                device_id,
                h_start_key or f"Z{zone}HolidayStartPeriod",
                h_start_field,
            )
            h_end_key = _resolve_key(msgs, "zone_holiday_end", n=zone)
            h_end_field = _infer_field(msgs[h_end_key]) if h_end_key else "value.value"
            holiday_end = _topic_config(
                prefix,
                device_id,
                h_end_key or f"Z{zone}HolidayEndPeriod",
                h_end_field,
            )
            h_start_time_key, h_start_time_field = _find_nested(
                msgs, "zone_holiday_start_time", n=zone
            )
            holiday_start_time = (
                _topic_config(
                    prefix, device_id, h_start_time_key, h_start_time_field, writable=False
                )
                if h_start_time_key
                else None
            )
            h_end_time_key, h_end_time_field = _find_nested(msgs, "zone_holiday_end_time", n=zone)
            holiday_end_time = (
                _topic_config(prefix, device_id, h_end_time_key, h_end_time_field, writable=False)
                if h_end_time_key
                else None
            )

            qv_temp_key = _resolve_key(msgs, "zone_quick_veto_temp", n=zone)
            qv_temp_field = _infer_field(msgs[qv_temp_key]) if qv_temp_key else "value.value"
            quick_veto_temp = _topic_config(
                prefix,
                device_id,
                qv_temp_key or f"Z{zone}QuickVetoTemp",
                qv_temp_field,
            )
            qv_dur_key = _resolve_key(msgs, "zone_quick_veto_duration", n=zone)
            qv_dur_field = _infer_field(msgs[qv_dur_key]) if qv_dur_key else "value.value"
            quick_veto_duration = _topic_config(
                prefix,
                device_id,
                qv_dur_key or f"Z{zone}QuickVetoDuration",
                qv_dur_field,
            )
            qv_ed_key = _resolve_key(msgs, "zone_quick_veto_end_date", n=zone)
            qv_ed_field = _infer_field(msgs[qv_ed_key]) if qv_ed_key else "value.value"
            quick_veto_end_date = _topic_config(
                prefix,
                device_id,
                qv_ed_key or f"Z{zone}QuickVetoEndDate",
                qv_ed_field,
            )
            qv_et_key = _resolve_key(msgs, "zone_quick_veto_end_time", n=zone)
            qv_et_field = _infer_field(msgs[qv_et_key]) if qv_et_key else "value.value"
            quick_veto_end_time = _topic_config(
                prefix,
                device_id,
                qv_et_key or f"Z{zone}QuickVetoEndTime",
                qv_et_field,
            )

            entities.append(
                DiscoveredClimate(
                    device_id=device_id,
                    key=f"{device_id}_zone{zone}",
                    name=f"{display_name} Zone {zone}",
                    mode=_topic_config(prefix, device_id, op_key, _infer_field(msgs[op_key])),
                    hvac_modes=hvac_modes,
                    current_temperature=current_temp,
                    target_temperature=t_target,
                    target_temperature_high=t_high,
                    target_temperature_low=t_low,
                    holiday_start=holiday_start,
                    holiday_end=holiday_end,
                    holiday_start_time=holiday_start_time,
                    holiday_end_time=holiday_end_time,
                    quick_veto_temp=quick_veto_temp,
                    quick_veto_duration=quick_veto_duration,
                    quick_veto_end_date=quick_veto_end_date,
                    quick_veto_end_time=quick_veto_end_time,
                )
            )

        # --- Sensors (pressure, energy, power, COP) ---
        for pattern in _SENSOR_CONFIGS:
            found_key, found_field = _find_topic(msgs, list(pattern.topic_keys))
            if found_key is None:
                continue

            key_suffix = pattern.key or pattern.topic_keys[0].lower()
            entities.append(
                DiscoveredSensor(
                    device_id=device_id,
                    key=f"{device_id}_{key_suffix}",
                    name=f"{display_name} {pattern.name}",
                    topic=_topic_config(prefix, device_id, found_key, found_field, writable=False),
                    device_class=pattern.device_class,
                    state_class=pattern.state_class,
                    unit=pattern.unit,
                    unique_id_prefix=pattern.unique_id_prefix,
                )
            )

    return entities
