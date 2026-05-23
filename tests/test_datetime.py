"""Integration tests for EbusdQuickVetoEndEntity."""

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


def _qv_entity(hass):
    states = hass.states.async_all("datetime")
    assert states, "No datetime entities found"
    return states[0]


async def test_quick_veto_end_entity_always_discovered(hass, setup_entry):
    """Datetime entity is created for every climate zone."""
    msgs = {k: v for k, v in BASE_MSGS.items() if "QuickVetoEnd" not in k}
    await _fire(hass, msgs)
    assert len(hass.states.async_all("datetime")) == 1


async def test_quick_veto_end_state(hass, setup_entry):
    await _fire(hass)
    assert _qv_entity(hass).state == "2026-05-23T02:51:00+00:00"


async def test_quick_veto_end_unknown_before_mqtt(hass, setup_entry):
    """State is unknown until both date and time arrive."""
    msgs = {k: v for k, v in BASE_MSGS.items() if "QuickVetoEnd" not in k}
    await _fire(hass, msgs)
    assert _qv_entity(hass).state == "unknown"


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
    assert _qv_entity(hass).state == "2026-05-24T10:00:00+00:00"
