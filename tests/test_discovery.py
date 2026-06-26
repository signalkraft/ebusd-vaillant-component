"""Unit tests for entity discovery logic (_analyze)."""

import pytest

from custom_components.ebusd_vaillant.discovery import (
    DiscoveredClimate,
    DiscoveredSensor,
    DiscoveredWaterHeater,
    _analyze,
    _find_topic,
    _infer_field,
    _resolve_key,
)
from tests.conftest import DATA_DIR, load_data_file

# ---------------------------------------------------------------------------
# Generic tests  -  run for every YAML file in tests/data/
# ---------------------------------------------------------------------------


def test_at_least_one_entity_discovered(data_file):
    prefix, by_device = data_file
    entities = _analyze(by_device, prefix)
    assert len(entities) > 0


def test_entity_types_are_valid(data_file):
    prefix, by_device = data_file
    entities = _analyze(by_device, prefix)
    for entity in entities:
        assert isinstance(entity, DiscoveredClimate | DiscoveredWaterHeater | DiscoveredSensor)


def test_entities_have_name_and_device_id(data_file):
    prefix, by_device = data_file
    entities = _analyze(by_device, prefix)
    for entity in entities:
        assert entity.name
        assert entity.device_id
        assert entity.key


def test_climate_hvac_modes_non_empty(data_file):
    prefix, by_device = data_file
    for entity in _analyze(by_device, prefix):
        if isinstance(entity, DiscoveredClimate):
            assert entity.hvac_modes


def test_climate_mode_topics_set(data_file):
    prefix, by_device = data_file
    for entity in _analyze(by_device, prefix):
        if isinstance(entity, DiscoveredClimate):
            assert entity.mode.read_topic
            assert entity.mode.write_topic


def test_water_heater_required_topics_set(data_file):
    prefix, by_device = data_file
    for entity in _analyze(by_device, prefix):
        if isinstance(entity, DiscoveredWaterHeater):
            assert entity.mode.read_topic
            assert entity.target_temperature.read_topic


# ---------------------------------------------------------------------------
# _infer_field
# ---------------------------------------------------------------------------


def test_infer_field_format1_scalar():
    """Format 1: {"value": {"value": X}} → "value.value"."""
    assert _infer_field({"value": {"value": "auto"}}) == "value.value"
    assert _infer_field({"value": {"value": 20.0}}) == "value.value"
    assert _infer_field({"value": {"value": None}}) == "value.value"


def test_infer_field_format2_named():
    """Format 2: {"fieldname": {"value": X}} → "fieldname.value"."""
    assert _infer_field({"opmode2": {"value": "time controlled"}}) == "opmode2.value"
    assert _infer_field({"tempv": {"value": 50}}) == "tempv.value"
    assert _infer_field({"pressv": {"value": 1.7}}) == "pressv.value"


def test_infer_field_non_dict():
    assert _infer_field(None) == "value.value"
    assert _infer_field("scalar") == ""


# ---------------------------------------------------------------------------
# _resolve_key
# ---------------------------------------------------------------------------


def test_resolve_key_exact_match():
    msgs = {"Z1OpMode": {}, "HwcOpMode": {}}
    assert _resolve_key(msgs, "zone_op_mode", n=1) == "Z1OpMode"
    assert _resolve_key(msgs, "hwc_op_mode") == "HwcOpMode"


def test_resolve_key_case_insensitive():
    msgs = {"z1RoomTemp": {"tempv": {"value": 25.35}}}
    assert _resolve_key(msgs, "zone_room_temp", n=1) == "z1RoomTemp"


def test_resolve_key_alias_opmode_heating():
    msgs = {"z1OpModeHeating": {"opmode2": {"value": "off"}}}
    assert _resolve_key(msgs, "zone_op_mode", n=1) == "z1OpModeHeating"


def test_resolve_key_alias_opmode_cooling():
    msgs = {"z1OpModeCooling": {"opmode2": {"value": "off"}}}
    assert _resolve_key(msgs, "zone_op_mode", n=1) == "z1OpModeCooling"


def test_resolve_key_alias_night_temp():
    msgs = {"z1SetBackTemp": {"tempv": {"value": 21}}}
    assert _resolve_key(msgs, "zone_night_temp", n=1) == "z1SetBackTemp"


