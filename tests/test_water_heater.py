"""Integration tests for EbusdWaterHeaterEntity using the HA test framework."""

import json

import pytest
from homeassistant.const import ATTR_TEMPERATURE
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.ebusd_vaillant.const import DOMAIN

MQTT_PREFIX = "ebusd"
DEVICE = "ctlv2"

VRC720_MSGS: dict[str, dict] = {
    f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode": {"value": {"value": "auto"}},
    f"{MQTT_PREFIX}/{DEVICE}/HwcTempDesired": {"value": {"value": 55}},
    f"{MQTT_PREFIX}/{DEVICE}/HwcStorageTemp": {"value": {"value": 53}},
}


@pytest.fixture
async def setup_entry(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"mqtt_prefix": MQTT_PREFIX})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _fire(hass, msgs: dict = VRC720_MSGS) -> None:
    """Fire MQTT messages twice: first pass triggers discovery, second updates entity state."""
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()


def _water_heater(hass):
    states = hass.states.async_all("water_heater")
    assert states, "No water_heater entities found"
    return states[0]


def _published(mqtt_client_mock) -> dict[str, str]:
    result: dict[str, str] = {}
    for c in mqtt_client_mock.publish.call_args_list:
        topic = c.args[0]
        payload = c.args[1] if len(c.args) > 1 else ""
        result[topic] = payload.decode() if isinstance(payload, bytes) else str(payload)
    return result


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


async def test_water_heater_entity_discovered(hass, setup_entry):
    await _fire(hass)
    assert len(hass.states.async_all("water_heater")) == 1


async def test_no_water_heater_without_temp_desired(hass, setup_entry):
    await _fire(hass, {k: v for k, v in VRC720_MSGS.items() if "TempDesired" not in k})
    assert len(hass.states.async_all("water_heater")) == 0


# ---------------------------------------------------------------------------
# State from incoming MQTT
# ---------------------------------------------------------------------------


async def test_operation_mode_auto(hass, setup_entry):
    await _fire(hass)
    assert _water_heater(hass).state == "auto"


async def test_operation_mode_day(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode", json.dumps({"value": {"value": "day"}})
    )
    await hass.async_block_till_done()
    assert _water_heater(hass).state == "day"


async def test_operation_mode_off(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode", json.dumps({"value": {"value": "off"}})
    )
    await hass.async_block_till_done()
    assert _water_heater(hass).state == "off"


async def test_target_temperature(hass, setup_entry):
    await _fire(hass)
    assert _water_heater(hass).attributes["temperature"] == 55.0


async def test_current_temperature(hass, setup_entry):
    await _fire(hass)
    assert _water_heater(hass).attributes["current_temperature"] == 53.0


async def test_target_temperature_update(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/HwcTempDesired", json.dumps({"value": {"value": 60}})
    )
    await hass.async_block_till_done()
    assert _water_heater(hass).attributes["temperature"] == 60.0


async def test_current_temperature_update(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/HwcStorageTemp", json.dumps({"value": {"value": 58}})
    )
    await hass.async_block_till_done()
    assert _water_heater(hass).attributes["current_temperature"] == 58.0


# ---------------------------------------------------------------------------
# Commands → MQTT publish
# ---------------------------------------------------------------------------


