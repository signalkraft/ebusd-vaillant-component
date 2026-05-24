"""Integration tests for EbusdAwayModeSwitch entity."""

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


def _switch(hass):
    states = hass.states.async_all("switch")
    assert states, "No switch entities found"
    return states[0]


def _published(mqtt_client_mock) -> dict[str, str]:
    result: dict[str, str] = {}
    for c in mqtt_client_mock.publish.call_args_list:
        topic = c.args[0]
        payload = c.args[1] if len(c.args) > 1 else ""
        result[topic] = payload.decode() if isinstance(payload, bytes) else str(payload)
    return result


async def test_switch_discovered_per_zone(hass, setup_entry):
    await _fire(hass)
    assert len(hass.states.async_all("switch")) == 1


async def test_switch_off_by_default(hass, setup_entry):
    await _fire(hass)
    assert _switch(hass).state == "off"


async def test_switch_on_when_holiday_active(hass, setup_entry):
    await _fire(hass)
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
    assert _switch(hass).state == "on"


async def test_switch_updates_on_mqtt(hass, setup_entry):
    await _fire(hass)
    state = _switch(hass)
    assert state.state == "off"
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
    assert _switch(hass).state == "on"
    async_fire_mqtt_message(
        hass,
        f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod",
        json.dumps({"value": {"value": "01.01.2015"}}),
    )
    await hass.async_block_till_done()
    assert _switch(hass).state == "off"


async def test_turn_on_publishes_holiday_dates(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
    entity_id = _switch(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": entity_id},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod/set" in published
    assert f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod/set" in published


async def test_turn_off_publishes_reset_dates(hass, setup_entry, mqtt_client_mock):
    await _fire(hass)
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
    assert _switch(hass).state == "on"
    entity_id = _switch(hass).entity_id
    mqtt_client_mock.publish.reset_mock()
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": entity_id},
        blocking=True,
    )
    published = _published(mqtt_client_mock)
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayStartPeriod/set") == "01.01.2015"
    assert published.get(f"{MQTT_PREFIX}/{DEVICE}/Z1HolidayEndPeriod/set") == "01.01.2015"
