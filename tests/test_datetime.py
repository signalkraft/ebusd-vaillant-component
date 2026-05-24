"""Integration tests for ebusd Vaillant datetime entities."""

import json

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.ebusd_vaillant.const import DOMAIN

MQTT_PREFIX = "ebusd"
DEVICE = "ctlv2"

BASE_MSGS: dict[str, dict] = {
    f"{MQTT_PREFIX}/{DEVICE}/Z1DayTemp": {"value": {"value": 21}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1NightTemp": {"value": {"value": 18}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1RoomTemp": {"value": {"value": 21.5}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod": {"value": {"value": "01.01.2015"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod": {"value": {"value": "01.01.2015"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndDate": {"value": {"value": "23.05.2026"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndTime": {"value": {"value": "02:51:00"}},
    f"{MQTT_PREFIX}/{DEVICE}/Z1OpMode": {"value": {"value": "auto"}},
}

HOLIDAY_TIME_MSGS: dict[str, dict] = {
    f"{MQTT_PREFIX}/{DEVICE}/z1HolidayStartTime": {"0": {"name": "", "value": "10:00:00"}},
    f"{MQTT_PREFIX}/{DEVICE}/z1HolidayEndTime": {"0": {"name": "", "value": "18:30:00"}},
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


async def _fire(hass, msgs: dict = BASE_MSGS) -> None:
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()
    for topic, payload in msgs.items():
        async_fire_mqtt_message(hass, topic, json.dumps(payload))
    await hass.async_block_till_done()


def _find_entity(hass, suffix: str):
    for state in hass.states.async_all("datetime"):
        if state.entity_id.endswith(suffix):
            return state
    pytest.fail(f"No datetime entity ending with '{suffix}' found")


async def test_all_datetime_entities_discovered(hass, setup_entry):
    """Three datetime entities (quick veto end, holiday start, holiday end) created per zone."""
    msgs = {k: v for k, v in BASE_MSGS.items() if "QuickVetoEnd" not in k}
    await _fire(hass, msgs)
    assert len(hass.states.async_all("datetime")) == 3


async def test_quick_veto_end_state(hass, setup_entry):
    await _fire(hass)
    assert _find_entity(hass, "quick_veto_end").state == "2026-05-23T02:51:00+00:00"


async def test_quick_veto_end_unknown_before_mqtt(hass, setup_entry):
    """State is unknown until both date and time arrive."""
    msgs = {k: v for k, v in BASE_MSGS.items() if "QuickVetoEnd" not in k}
    await _fire(hass, msgs)
    assert _find_entity(hass, "quick_veto_end").state == "unknown"


async def test_quick_veto_end_updates_on_mqtt(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndDate",
        json.dumps({"value": {"value": "24.05.2026"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1QuickVetoEndTime",
        json.dumps({"value": {"value": "10:00:00"}}),
    )
    await hass.async_block_till_done()
    assert _find_entity(hass, "quick_veto_end").state == "2026-05-24T10:00:00+00:00"


async def test_holiday_start_end_state_without_time(hass, setup_entry):
    """Holiday entities show unknown when date is the reset sentinel (01.01.2015)."""
    await _fire(hass)
    assert _find_entity(hass, "holiday_start").state == "unknown"
    assert _find_entity(hass, "holiday_end").state == "unknown"


async def test_holiday_start_end_state_with_time(hass, setup_entry):
    """Holiday entities show unknown when date is reset sentinel even with time data present."""
    msgs = {**BASE_MSGS, **HOLIDAY_TIME_MSGS}
    await _fire(hass, msgs)
    assert _find_entity(hass, "holiday_start").state == "unknown"
    assert _find_entity(hass, "holiday_end").state == "unknown"


async def test_holiday_start_end_unknown_before_mqtt(hass, setup_entry):
    """State is unknown until holiday date data arrives."""
    msgs = {
        k: v
        for k, v in BASE_MSGS.items()
        if "HolidayStartPeriod" not in k and "HolidayEndPeriod" not in k
    }
    await _fire(hass, msgs)
    assert _find_entity(hass, "holiday_start").state == "unknown"
    assert _find_entity(hass, "holiday_end").state == "unknown"


async def test_holiday_start_end_updates_on_mqtt(hass, setup_entry):
    await _fire(hass)
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod",
        json.dumps({"value": {"value": "15.06.2026"}}),
    )
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod",
        json.dumps({"value": {"value": "20.06.2026"}}),
    )
    await hass.async_block_till_done()
    assert _find_entity(hass, "holiday_start").state == "2026-06-15T00:00:00+00:00"
    assert _find_entity(hass, "holiday_end").state == "2026-06-20T00:00:00+00:00"