async def test_set_temperature_publishes(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _water_heater(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {"entity_id": entity_id, ATTR_TEMPERATURE: 60.0},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcTempDesired/set") == "60.0"


async def test_set_operation_mode_off_publishes(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _water_heater(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "water_heater",
        "set_operation_mode",
        {"entity_id": entity_id, "operation_mode": "off"},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode/set") == "off"


async def test_turn_on_publishes_auto(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _water_heater(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "water_heater", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode/set") == "auto"


async def test_turn_off_publishes_off(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _water_heater(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "water_heater", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode/set") == "off"


async def test_set_operation_mode_day_publishes(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _water_heater(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "water_heater",
        "set_operation_mode",
        {"entity_id": entity_id, "operation_mode": "day"},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode/set") == "day"


async def test_set_operation_mode_auto_publishes(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _water_heater(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "water_heater",
        "set_operation_mode",
        {"entity_id": entity_id, "operation_mode": "auto"},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode/set") == "auto"


async def test_storage_temp_bottom_fallback(hass, mqtt_mock):
    """HwcStorageTempBottom is used when HwcStorageTemp is absent."""
    entry = MockConfigEntry(domain=DOMAIN, data={"mqtt_prefix": MQTT_PREFIX})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    msgs = {
        # Arrive before HwcOpMode so _analyze picks HwcStorageTempBottom on first discovery.
        f"{MQTT_PREFIX}/{DEVICE}/HwcStorageTempBottom": {"value": {"value": 48}},
        f"{MQTT_PREFIX}/{DEVICE}/HwcTempDesired": {"value": {"value": 55}},
        f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode": {"value": {"value": "auto"}},
    }
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()

    assert _water_heater(hass).attributes["current_temperature"] == 48.0

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


HWC_HOLIDAY_MSGS: dict[str, dict] = {
    f"{MQTT_PREFIX}/{DEVICE}/HwcOpMode": {"value": {"value": "auto"}},
    f"{MQTT_PREFIX}/{DEVICE}/HwcTempDesired": {"value": {"value": 55}},
    f"{MQTT_PREFIX}/{DEVICE}/HwcHolidayStartPeriod": {"value": {"value": "01.01.2020"}},
    f"{MQTT_PREFIX}/{DEVICE}/HwcHolidayEndPeriod": {"value": {"value": "01.01.2099"}},
}


@pytest.fixture
async def setup_holiday_entry(hass, mqtt_mock):
    entry = MockConfigEntry(domain=DOMAIN, data={"mqtt_prefix": MQTT_PREFIX})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _fire_holiday(hass, msgs: dict = HWC_HOLIDAY_MSGS) -> None:
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()


async def test_away_mode_always_available(hass, setup_entry):
    """Away mode feature is always available."""
    await _fire(hass)
    features = _water_heater(hass).attributes.get("supported_features", 0)
    assert features & 4  # AWAY_MODE = 4


async def test_away_mode_on_when_within_holiday(hass, setup_holiday_entry):
    """is_away_mode_on is True when today falls within holiday range."""
    await _fire_holiday(hass)
    wh = _water_heater(hass)
    assert wh.attributes.get("away_mode") == "on"


async def test_away_mode_off_when_reset_sentinel(hass, setup_holiday_entry):
    """is_away_mode_on is False when holiday dates are the reset sentinel (past)."""
    msgs = {k: v for k, v in HWC_HOLIDAY_MSGS.items()}
    msgs.update(
        {
            f"{MQTT_PREFIX}/{DEVICE}/HwcHolidayStartPeriod": {"value": {"value": "01.01.2015"}},
            f"{MQTT_PREFIX}/{DEVICE}/HwcHolidayEndPeriod": {"value": {"value": "01.01.2015"}},
        }
    )
    await _fire_holiday(hass, msgs)
    wh = _water_heater(hass)
    assert wh.attributes.get("away_mode") == "off"


async def test_set_away_mode_on_publishes_holiday_dates(
    hass, setup_holiday_entry, mqtt_client_mock, freezer
):
    """Enabling away mode publishes today+7 as holiday dates."""
    freezer.move_to("2026-06-01")
    await _fire_holiday(hass)
    entity_id = _water_heater(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "water_heater",
        "set_away_mode",
        {"entity_id": entity_id, "away_mode": "on"},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcHolidayStartPeriod/set") == "01.06.2026"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcHolidayEndPeriod/set") == "08.06.2026"


async def test_set_away_mode_off_publishes_reset(hass, setup_holiday_entry, mqtt_client_mock):
    """Disabling away mode publishes reset sentinels."""
    await _fire_holiday(hass)
    entity_id = _water_heater(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "water_heater",
        "set_away_mode",
        {"entity_id": entity_id, "away_mode": "off"},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcHolidayStartPeriod/set") == "01.01.2015"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/HwcHolidayEndPeriod/set") == "01.01.2015"