def test_resolve_key_alias_heating_day_temp():
    msgs = {"z1HeatingRoomTempDesiredManualControlled": {"tempv": {"value": 20}}}
    assert _resolve_key(msgs, "zone_day_temp", n=1) == "z1HeatingRoomTempDesiredManualControlled"


def test_resolve_key_missing_role():
    msgs = {"OtherThing": {"value": {"value": 1}}}
    assert _resolve_key(msgs, "hwc_op_mode") is None
    assert _resolve_key(msgs, "zone_op_mode", n=2) is None


def test_resolve_key_hwc_current_temp_preference():
    """HwcStorageTemp is preferred over HwcStorageTempBottom/Top."""
    msgs = {"HwcStorageTempBottom": {}, "HwcStorageTemp": {}}
    assert _resolve_key(msgs, "hwc_current_temp") == "HwcStorageTemp"


def test_resolve_key_hwc_current_temp_fallback():
    msgs = {"HwcStorageTempTop": {}}
    assert _resolve_key(msgs, "hwc_current_temp") == "HwcStorageTempTop"


def test_resolve_key_hwc_opmode_uppercase_variant():
    msgs = {"HwcOPMode": {"hwcmode7": {"value": "auto"}}}
    assert _resolve_key(msgs, "hwc_op_mode") == "HwcOPMode"


def test_resolve_key_hwc_current_temp_displayed():
    msgs = {"DisplayedHwcStorageTemp": {"temp1": {"value": 50}}}
    assert _resolve_key(msgs, "hwc_current_temp") == "DisplayedHwcStorageTemp"


def test_resolve_key_z_manual_temp_as_day_temp():
    """Z{n}ManualTemp is the ctlv2 equivalent of Z{n}DayTemp."""
    msgs = {"Z1ManualTemp": {"tempv": {"value": 21}}}
    assert _resolve_key(msgs, "zone_day_temp", n=1) == "Z1ManualTemp"


def test_resolve_key_z_cooling_temp_desired():
    """Z{n}CoolingTempDesired is the ctlv2 cooling target."""
    msgs = {"Z1CoolingTempDesired": {"tempv": {"value": 18}}}
    assert _resolve_key(msgs, "zone_cooling_temp", n=1) == "Z1CoolingTempDesired"


def test_resolve_key_z_cooling_manual_temp():
    """Z{n}CoolingManualTemp is the ctlv2 cooling manual setpoint."""
    msgs = {"Z1CoolingManualTemp": {"tempv": {"value": 22}}}
    assert _resolve_key(msgs, "zone_cooling_temp", n=1) == "Z1CoolingManualTemp"


# ---------------------------------------------------------------------------
# _find_topic
# ---------------------------------------------------------------------------

_PRESSURE_KEYS = ["WaterPressure", "DisplaySystemPressure"]


def test_find_topic_top_level_first_key():
    msgs = {"WaterPressure": {"pressv": {"value": 1.7}}}
    key, field = _find_topic(msgs, _PRESSURE_KEYS)
    assert key == "WaterPressure"
    assert field == "pressv.value"


def test_find_topic_top_level_second_key():
    msgs = {"DisplaySystemPressure": {"pressv": {"value": 1.5}}}
    key, field = _find_topic(msgs, _PRESSURE_KEYS)
    assert key == "DisplaySystemPressure"
    assert field == "pressv.value"


def test_find_topic_nested_fallback():
    msgs = {"State07": {"power": {"value": 0}, "DisplaySystemPressure": {"value": 1.7}}}
    key, field = _find_topic(msgs, _PRESSURE_KEYS)
    assert key == "State07"
    assert field == "DisplaySystemPressure.value"


def test_find_topic_no_match():
    msgs = {"State07": {"power": {"value": 0}, "energy": {"value": 0}}}
    key, field = _find_topic(msgs, _PRESSURE_KEYS)
    assert key is None
    assert field is None


# ---------------------------------------------------------------------------
# _find_nested
# ---------------------------------------------------------------------------


def test_find_nested_via_state07_discovers_pressure_sensor():
    """A pressure sensor entity should be discovered from nested DisplaySystemPressure."""
    by_device = {
        "hmu": {
            "State07": {
                "power": {"value": 0},
                "DisplaySystemPressure": {"value": 1.7},
            },
        }
    }
    entities = _analyze(by_device, "ebusd")
    sensors = [
        e for e in entities if isinstance(e, DiscoveredSensor) and e.device_class == "pressure"
    ]
    assert len(sensors) == 1
    ps = sensors[0]
    assert ps.device_id == "hmu"
    assert ps.topic.read_topic == "ebusd/hmu/State07"
    assert ps.topic.field == "DisplaySystemPressure.value"


