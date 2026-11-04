"""Tests for reading time programs (Zeitprogramme): discovery, parsing, sensor entity."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.ebusd_vaillant.const import DOMAIN
from custom_components.ebusd_vaillant.discovery import (
    DiscoveredTimeProgram,
    _analyze,
    payload_values,
)
from custom_components.ebusd_vaillant.time_program import (
    build_schedule,
    next_change,
    parse_slot,
    parse_slot_counts,
    slot_at,
)
from tests.conftest import DATA_DIR, load_data_file

TZ = ZoneInfo("Europe/Berlin")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _slot(start: str, end: str, temp=None) -> dict:
    payload = {"htm": {"value": start}, "htm_1": {"value": end}}
    if temp is not None:
        payload["slottemp"] = {"value": temp}
    return payload


def _counts(*counts: int) -> dict:
    names = ["slotcount"] + [f"slotcount_{i}" for i in range(1, 7)]
    return {n: {"value": c} for n, c in zip(names, counts, strict=True)}


def _time_programs(entities) -> dict[str, DiscoveredTimeProgram]:
    return {e.key: e for e in entities if isinstance(e, DiscoveredTimeProgram)}


# ---------------------------------------------------------------------------
# payload parsing
# ---------------------------------------------------------------------------


def test_payload_values_named_fields():
    assert payload_values(_slot("07:00", "20:30", 21)) == ["07:00", "20:30", 21]


def test_payload_values_indexed_fields():
    payload = {str(i): {"name": "slotCount", "value": i} for i in (10, 2, 0, 1)}
    assert payload_values(payload) == [0, 1, 2, 10]


def test_payload_values_non_dict():
    assert payload_values("00 0c 0a") == []
    assert payload_values(None) == []


def test_parse_slot_counts():
    assert parse_slot_counts(_counts(3, 3, 3, 3, 3, 1, 0)) == [3, 3, 3, 3, 3, 1, 0]
    assert parse_slot_counts({"slotcount": {"value": 1}}) is None
    assert parse_slot_counts(_counts(1, 1, 1, None, 1, 1, 1)) is None


def test_parse_slot_with_temperature():
    assert parse_slot(_slot("07:00", "20:30", 21)) == {
        "start": "07:00",
        "end": "20:30",
        "temperature": 21.0,
    }


def test_parse_slot_until_midnight():
    assert parse_slot(_slot("20:30", "24:00", 21))["end"] == "24:00"


def test_parse_slot_without_temperature():
    assert parse_slot(_slot("06:00", "08:00"), has_temperature=False) == {
        "start": "06:00",
        "end": "08:00",
    }


@pytest.mark.parametrize(
    "payload",
    [
        _slot("00:00", "00:00", None),  # unused slot register
        _slot("10:00", "09:00", 20),  # end before start
        _slot("25:00", "26:00", 20),  # out of range
        _slot("bogus", "10:00", 20),
        {"htm": {"value": "07:00"}},
        None,
    ],
)
def test_parse_slot_invalid(payload):
    assert parse_slot(payload) is None


# ---------------------------------------------------------------------------
# schedule building and evaluation
# ---------------------------------------------------------------------------


def test_build_schedule_respects_slot_counts():
    payloads = {
        "monday": [_slot("06:00", "08:00", 21), _slot("17:00", "22:00", 20), None],
        # stale data in slot 1, but Timeframes says only 1 slot is active
        "tuesday": [_slot("06:00", "22:00", 21), _slot("23:00", "24:00", 19), None],
    }
    schedule = build_schedule([2, 1, 0, 0, 0, 0, 0], payloads)
    assert [s["start"] for s in schedule["monday"]] == ["06:00", "17:00"]
    assert [s["start"] for s in schedule["tuesday"]] == ["06:00"]
    assert schedule["sunday"] == []


def test_build_schedule_without_counts_skips_empty_slots():
    payloads = {"monday": [_slot("17:00", "22:00", 20), _slot("00:00", "00:00"), None]}
    schedule = build_schedule(None, payloads)
    assert schedule["monday"] == [{"start": "17:00", "end": "22:00", "temperature": 20.0}]


def test_build_schedule_sorts_slots():
    payloads = {"monday": [_slot("17:00", "22:00", 20), _slot("06:00", "08:00", 21)]}
    schedule = build_schedule([2, 0, 0, 0, 0, 0, 0], payloads)
    assert [s["start"] for s in schedule["monday"]] == ["06:00", "17:00"]


def _weekday_schedule() -> dict:
    """Mon-Fri 06:00-08:00 @21 and 17:00-22:00 @20, weekend empty."""
    day = [
        {"start": "06:00", "end": "08:00", "temperature": 21.0},
        {"start": "17:00", "end": "22:00", "temperature": 20.0},
    ]
    return {d.lower(): (list(day) if i < 5 else []) for i, d in enumerate(DAYS)}


def test_slot_at_and_next_change_inside_slot():
    schedule = _weekday_schedule()
    now = datetime(2026, 10, 26, 7, 15, tzinfo=TZ)  # Monday
    assert slot_at(schedule, now)["start"] == "06:00"
    assert next_change(schedule, now) == datetime(2026, 10, 26, 8, 0, tzinfo=TZ)


def test_next_change_between_slots():
    schedule = _weekday_schedule()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=TZ)
    assert slot_at(schedule, now) is None
    assert next_change(schedule, now) == datetime(2026, 10, 26, 17, 0, tzinfo=TZ)


def test_slot_end_is_exclusive():
    schedule = _weekday_schedule()
    assert slot_at(schedule, datetime(2026, 10, 26, 8, 0, tzinfo=TZ)) is None


def test_next_change_skips_weekend():
    schedule = _weekday_schedule()
    now = datetime(2026, 10, 30, 23, 0, tzinfo=TZ)  # Friday night
    assert next_change(schedule, now) == datetime(2026, 11, 2, 6, 0, tzinfo=TZ)  # Monday


def test_next_change_merges_adjacent_slots_with_same_temperature():
    day = [
        {"start": "00:00", "end": "07:00", "temperature": 21.0},
        {"start": "07:00", "end": "20:30", "temperature": 21.0},
        {"start": "20:30", "end": "24:00", "temperature": 18.0},
    ]
    schedule = {d.lower(): list(day) for d in DAYS}
    now = datetime(2026, 10, 26, 3, 0, tzinfo=TZ)
    assert next_change(schedule, now) == datetime(2026, 10, 26, 20, 30, tzinfo=TZ)
    # 18 °C until midnight, then 21 °C again from 00:00
    later = datetime(2026, 10, 26, 21, 0, tzinfo=TZ)
    assert next_change(schedule, later) == datetime(2026, 10, 27, 0, 0, tzinfo=TZ)


def test_next_change_constant_schedule():
    full = {d.lower(): [{"start": "00:00", "end": "24:00", "temperature": 20.0}] for d in DAYS}
    assert next_change(full, datetime(2026, 10, 26, 3, 0, tzinfo=TZ)) is None
    empty = {d.lower(): [] for d in DAYS}
    assert next_change(empty, datetime(2026, 10, 26, 3, 0, tzinfo=TZ)) is None


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def test_discovery_vrc720_fixture():
    prefix, by_device = load_data_file(DATA_DIR / "vrc720.yml")
    tps = _time_programs(_analyze(by_device, prefix))
    # Z2/Z3 are inactive zones and CcTimer has 0 slots on every day
    assert set(tps) == {"ctlv2_zone1_timer", "ctlv2_hwc_timer"}

    zone = tps["ctlv2_zone1_timer"]
    assert zone.program == "heating"
    assert zone.device_key == "ctlv2_zone1"
    assert zone.has_temperature
    assert zone.timeframes.read_topic == "ebusd/ctlv2/Z1Timer_Timeframes"
    assert zone.timeframes.write_topic is None
    assert set(zone.slots) == {d.lower() for d in DAYS}
    assert [t.read_topic for t in zone.slots["monday"]] == [
        f"ebusd/ctlv2/Z1Timer_Monday{i}" for i in range(3)
    ]

    hwc = tps["ctlv2_hwc_timer"]
    assert hwc.program == "hot_water"
    assert hwc.device_key == "ctlv2_hwc"


def test_discovery_vrc720_fixture_schedule():
    prefix, by_device = load_data_file(DATA_DIR / "vrc720.yml")
    hwc = _time_programs(_analyze(by_device, prefix))["ctlv2_hwc_timer"]
    msgs = by_device["ctlv2"]

    def raw(cfg):
        return msgs.get(cfg.read_topic.rsplit("/", 1)[1])

    schedule = build_schedule(
        parse_slot_counts(raw(hwc.timeframes)),
        {day: [raw(t) for t in topics] for day, topics in hwc.slots.items()},
    )
    assert schedule["thursday"] == [{"start": "05:00", "end": "19:30", "temperature": 55.0}]
    assert schedule["friday"] == [{"start": "05:30", "end": "20:00", "temperature": 55.0}]


def test_discovery_without_timer_topics(data_file):
    """Fixtures from controllers without *Timer_* messages yield no time programs."""
    prefix, by_device = data_file
    if any("Timer_" in k for msgs in by_device.values() for k in msgs):
        pytest.skip("fixture has timer topics")
    assert not _time_programs(_analyze(by_device, prefix))


ZONE_BASE = {
    "Z1OpMode": {"value": {"value": "auto"}},
    "Z1RoomTemp": {"value": {"value": 21.5}},
    "Z1DayTemp": {"value": {"value": 21}},
}


def test_discovery_zone_timer_from_single_slot():
    msgs = {**ZONE_BASE, "Z1Timer_Monday0": _slot("06:00", "22:00", 21)}
    tps = _time_programs(_analyze({"ctlv2": msgs}, "ebusd"))
    zone = tps["ctlv2_zone1_timer"]
    # canonical fallback names so missing topics can be primed
    assert zone.timeframes.read_topic == "ebusd/ctlv2/Z1Timer_Timeframes"
    assert zone.slots["sunday"][2].read_topic == "ebusd/ctlv2/Z1Timer_Sunday2"


def test_discovery_zone_timer_requires_zone():
    msgs = {"Z2Timer_Timeframes": _counts(1, 1, 1, 1, 1, 1, 1)}
    assert not _time_programs(_analyze({"ctlv2": msgs}, "ebusd"))


def test_discovery_circulation_with_slots():
    msgs = {
        "HwcOpMode": {"value": {"value": "auto"}},
        "HwcTempDesired": {"value": {"value": 50}},
        "CcTimer_Timeframes": _counts(1, 1, 1, 1, 1, 0, 0),
    }
    tps = _time_programs(_analyze({"ctlv2": msgs}, "ebusd"))
    cc = tps["ctlv2_cc_timer"]
    assert cc.program == "circulation"
    assert not cc.has_temperature
    assert cc.device_key == "ctlv2_hwc"


def test_discovery_hwc_timer_without_water_heater():
    msgs = {"HwcTimer_Timeframes": _counts(1, 1, 1, 1, 1, 1, 1)}
    tps = _time_programs(_analyze({"ctlv2": msgs}, "ebusd"))
    assert tps["ctlv2_hwc_timer"].device_key == "ctlv2"


# ---------------------------------------------------------------------------
# sensor entity (MQTT integration)
# ---------------------------------------------------------------------------

PREFIX = "ebusd"
DEVICE = "ctlv2"


def _zone_messages() -> dict[str, dict]:
    msgs = {f"{PREFIX}/{DEVICE}/{k}": v for k, v in ZONE_BASE.items()}
    msgs[f"{PREFIX}/{DEVICE}/Z1Timer_Timeframes"] = _counts(2, 2, 2, 2, 2, 0, 0)
    for day in DAYS[:5]:
        msgs[f"{PREFIX}/{DEVICE}/Z1Timer_{day}0"] = _slot("06:00", "08:00", 21)
        msgs[f"{PREFIX}/{DEVICE}/Z1Timer_{day}1"] = _slot("17:00", "22:00", 20)
        msgs[f"{PREFIX}/{DEVICE}/Z1Timer_{day}2"] = _slot("00:00", "00:00", 0)
    return msgs


@pytest.fixture
async def setup_entry(hass, mqtt_mock):
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = MockConfigEntry(domain=DOMAIN, data={"mqtt_prefix": PREFIX})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _fire(hass, msgs: dict) -> None:
    # twice: first round triggers discovery, second delivers values to new entities
    for _ in range(2):
        for topic, payload in msgs.items():
            async_fire_mqtt_message(hass, topic, json.dumps(payload))
        await hass.async_block_till_done()


def _time_program_state(hass):
    states = [
        s for s in hass.states.async_all("sensor") if s.attributes.get("program") == "heating"
    ]
    assert len(states) == 1, states
    return states[0]


async def test_sensor_reports_schedule(hass, setup_entry, freezer):
    freezer.move_to(datetime(2026, 10, 26, 7, 15, tzinfo=TZ))  # Monday
    await _fire(hass, _zone_messages())

    state = _time_program_state(hass)
    assert state.state == "active"
    assert state.attributes["slot_start"] == "06:00"
    assert state.attributes["slot_end"] == "08:00"
    assert state.attributes["slot_temperature"] == 21.0
    assert state.attributes["next_change"] == "2026-10-26T08:00:00+01:00"
    schedule = state.attributes["schedule"]
    assert schedule["monday"] == [
        {"start": "06:00", "end": "08:00", "temperature": 21.0},
        {"start": "17:00", "end": "22:00", "temperature": 20.0},
    ]
    assert schedule["saturday"] == []


async def test_sensor_updates_at_next_change(hass, setup_entry, freezer):
    freezer.move_to(datetime(2026, 10, 26, 7, 59, tzinfo=TZ))
    await _fire(hass, _zone_messages())
    assert _time_program_state(hass).state == "active"

    freezer.move_to(datetime(2026, 10, 26, 8, 0, 1, tzinfo=TZ))
    async_fire_time_changed(hass, datetime(2026, 10, 26, 8, 0, 1, tzinfo=TZ))
    await hass.async_block_till_done()

    state = _time_program_state(hass)
    assert state.state == "inactive"
    assert state.attributes["slot_temperature"] is None
    assert state.attributes["next_change"] == "2026-10-26T17:00:00+01:00"


async def test_sensor_follows_slot_changes(hass, setup_entry, freezer):
    freezer.move_to(datetime(2026, 10, 26, 12, 0, tzinfo=TZ))
    await _fire(hass, _zone_messages())
    assert _time_program_state(hass).state == "inactive"

    # changed on the controller / via app: Monday slot 0 now lasts until 13:00
    async_fire_mqtt_message(
        hass,
        f"{PREFIX}/{DEVICE}/Z1Timer_Monday0",
        json.dumps(_slot("06:00", "13:00", 21)),
    )
    await hass.async_block_till_done()
    state = _time_program_state(hass)
    assert state.state == "active"
    assert state.attributes["slot_end"] == "13:00"


async def test_timer_topics_are_primed(hass, setup_entry, mqtt_client_mock):
    await _fire(hass, _zone_messages())
    await hass.async_block_till_done(wait_background_tasks=True)
    published = {c.args[0]: c.args[1] for c in mqtt_client_mock.publish.call_args_list}
    assert published.get(f"{PREFIX}/{DEVICE}/Z1Timer_Timeframes/get") == "?1"
    for day in DAYS:
        for slot in range(3):
            assert f"{PREFIX}/{DEVICE}/Z1Timer_{day}{slot}/get" in published
    # read-only: nothing is written to the controller
    assert not [t for t in published if "Timer_" in t and t.endswith("/set")]


async def test_sensor_unique_id_and_device(hass, setup_entry):
    await _fire(hass, _zone_messages())
    state = _time_program_state(hass)
    entry = er.async_get(hass).async_get(state.entity_id)
    assert entry.unique_id == "ebusd_time_program_ctlv2_zone1_timer"
    device = dr.async_get(hass).async_get(entry.device_id)
    assert (DOMAIN, "ctlv2_zone1") in device.identifiers
