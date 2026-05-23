"""Unit tests for entity discovery logic (_analyze)."""

import pytest

from custom_components.ebusd_vaillant.discovery import (
    DiscoveredClimate,
    DiscoveredPressureSensor,
    DiscoveredWaterHeater,
    _analyze,
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
        assert isinstance(
            entity, DiscoveredClimate | DiscoveredWaterHeater | DiscoveredPressureSensor
        )


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
    """Only Z1 has Z1RoomTemp in vrc720.yml, so only one zone should be discovered."""
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
