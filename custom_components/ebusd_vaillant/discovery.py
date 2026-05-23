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
        if "WaterPressure" in msgs:
            entities.append(
                DiscoveredPressureSensor(
                    device_id=device_id,
                    key=f"{device_id}_pressure",
                    name=f"{display_name} Water Pressure",
                    topic=_topic_config(
                        prefix, device_id, "WaterPressure", "value.value", writable=False
                    ),
                )
            )

        # --- Water heater: HwcOpMode + HwcTempDesired required ---
        if "HwcOpMode" in msgs and "HwcTempDesired" in msgs:
            current_temp_msg = next(
                (
                    c
                    for c in ("HwcStorageTemp", "HwcStorageTempBottom", "HwcStorageTempTop")
                    if c in msgs
                ),
                "HwcStorageTemp",
            )
            entities.append(
                DiscoveredWaterHeater(
                    device_id=device_id,
                    key=f"{device_id}_hwc",
                    name=f"{display_name} Hot Water",
                    mode=_topic_config(prefix, device_id, "HwcOpMode", "value.value"),
                    target_temperature=_topic_config(
                        prefix, device_id, "HwcTempDesired", "value.value"
                    ),
                    current_temperature=_topic_config(
                        prefix, device_id, current_temp_msg, "value.value", writable=False
                    ),
                )
            )
        # --- Zone-based heating: Z{n}OpMode + live Z{n}RoomTemp value required ---
        for zone in range(1, 5):
            op_key = f"Z{zone}OpMode"
            room_key = f"Z{zone}RoomTemp"
            if op_key not in msgs:
                continue
            if _get(msgs.get(room_key), "value.value") is None:
                continue

            hvac_modes = ["auto", "heat", "cool", "off"]

            day_key = f"Z{zone}DayTemp"
            cooling_key = f"Z{zone}CoolingTemp"
            night_key = f"Z{zone}NightTemp"

            current_temp = (
                _topic_config(prefix, device_id, room_key, "value.value", writable=False)
                if room_key in msgs
                else None
            )

            has_day = day_key in msgs
            has_cooling = cooling_key in msgs
            has_night = night_key in msgs

            if has_day and has_cooling:
                t_target = None
                t_high = _topic_config(prefix, device_id, cooling_key, "value.value")
                t_low = _topic_config(prefix, device_id, day_key, "value.value")
            elif has_day and has_night:
                t_target = None
                t_high = _topic_config(prefix, device_id, day_key, "value.value")
                t_low = _topic_config(prefix, device_id, night_key, "value.value")
            elif has_day:
                t_target = _topic_config(prefix, device_id, day_key, "value.value")
                t_high = None
                t_low = None
            else:
                t_target = None
                t_high = None
                t_low = None

            start_key = f"Z{zone}HolidayStartPeriod"
            end_key = f"Z{zone}HolidayEndPeriod"
            holiday_start = _topic_config(prefix, device_id, start_key, "value.value")
            holiday_end = _topic_config(prefix, device_id, end_key, "value.value")

            quick_veto_temp = _topic_config(
                prefix, device_id, f"Z{zone}QuickVetoTemp", "value.value"
            )
            quick_veto_duration = _topic_config(
                prefix, device_id, f"Z{zone}QuickVetoDuration", "value.value"
            )
            quick_veto_end_date = _topic_config(
                prefix, device_id, f"Z{zone}QuickVetoEndDate", "value.value"
            )
            quick_veto_end_time = _topic_config(
                prefix, device_id, f"Z{zone}QuickVetoEndTime", "value.value"
            )

            entities.append(
                DiscoveredClimate(
                    device_id=device_id,
                    key=f"{device_id}_zone{zone}",
                    name=f"{display_name} Zone {zone}",
                    mode=_topic_config(prefix, device_id, op_key, "value.value"),
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