def test_sensor_pattern_second_key_used_when_first_absent():
    """When first candidate topic is absent, second candidate is used (top-level)."""
    by_device = {"hmu": {"DisplaySystemPressure": {"pressv": {"value": 1.5}}}}
    entities = _analyze(by_device, "ebusd")
    ps = next(
        e for e in entities if isinstance(e, DiscoveredSensor) and e.device_class == "pressure"
    )
    assert ps.topic.read_topic == "ebusd/hmu/DisplaySystemPressure"
    assert ps.topic.field == "pressv.value"


def test_find_nested_prefers_top_level():
    """Top-level WaterPressure takes priority over nested DisplaySystemPressure."""
    by_device = {
        "ctlv2": {
            "WaterPressure": {"pressv": {"value": 1.7}},
            "State07": {
                "DisplaySystemPressure": {"value": 1.5},
            },
        }
    }
    entities = _analyze(by_device, "ebusd")
    ps = next(
        e for e in entities if isinstance(e, DiscoveredSensor) and e.device_class == "pressure"
    )
    assert ps.topic.read_topic == "ebusd/ctlv2/WaterPressure"
    assert ps.topic.field == "pressv.value"


def test_rmalbrecht_discovers_pressure_from_state07():
    """Real-world scenario: pressure inside hmu.State07 is discovered."""
    prefix, by_device = load_data_file(DATA_DIR / "rmalbrecht.yml")
    entities = _analyze(by_device, prefix)
    sensors = [
        e for e in entities if isinstance(e, DiscoveredSensor) and e.device_class == "pressure"
    ]
    assert len(sensors) == 1
    ps = sensors[0]
    assert ps.device_id == "hmu"
    assert ps.topic.read_topic == "ebusd/hmu/State07"
    assert ps.topic.field == "DisplaySystemPressure.value"


# ---------------------------------------------------------------------------
# Format 2 (named-field payloads, lowercase/variant key names)
# ---------------------------------------------------------------------------


