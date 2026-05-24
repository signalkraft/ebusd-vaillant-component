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
    quick_veto_temp: TopicConfig | None = None
    quick_veto_duration: TopicConfig | None = None
    quick_veto_end_date: TopicConfig | None = None
    quick_veto_end_time: TopicConfig | None = None
    min_temp: float = 5.0
    max_temp: float = 30.0
    temp_step: float = 0.5


@dataclass
class DiscoveredPressureSensor:
    device_id: str
    key: str
    name: str
    topic: TopicConfig


@dataclass
class DiscoveredWaterHeater:
    device_id: str
    key: str  # stable identifier for unique_id (device_id + hwc), never changes
    name: str
    mode: TopicConfig
    target_temperature: TopicConfig
    current_temperature: TopicConfig | None = None
    operation_modes: list[str] = field(default_factory=lambda: ["auto", "day", "off"])
    min_temp: float = 40.0
    max_temp: float = 80.0
    temp_step: float = 1.0


def _get(payload: Any, dot_path: str) -> Any:
    """Extract a value from a nested dict using dot-notation path."""
    obj = payload
    for key in dot_path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _infer_field(payload: Any) -> str:
    """Derive dot-path from payload structure.

    Format 1 (scalar wrapper):
        {"value": {"value": X}}  →  "value.value"

    Format 2 (named sub-fields):
        {"fieldname": {"value": X}}  →  "fieldname.value"
    """
    if not isinstance(payload, dict):
        return "value.value"
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
    "pressure": ["WaterPressure", "DisplaySystemPressure"],
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
}


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


def _find_nested(
    msgs: dict[str, Any], role: str, **fmt_kwargs: Any
) -> tuple[str | None, str | None]:
    """Resolve a role to a (msg_key, field_path) pair, searching inside
    multi-field messages when no top-level key matches.

    Tries top-level key match first via _resolve_key.  If that fails,
    iterates through all multi-field messages and checks their sub-keys.
    Returns (None, None) when nothing matches.
    """
    top_key = _resolve_key(msgs, role, **fmt_kwargs)
    if top_key is not None:
        return top_key, _infer_field(msgs[top_key])

    patterns = _ROLE_PATTERNS[role]
    for msg_name, payload in msgs.items():
        if not isinstance(payload, dict):
            continue
        for pat in patterns:
            sub_key_lookup = pat.format(**fmt_kwargs)
            if sub_key_lookup in payload:
                return msg_name, f"{sub_key_lookup}.value"
            low_payload = {k.lower(): k for k in payload}
            if sub_key_lookup.lower() in low_payload:
                actual_key = low_payload[sub_key_lookup.lower()]
                return msg_name, f"{actual_key}.value"
    return None, None


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
) -> list[DiscoveredClimate | DiscoveredWaterHeater | DiscoveredPressureSensor]:
    """Build a list of discovered entities from per-device message dicts."""
    entities: list[DiscoveredClimate | DiscoveredWaterHeater | DiscoveredPressureSensor] = []

    for device_id, msgs in by_device.items():
        # --- Water pressure sensor ---
        pressure_key, pressure_field = _find_nested(msgs, "pressure")
        if pressure_key:
            entities.append(
                DiscoveredPressureSensor(
                    device_id=device_id,
                    key=f"{device_id}_pressure",
                    name=f"{display_name} Water Pressure",
                    topic=_topic_config(
                        prefix, device_id, pressure_key, pressure_field, writable=False
                    ),
                )
            )

        # --- Water heater: HwcOpMode + HwcTempDesired required ---
        hwc_op_key = _resolve_key(msgs, "hwc_op_mode")
        hwc_target_key = _resolve_key(msgs, "hwc_target_temp")
        if hwc_op_key and hwc_target_key:
            hwc_current_key = _resolve_key(msgs, "hwc_current_temp") or "HwcStorageTemp"
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
                )
            )

        # --- Zone-based heating: Z{n}OpMode + live Z{n}RoomTemp value required ---
        for zone in range(1, 5):
            op_key = _resolve_key(msgs, "zone_op_mode", n=zone)
            room_key = _resolve_key(msgs, "zone_room_temp", n=zone)
            if not op_key or not room_key:
                continue
            room_field = _infer_field(msgs.get(room_key))
            if _get(msgs.get(room_key), room_field) is None:
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
            h_start_key = (
                _resolve_key(msgs, "zone_holiday_start", n=zone) or f"Z{zone}HolidayStartPeriod"
            )
            holiday_start = _topic_config(prefix, device_id, h_start_key, "value.value")
            h_end_key = _resolve_key(msgs, "zone_holiday_end", n=zone) or f"Z{zone}HolidayEndPeriod"
            holiday_end = _topic_config(prefix, device_id, h_end_key, "value.value")

            qv_temp_key = (
                _resolve_key(msgs, "zone_quick_veto_temp", n=zone) or f"Z{zone}QuickVetoTemp"
            )
            quick_veto_temp = _topic_config(prefix, device_id, qv_temp_key, "value.value")
            qv_dur_key = (
                _resolve_key(msgs, "zone_quick_veto_duration", n=zone)
                or f"Z{zone}QuickVetoDuration"
            )
            quick_veto_duration = _topic_config(prefix, device_id, qv_dur_key, "value.value")
            qv_ed_key = (
                _resolve_key(msgs, "zone_quick_veto_end_date", n=zone) or f"Z{zone}QuickVetoEndDate"
            )
            quick_veto_end_date = _topic_config(prefix, device_id, qv_ed_key, "value.value")
            qv_et_key = (
                _resolve_key(msgs, "zone_quick_veto_end_time", n=zone) or f"Z{zone}QuickVetoEndTime"
            )
            quick_veto_end_time = _topic_config(prefix, device_id, qv_et_key, "value.value")

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
                    quick_veto_temp=quick_veto_temp,
                    quick_veto_duration=quick_veto_duration,
                    quick_veto_end_date=quick_veto_end_date,
                    quick_veto_end_time=quick_veto_end_time,
                )
            )

    return entities
