"""Integration tests for EbusdClimateEntity using the HA test framework."""

import json

import pytest
from homeassistant.components.climate import (
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_NONE,
    HVACAction,
    HVACMode,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.ebusd_vaillant.const import (
    CONF_AWAY_MODE_DURATION,
    CONF_QUICK_VETO_DURATION,
    DEFAULT_QUICK_VETO_TEMP,
    DOMAIN,
)

MQTT_PREFIX = "ebusd"
DEVICE = "ctlv2"
HMU_DEVICE = "hmu"

# Payloads matching vrc720.yml in coordinator wire format.
# Setpoint messages MUST arrive before Z1OpMode so that _analyze sees the full
# config when it first creates the entity (the coordinator won't re-notify
# listeners if only the config changes, not the entity name set).
VRC720_MSGS: dict[str, dict] = {
    f"{MQTT_PREFIX}/{DEVICE}/Z1DayTemp": {"value": {"value": 21}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1NightTemp": {"value": {"value": 18}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1CoolingTemp": {"value": {"value": 22}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1RoomTemp": {"value": {"value": 21.5}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod": {"value": {"value": "01.01.2015"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod": {"value": {"value": "01.01.2015"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode": {"value": {"value": "auto"}},
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
    # Entities are now subscribed  -  re-fire so their state handlers receive the values.
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()


def _climate(hass):
    states = hass.states.async_all("climate")
    assert states, "No climate entities found"
    return states[0]


def _published(mqtt_client_mock) -> dict[str, str]:
    """Map topic → decoded payload from paho publish calls."""
    result: dict[str, str] = {}
    for c in mqtt_client_mock.publish.call_args_list:
        topic = c.args[0]
        payload = c.args[1] if len(c.args) > 1 else ""
        result[topic] = payload.decode() if isinstance(payload, bytes) else str(payload)
    return result


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


async def test_climate_entity_discovered(hass, setup_entry):
    await _fire(hass)
    assert len(hass.states.async_all("climate")) == 1


async def test_no_climate_without_room_temp(hass, setup_entry):
    await _fire(hass, {k: v for k, v in VRC720_MSGS.items() if "RoomTemp" not in k})
    assert len(hass.states.async_all("climate")) == 0


# ---------------------------------------------------------------------------
# State from incoming MQTT
# ---------------------------------------------------------------------------


async def test_hvac_mode_auto(hass, setup_entry):
    await _fire(hass)
    assert _climate(hass).state == HVACMode.AUTO


async def test_hvac_mode_heat_from_day(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode", json.dumps({"value": {"value": "day"}})
    )
    await hass.async_block_till_done()
    assert _climate(hass).state == HVACMode.HEAT


async def test_hvac_mode_cool_from_night(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode", json.dumps({"value": {"value": "night"}})
    )
    await hass.async_block_till_done()
    assert _climate(hass).state == HVACMode.COOL


async def test_hvac_mode_off(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode", json.dumps({"value": {"value": "off"}})
    )
    await hass.async_block_till_done()
    assert _climate(hass).state == HVACMode.OFF


async def test_current_temperature(hass, setup_entry):
    await _fire(hass)
    assert _climate(hass).attributes["current_temperature"] == 21.5


async def test_temperature_range_high_low(hass, setup_entry):
    """Z1 with DayTemp + CoolingTemp → target_temp_high/low attributes."""
    await _fire(hass)
    attrs = _climate(hass).attributes
    assert attrs.get("target_temp_high") == 22.0  # CoolingTemp
    assert attrs.get("target_temp_low") == 21.0  # DayTemp


async def test_current_temp_update(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/Z1RoomTemp", json.dumps({"value": {"value": 23.5}})
    )
    await hass.async_block_till_done()
    assert _climate(hass).attributes["current_temperature"] == 23.5


# ---------------------------------------------------------------------------
# Commands → MQTT publish
# ---------------------------------------------------------------------------


async def test_set_hvac_mode_off_publishes(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode/set") == "off"


async def test_set_hvac_mode_heat_maps_to_day(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.HEAT},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode/set") == "day"


async def test_set_hvac_mode_cool_maps_to_night(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": HVACMode.COOL},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode/set") == "night"


async def test_set_temperature_range_publishes(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, "target_temp_high": 24.0, "target_temp_low": 20.0},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert f"{MQTT_PREFIX}/{DEVICE}/Z1CoolingTemp/set" in published
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoTemp/set") == "20.0"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoDuration/set") == "3"


async def test_turn_on_publishes_auto(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call("climate", "turn_on", {"entity_id": entity_id}, blocking=True)
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode/set") == "auto"


async def test_turn_off_publishes_off(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call("climate", "turn_off", {"entity_id": entity_id}, blocking=True)
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode/set") == "off"


# ---------------------------------------------------------------------------
# Presets  -  ECO and AWAY
# ---------------------------------------------------------------------------


async def test_preset_modes_include_none_boost_and_away(hass, setup_entry):
    await _fire(hass)
    attrs = _climate(hass).attributes
    assert PRESET_NONE in attrs["preset_modes"]
    assert PRESET_BOOST in attrs["preset_modes"]
    assert PRESET_AWAY in attrs["preset_modes"]


async def test_preset_eco_when_holiday_dates_in_past(hass, setup_entry):
    await _fire(hass)
    # VRC720_MSGS has holiday dates set to 01.01.2015 (past) → ECO
    assert _climate(hass).attributes.get("preset_mode") == PRESET_NONE


async def test_preset_away_when_now_within_holiday_period(hass, setup_entry):
    await _fire(hass)
    _climate(hass).entity_id
    # Send holiday dates that bracket today
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod",
        json.dumps({"value": {"value": "01.01.2020"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod",
        json.dumps({"value": {"value": "01.01.2099"}}),
    )
    await hass.async_block_till_done()
    assert _climate(hass).attributes.get("preset_mode") == PRESET_AWAY


async def test_set_preset_eco_from_away_resets_holiday_dates(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    # Put entity into AWAY state first
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod",
        json.dumps({"value": {"value": "01.01.2020"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod",
        json.dumps({"value": {"value": "01.01.2099"}}),
    )
    await hass.async_block_till_done()
    assert _climate(hass).attributes.get("preset_mode") == PRESET_AWAY

    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": PRESET_NONE},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod/set") == "01.01.2015"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod/set") == "01.01.2015"


async def test_set_preset_away_publishes_holiday_dates(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": PRESET_AWAY},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod/set" in published
    assert f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod/set" in published


async def test_preset_boost_when_quick_veto_end_in_future(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndDate",
        json.dumps({"value": {"value": "01.01.2099"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndTime",
        json.dumps({"value": {"value": "00:00:00"}}),
    )
    await hass.async_block_till_done()
    assert _climate(hass).attributes.get("preset_mode") == PRESET_BOOST


async def test_preset_none_when_quick_veto_end_in_past(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndDate",
        json.dumps({"value": {"value": "01.01.2015"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndTime",
        json.dumps({"value": {"value": "00:00:00"}}),
    )
    await hass.async_block_till_done()
    assert _climate(hass).attributes.get("preset_mode") == PRESET_NONE


async def test_set_preset_none_from_boost_cancels_quick_veto(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    # Put entity into BOOST state
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndDate",
        json.dumps({"value": {"value": "01.01.2099"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndTime",
        json.dumps({"value": {"value": "00:00:00"}}),
    )
    await hass.async_block_till_done()
    assert _climate(hass).attributes.get("preset_mode") == PRESET_BOOST

    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": PRESET_NONE},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoDuration/set") == "0"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndDate/set") == "01.01.2015"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndTime/set") == "00:00:00"


async def test_set_preset_boost_starts_quick_veto(hass, setup_entry, mqtt_client_mock):
    """Selecting the Boost preset starts a quick veto (issue #6).

    Regression: previously ``set_preset_mode(PRESET_BOOST)`` had no branch, so the
    advertised preset silently did nothing. The veto uses the configured quick-veto
    temperature (same write path/value as the Quick Veto switch), not the max temp.
    """
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": PRESET_BOOST},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    qv_temp = published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoTemp/set")
    assert qv_temp is not None, "Boost preset must start a quick veto (Z1QuickVetoTemp/set)"
    assert float(qv_temp) == DEFAULT_QUICK_VETO_TEMP
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoDuration/set") == "3"


async def test_set_preset_boost_noop_when_already_boosting(hass, setup_entry, mqtt_client_mock):
    """Re-selecting Boost while a quick veto is already active publishes nothing."""
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndDate",
        json.dumps({"value": {"value": "01.01.2099"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndTime",
        json.dumps({"value": {"value": "00:00:00"}}),
    )
    await hass.async_block_till_done()
    assert _climate(hass).attributes.get("preset_mode") == PRESET_BOOST

    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": PRESET_BOOST},
        blocking=True,
    )
    assert f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoTemp/set" not in _published(mqtt_client_mock)


async def test_set_preset_boost_from_away_clears_holiday_and_starts_veto(
    hass, setup_entry, mqtt_client_mock
):
    """AWAY -> BOOST both clears the holiday period and starts a quick veto."""
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod",
        json.dumps({"value": {"value": "01.01.2020"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod",
        json.dumps({"value": {"value": "01.01.2099"}}),
    )
    await hass.async_block_till_done()
    assert _climate(hass).attributes.get("preset_mode") == PRESET_AWAY

    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": PRESET_BOOST},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoTemp/set" in published  # boost started
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod/set") == "01.01.2015"  # away cleared


# ---------------------------------------------------------------------------
# Late-arrival temperature topics (race condition in production startup)
# ---------------------------------------------------------------------------

HOLIDAY_MSGS: dict[str, dict] = {
    f"{MQTT_PREFIX}/{DEVICE}/Z1DayTemp": {"value": {"value": 21}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1NightTemp": {"value": {"value": 18}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1CoolingTemp": {"value": {"value": 22}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1RoomTemp": {"value": {"value": 20.4125}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod": {"value": {"value": "22.05.2020"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod": {"value": {"value": "29.05.2099"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode": {"value": {"value": "auto"}},
}


async def test_holiday_preset_away(hass, setup_entry):
    """Holiday dates that span today → PRESET_AWAY."""
    await _fire(hass, HOLIDAY_MSGS)
    assert _climate(hass).attributes.get("preset_mode") == PRESET_AWAY


# ---------------------------------------------------------------------------
# Configuration options affect preset durations
# ---------------------------------------------------------------------------


@pytest.fixture
async def setup_custom_entry(hass, mqtt_mock):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"mqtt_prefix": MQTT_PREFIX},
        options={CONF_AWAY_MODE_DURATION: 14, CONF_QUICK_VETO_DURATION: 6},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_preset_away_default_duration(hass, setup_entry, mqtt_client_mock, freezer):
    """Default away_mode_duration=7 publishes today+7 as the end date."""
    freezer.move_to("2026-06-01")
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": PRESET_AWAY},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod/set") == "01.06.2026"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod/set") == "08.06.2026"


async def test_preset_away_custom_duration(hass, setup_custom_entry, mqtt_client_mock, freezer):
    """Custom away_mode_duration=14 publishes today+14 as the end date."""
    freezer.move_to("2026-06-01")
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_preset_mode",
        {"entity_id": entity_id, "preset_mode": PRESET_AWAY},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod/set") == "01.06.2026"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod/set") == "15.06.2026"


async def test_quick_veto_custom_duration(hass, setup_custom_entry, mqtt_client_mock):
    """Custom quick_veto_duration=6 publishes 6 hours instead of default 3."""
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, "target_temp_high": 22.0, "target_temp_low": 20.0},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoDuration/set") == "6"


async def test_set_low_temp_publishes_quick_veto(hass, setup_entry, mqtt_client_mock):
    """Setting the lower temperature publishes to the quick veto topic, not DayTemp."""
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, "target_temp_high": 22.0, "target_temp_low": 19.0},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoTemp/set") == "19.0"
    assert f"{MQTT_PREFIX}/{DEVICE}/Z1DayTemp/set" not in published


async def test_set_low_temp_publishes_veto_duration_of_3(hass, setup_entry, mqtt_client_mock):
    """The quick veto duration is always 3 hours."""
    await _fire(hass)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, "target_temp_high": 22.0, "target_temp_low": 20.5},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoDuration/set") == "3"


async def test_set_single_target_temp_publishes_quick_veto(hass, setup_entry, mqtt_client_mock):
    """With a single target temperature zone, setting it also triggers a quick veto."""
    single_temp_msgs = {
        f"{MQTT_PREFIX}/{DEVICE}/Z1DayTemp": {"value": {"value": 21}},
        f"{MQTT_PREFIX}/{DEVICE}/Z1RoomTemp": {"value": {"value": 20.0}},
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod": {"value": {"value": "01.01.2015"}},
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod": {"value": {"value": "01.01.2015"}},
        f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode": {"value": {"value": "auto"}},
    }
    await _fire(hass, single_temp_msgs)
    entity_id = _climate(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, "temperature": 22.0},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoTemp/set") == "22.0"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoDuration/set") == "3"


async def test_holiday_target_temps_when_opmode_arrives_last(hass, setup_entry):
    """When Z1OpMode + Z1RoomTemp arrive before DayTemp/CoolingTemp, the entity must still
    acquire temperature range support once those topics appear."""
    # First batch: triggers entity creation without temperature topics
    for topic in [
        f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode",
        f"{MQTT_PREFIX}/{DEVICE}/Z1RoomTemp",
    ]:
        async_fire_mqtt_message(hass, topic, json.dumps(HOLIDAY_MSGS[topic]))
    await hass.async_block_till_done()

    # Second batch: temperature topics arrive late
    for topic in [
        f"{MQTT_PREFIX}/{DEVICE}/Z1DayTemp",
        f"{MQTT_PREFIX}/{DEVICE}/Z1CoolingTemp",
    ]:
        async_fire_mqtt_message(hass, topic, json.dumps(HOLIDAY_MSGS[topic]))
    await hass.async_block_till_done()

    attrs = _climate(hass).attributes
    assert attrs.get("target_temp_high") == 22.0
    assert attrs.get("target_temp_low") == 21.0


# ---------------------------------------------------------------------------
# hvac_action from RunDataStatuscode
# ---------------------------------------------------------------------------


async def _fire_hmu(hass, statuscode: str) -> None:
    """Fire RunDataStatuscode on the hmu device."""
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{HMU_DEVICE}/RunDataStatuscode",
        json.dumps({"value": {"value": statuscode}}),
    )
    await hass.async_block_till_done()


async def test_hvac_action_cooling_from_statuscode(hass, setup_entry):
    """auto mode + cool_compressor_active → hvac_action = COOLING."""
    await _fire(hass)
    await _fire_hmu(hass, "cool_compressor_active")
    assert _climate(hass).state == HVACMode.AUTO
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.COOLING


async def test_hvac_action_heating_from_statuscode(hass, setup_entry):
    """auto mode + heat_compressor_active → hvac_action = HEATING."""
    await _fire(hass)
    await _fire_hmu(hass, "heat_compressor_active")
    assert _climate(hass).state == HVACMode.AUTO
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.HEATING


async def test_hvac_action_idle_from_standby(hass, setup_entry):
    """auto mode + standby → hvac_action = IDLE."""
    await _fire(hass)
    await _fire_hmu(hass, "standby")
    assert _climate(hass).state == HVACMode.AUTO
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.IDLE


async def test_hvac_action_off_when_mode_off(hass, setup_entry):
    """off mode overrides statuscode → hvac_action = OFF."""
    await _fire(hass)
    await _fire_hmu(hass, "heat_compressor_active")
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode", json.dumps({"value": {"value": "off"}})
    )
    await hass.async_block_till_done()
    assert _climate(hass).state == HVACMode.OFF
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.OFF


async def test_hvac_action_cooling_from_mode_fallback(hass, setup_entry):
    """cool mode without statuscode → hvac_action = COOLING (fallback)."""
    await _fire(hass)
    async_fire_mqtt_message(
        hass, f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode", json.dumps({"value": {"value": "night"}})
    )
    await hass.async_block_till_done()
    assert _climate(hass).state == HVACMode.COOL
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.COOLING


async def test_hvac_action_updates_on_statuscode_change(hass, setup_entry):
    """Changing RunDataStatuscode updates hvac_action."""
    await _fire(hass)
    await _fire_hmu(hass, "standby")
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.IDLE
    await _fire_hmu(hass, "cool_compressor_active")
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.COOLING


async def test_hvac_action_prerun_maps_to_heating(hass, setup_entry):
    """heat_prerun → hvac_action = HEATING."""
    await _fire(hass)
    await _fire_hmu(hass, "heat_prerun")
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.HEATING


async def test_hvac_action_overrun_maps_to_cooling(hass, setup_entry):
    """cool_overrun → hvac_action = COOLING."""
    await _fire(hass)
    await _fire_hmu(hass, "cool_overrun")
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.COOLING


# ---------------------------------------------------------------------------
# hvac_action gated by Hc{n}Status (per-zone active flag)
# ---------------------------------------------------------------------------


async def _fire_hc_status(hass, zone: int, value: int) -> None:
    """Fire Hc{n}Status on the ctlv2 device."""
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Hc{zone}Status",
        json.dumps({"value": {"value": value}}),
    )
    await hass.async_block_till_done()


async def test_hvac_action_heating_when_hc_status_active(hass, setup_entry):
    """Hc1Status=1 + heat_compressor_active → HEATING for this zone."""
    await _fire(hass)
    await _fire_hmu(hass, "heat_compressor_active")
    await _fire_hc_status(hass, 1, 1)
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.HEATING


async def test_hvac_action_idle_when_hc_status_inactive(hass, setup_entry):
    """Hc1Status=0 + heat_compressor_active → IDLE; this zone is not contributing."""
    await _fire(hass)
    await _fire_hmu(hass, "heat_compressor_active")
    await _fire_hc_status(hass, 1, 0)
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.IDLE


async def test_hvac_action_cooling_when_hc_status_active(hass, setup_entry):
    """Hc1Status=1 + cool_compressor_active → COOLING for this zone."""
    await _fire(hass)
    await _fire_hmu(hass, "cool_compressor_active")
    await _fire_hc_status(hass, 1, 1)
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.COOLING


async def test_hvac_action_idle_when_hc_status_inactive_cooling(hass, setup_entry):
    """Hc1Status=0 + cool_compressor_active → IDLE; this zone is not contributing."""
    await _fire(hass)
    await _fire_hmu(hass, "cool_compressor_active")
    await _fire_hc_status(hass, 1, 0)
    assert _climate(hass).attributes.get("hvac_action") == HVACAction.IDLE


TWO_ZONE_MSGS: dict[str, dict] = {
    f"{MQTT_PREFIX}/{DEVICE}/Z1DayTemp": {"value": {"value": 21}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1RoomTemp": {"value": {"value": 20.0}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod": {"value": {"value": "01.01.2015"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod": {"value": {"value": "01.01.2015"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode": {"value": {"value": "auto"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z2DayTemp": {"value": {"value": 21}},
    f"{MQTT_PREFIX}/{DEVICE}/Z2RoomTemp": {"value": {"value": 21.5}},
    f"{MQTT_PREFIX}/{DEVICE}/Z2HolidayStartPeriod": {"value": {"value": "01.01.2015"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z2HolidayEndPeriod": {"value": {"value": "01.01.2015"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z2OpMode": {"value": {"value": "auto"}},
}


async def test_two_zones_differ_by_hc_status(hass, setup_entry):
    """Zone 1 (Hc1Status=1) shows HEATING; Zone 2 (Hc2Status=0) shows IDLE."""
    await _fire(hass, TWO_ZONE_MSGS)
    await _fire_hmu(hass, "heat_compressor_active")
    await _fire_hc_status(hass, 1, 1)
    await _fire_hc_status(hass, 2, 0)

    states = {s.name: s for s in hass.states.async_all("climate")}
    assert states["Vaillant Zone 1"].attributes.get("hvac_action") == HVACAction.HEATING
    assert states["Vaillant Zone 2"].attributes.get("hvac_action") == HVACAction.IDLE