def test_format2_water_heater_discovered():
    """Named-field payloads should still discover a water heater."""
    by_device = {
        "dev": {
            "HwcOpMode": {"opmode2": {"value": "time controlled"}},
            "HwcTempDesired": {"tempv": {"value": 50}},
            "HwcStorageTemp": {"tempv": {"value": 67.75}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    wh = next(e for e in entities if isinstance(e, DiscoveredWaterHeater))
    assert wh.mode.read_topic == "ebusd/dev/HwcOpMode"
    assert wh.mode.field == "opmode2.value"
    assert wh.target_temperature.read_topic == "ebusd/dev/HwcTempDesired"
    assert wh.target_temperature.field == "tempv.value"
    assert wh.current_temperature is not None
    assert wh.current_temperature.read_topic == "ebusd/dev/HwcStorageTemp"
    assert wh.current_temperature.field == "tempv.value"


def test_format2_water_heater_no_storage_temp():
    """Water heater discovered with fallback current temp topic when no storage key exists."""
    by_device = {
        "dev": {
            "HwcOpMode": {"opmode2": {"value": "auto"}},
            "HwcTempDesired": {"tempv": {"value": 55}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    wh = next(e for e in entities if isinstance(e, DiscoveredWaterHeater))
    assert wh.current_temperature is not None
    # Falls back to "HwcStorageTemp" with "value.value" field path
    assert wh.current_temperature.read_topic == "ebusd/dev/HwcStorageTemp"
    assert wh.current_temperature.field == "value.value"


def test_format2_lowercase_z_climate_discovered():
    """Climate zone discovered with lowercase z prefix and aliased opmode key."""
    by_device = {
        "dev": {
            "z1OpModeHeating": {"opmode2": {"value": "auto"}},
            "z1RoomTemp": {"tempv": {"value": 21.5}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.name == "Vaillant Zone 1"
    assert z1.mode.read_topic == "ebusd/dev/z1OpModeHeating"
    assert z1.mode.field == "opmode2.value"
    assert z1.current_temperature.read_topic == "ebusd/dev/z1RoomTemp"
    assert z1.current_temperature.field == "tempv.value"


def test_format2_lowercase_z_with_targets():
    """Climate zone with lowercase z + HeatingRoomTempDesired + SetBackTemp targets."""
    by_device = {
        "dev": {
            "z1OpModeHeating": {"opmode2": {"value": "auto"}},
            "z1RoomTemp": {"tempv": {"value": 21.5}},
            "z1HeatingRoomTempDesiredManualControlled": {"tempv": {"value": 20}},
            "z1SetBackTemp": {"tempv": {"value": 21}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.target_temperature is None  # range mode
    assert z1.target_temperature_high is not None
    assert (
        z1.target_temperature_high.read_topic
        == "ebusd/dev/z1HeatingRoomTempDesiredManualControlled"
    )
    assert z1.target_temperature_low is not None
    assert z1.target_temperature_low.read_topic == "ebusd/dev/z1SetBackTemp"


# ---------------------------------------------------------------------------
# vrc720-specific tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vrc720():
    return load_data_file(DATA_DIR / "vrc720.yml")


def test_vrc720_discovers_one_water_heater(vrc720):
    prefix, by_device = vrc720
    water_heaters = [e for e in _analyze(by_device, prefix) if isinstance(e, DiscoveredWaterHeater)]
    assert len(water_heaters) == 1


def test_vrc720_discovers_one_climate_zone(vrc720):
    """Only Z1 has Z1RoomTemp + Hc1CircuitType != inactive in vrc720.yml, so only one zone."""
    prefix, by_device = vrc720
    climates = [e for e in _analyze(by_device, prefix) if isinstance(e, DiscoveredClimate)]
    assert len(climates) == 1
    assert climates[0].name == "Vaillant Zone 1"


def test_vrc720_water_heater_topics(vrc720):
    prefix, by_device = vrc720
    entities = _analyze(by_device, prefix)
    wh = next(e for e in entities if isinstance(e, DiscoveredWaterHeater))
    assert wh.device_id == "ctlv2"
    assert wh.key == "ctlv2_hwc"
    assert wh.name == "Vaillant Hot Water"
    assert wh.mode.read_topic == "ebusd/ctlv2/HwcOpMode"
    assert wh.mode.write_topic == "ebusd/ctlv2/HwcOpMode/set"
    assert wh.target_temperature.read_topic == "ebusd/ctlv2/HwcTempDesired"
    assert wh.target_temperature.write_topic == "ebusd/ctlv2/HwcTempDesired/set"
    assert wh.current_temperature is not None
    assert wh.current_temperature.read_topic == "ebusd/ctlv2/HwcStorageTemp"
    assert wh.current_temperature.write_topic is None


def test_vrc720_water_heater_sf_mode(vrc720):
    """HwcSFMode is present in the data → sf_mode is set on DiscoveredWaterHeater."""
    prefix, by_device = vrc720
    entities = _analyze(by_device, prefix)
    wh = next(e for e in entities if isinstance(e, DiscoveredWaterHeater))
    assert wh.sf_mode is not None
    assert wh.sf_mode.read_topic == "ebusd/ctlv2/HwcSFMode"
    assert wh.sf_mode.write_topic == "ebusd/ctlv2/HwcSFMode/set"


def test_vrc720_water_heater_temp_range(vrc720):
    prefix, by_device = vrc720
    entities = _analyze(by_device, prefix)
    wh = next(e for e in entities if isinstance(e, DiscoveredWaterHeater))
    assert wh.min_temp == 40.0
    assert wh.max_temp == 80.0
    assert wh.temp_step == 1.0


def test_vrc720_z1_uses_temperature_range(vrc720):
    """Z1 has both DayTemp and CoolingTemp → temperature range (high/low), not single target."""
    prefix, by_device = vrc720
    entities = _analyze(by_device, prefix)
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.target_temperature is None
    assert z1.target_temperature_high is not None
    assert z1.target_temperature_low is not None


def test_vrc720_z1_temperature_topics(vrc720):
    """Z1CoolingTemp → high, Z1DayTemp → low (heat/cool range branch)."""
    prefix, by_device = vrc720
    entities = _analyze(by_device, prefix)
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.target_temperature_high.read_topic == "ebusd/ctlv2/Z1CoolingTemp"
    assert z1.target_temperature_low.read_topic == "ebusd/ctlv2/Z1DayTemp"
    assert z1.current_temperature.read_topic == "ebusd/ctlv2/Z1RoomTemp"
    assert z1.current_temperature.write_topic is None


def test_vrc720_z1_hvac_modes(vrc720):
    prefix, by_device = vrc720
    entities = _analyze(by_device, prefix)
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert set(z1.hvac_modes) == {"auto", "heat", "cool", "off"}


def test_vrc720_z1_key_and_name(vrc720):
    prefix, by_device = vrc720
    entities = _analyze(by_device, prefix)
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.key == "ctlv2_zone1"
    assert z1.name == "Vaillant Zone 1"


def test_inactive_circuit_type_skips_zone():
    """Zone with Hc{n}CircuitType mctype=inactive is excluded even with room temp."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "Z2OpMode": {"value": {"value": "auto"}},
            "Z2RoomTemp": {"value": {"value": 22.0}},
            "Hc1CircuitType": {"mctype": {"value": "mixer"}},
            "Hc2CircuitType": {"mctype": {"value": "inactive"}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    climates = [e for e in entities if isinstance(e, DiscoveredClimate)]
    assert len(climates) == 1
    assert climates[0].key == "dev_zone1"


def test_room_zone_mapping_none_skips_zone():
    """Zone with Z{n}RoomZoneMapping=none is excluded even with room temp and OpMode."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "Z1RoomZoneMapping": {"value": {"value": "VRC700"}},
            "Z2OpMode": {"value": {"value": "auto"}},
            "Z2RoomTemp": {"value": {"value": 0.0}},
            "Z2RoomZoneMapping": {"value": {"value": "none"}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    climates = [e for e in entities if isinstance(e, DiscoveredClimate)]
    assert len(climates) == 1
    assert climates[0].key == "dev_zone1"


def test_custom_display_name():
    """display_name parameter replaces 'Vaillant' in all entity names."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "HwcOpMode": {"value": {"value": "auto"}},
            "HwcTempDesired": {"value": {"value": 55}},
        }
    }
    entities = _analyze(by_device, "ebusd", display_name="My Boiler")
    names = {e.name for e in entities}
    assert "My Boiler Zone 1" in names
    assert "My Boiler Hot Water" in names


def test_entity_name_has_no_device_id():
    """Device IDs must not appear in entity names."""
    by_device = {
        "ctlv2": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "HwcOpMode": {"value": {"value": "auto"}},
            "HwcTempDesired": {"value": {"value": 55}},
        }
    }
    entities = _analyze(by_device, "ebusd", display_name="Heat")
    for entity in entities:
        assert "ctlv2" not in entity.name


def test_no_zone_without_room_temp():
    """A zone is only discovered when a live Z{n}RoomTemp value is present."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            # No Z1RoomTemp
        }
    }
    entities = _analyze(by_device, "ebusd")
    climates = [e for e in entities if isinstance(e, DiscoveredClimate)]
    assert len(climates) == 0


def test_no_water_heater_without_temp_desired():
    by_device = {
        "dev": {
            "HwcOpMode": {"value": {"value": "auto"}},
            # Missing HwcTempDesired
        }
    }
    entities = _analyze(by_device, "ebusd")
    water_heaters = [e for e in entities if isinstance(e, DiscoveredWaterHeater)]
    assert len(water_heaters) == 0


def test_zone_day_only_uses_single_target():
    """When only DayTemp is present (no Cooling, no Night) → single target temperature."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "Z1DayTemp": {"value": {"value": 21.0}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.target_temperature is not None
    assert z1.target_temperature_high is None
    assert z1.target_temperature_low is None


def test_zone_day_and_night_uses_range():
    """DayTemp + NightTemp → temperature range (day=high, night=low)."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "Z1DayTemp": {"value": {"value": 21.0}},
            "Z1NightTemp": {"value": {"value": 18.0}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.target_temperature is None
    assert z1.target_temperature_high.read_topic == "ebusd/dev/Z1DayTemp"
    assert z1.target_temperature_low.read_topic == "ebusd/dev/Z1NightTemp"


def test_quick_veto_write_topics_always_present():
    """quick_veto_temp and quick_veto_duration are always created for any zone."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "Z1DayTemp": {"value": {"value": 21.0}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.quick_veto_temp is not None
    assert z1.quick_veto_temp.write_topic == "ebusd/dev/Z1QuickVetoTemp/set"
    assert z1.quick_veto_duration is not None
    assert z1.quick_veto_duration.write_topic == "ebusd/dev/Z1QuickVetoDuration/set"


def test_quick_veto_end_topics_always_present_and_writable():
    """quick_veto_end_date and quick_veto_end_time are always created with write topics."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "Z1DayTemp": {"value": {"value": 21.0}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    z1 = next(e for e in entities if isinstance(e, DiscoveredClimate))
    assert z1.quick_veto_end_date is not None
    assert z1.quick_veto_end_date.read_topic == "ebusd/dev/Z1QuickVetoEndDate"
    assert z1.quick_veto_end_date.write_topic == "ebusd/dev/Z1QuickVetoEndDate/set"
    assert z1.quick_veto_end_time is not None
    assert z1.quick_veto_end_time.read_topic == "ebusd/dev/Z1QuickVetoEndTime"
    assert z1.quick_veto_end_time.write_topic == "ebusd/dev/Z1QuickVetoEndTime/set"


def test_storage_temp_fallback_priority():
    """HwcStorageTemp is preferred; bottom/top variants used when that's absent."""
    by_device = {
        "dev": {
            "HwcOpMode": {"value": {"value": "auto"}},
            "HwcTempDesired": {"value": {"value": 55}},
            "HwcStorageTempBottom": {"value": {"value": 50}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    wh = next(e for e in entities if isinstance(e, DiscoveredWaterHeater))
    assert wh.current_temperature.read_topic == "ebusd/dev/HwcStorageTempBottom"


def test_mixed_zone_and_lowercase_zone_dont_conflict():
    """zone 1 uppercase and lowercase variants on different devices don't interfere."""
    by_device = {
        "dev_a": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
        },
        "dev_b": {
            "z1OpModeHeating": {"opmode2": {"value": "auto"}},
            "z1RoomTemp": {"tempv": {"value": 21.0}},
        },
    }
    entities = _analyze(by_device, "ebusd")
    climates = [e for e in entities if isinstance(e, DiscoveredClimate)]
    assert len(climates) == 2
    assert climates[0].device_id == "dev_a"
    assert climates[1].device_id == "dev_b"
    assert climates[0].mode.read_topic == "ebusd/dev_a/Z1OpMode"
    assert climates[1].mode.read_topic == "ebusd/dev_b/z1OpModeHeating"


# ---------------------------------------------------------------------------
# run_data_status  -  cross-device resolution
# ---------------------------------------------------------------------------


def test_run_data_status_resolved_from_hmu():
    """RunDataStatuscode on hmu is attached to climates on other devices (ctlv2)."""
    by_device = {
        "hmu": {
            "RunDataStatuscode": {"value": {"value": "cool_compressor_active"}},
        },
        "ctlv2": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 22.0}},
            "Z1DayTemp": {"value": {"value": 21}},
        },
    }
    entities = _analyze(by_device, "ebusd")
    climates = [e for e in entities if isinstance(e, DiscoveredClimate)]
    assert len(climates) == 1
    z1 = climates[0]
    assert z1.run_data_status is not None
    assert z1.run_data_status.read_topic == "ebusd/hmu/RunDataStatuscode"
    assert z1.run_data_status.write_topic is None  # read-only


def test_run_data_status_none_when_missing():
    """When no RunDataStatuscode exists anywhere, run_data_status stays None."""
    by_device = {
        "dev": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 20.0}},
            "Z1DayTemp": {"value": {"value": 21}},
        }
    }
    entities = _analyze(by_device, "ebusd")
    climates = [e for e in entities if isinstance(e, DiscoveredClimate)]
    assert len(climates) == 1
    assert climates[0].run_data_status is None


def test_run_data_status_resolved_from_statuscode_reech():
    """Reech-style systems use Statuscode (named-field format)."""
    by_device = {
        "hmu": {
            "Statuscode": {"scode": {"value": "Standby"}},
        },
        "bai00": {
            "Z1OpMode": {"value": {"value": "auto"}},
            "Z1RoomTemp": {"value": {"value": 21.0}},
        },
    }
    entities = _analyze(by_device, "ebusd")
    climates = [e for e in entities if isinstance(e, DiscoveredClimate)]
    assert len(climates) == 1
    z1 = climates[0]
    assert z1.run_data_status is not None
    assert z1.run_data_status.read_topic == "ebusd/hmu/Statuscode"
    assert z1.run_data_status.field == "scode.value"
