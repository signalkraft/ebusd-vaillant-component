# /// script
# requires-python = ">=3.14"
# dependencies = ["paho-mqtt>=2"]
# ///

import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass

import paho.mqtt.client as mqtt

BROKER = "192.168.12.64"
PORT = 1883
PREFIX = "ebusd"
TIMEOUT = 30
ZONES = 4

ROLE_PATTERNS: dict[str, list[str]] = {
    "hwc": [
        "HwcOpMode",
        "HwcOPMode",
        "HwcTempDesired",
        "HwcStorageTemp",
        "HwcStorageTempBottom",
        "HwcStorageTempTop",
        "DisplayedHwcStorageTemp",
        "HwcSFMode",
        "HwcHolidayStartPeriod",
        "HwcHolidayStartDate",
        "HwcHolidayEndPeriod",
        "HwcHolidayEndDate",
        "HwcHolidayStartTime",
        "HwcHolidayEndTime",
    ],
    "pressure": ["WaterPressure", "DisplaySystemPressure"],
    "zone": [
        "Z{n}OpMode",
        "z{n}OpModeHeating",
        "z{n}OpModeCooling",
        "z{n}OpMode",
        "Z{n}RoomTemp",
        "z{n}RoomTemp",
        "Z{n}DayTemp",
        "Z{n}ManualTemp",
        "z{n}HeatingRoomTempDesiredManualControlled",
        "Z{n}CoolingTemp",
        "Z{n}CoolingTempDesired",
        "Z{n}CoolingManualTemp",
        "z{n}CoolingRoomTempDesiredManualControlled",
        "Z{n}NightTemp",
        "z{n}SetBackTemp",
        "Z{n}HolidayStartDate",
        "Z{n}HolidayStartPeriod",
        "z{n}HolidayStartDate",
        "Z{n}HolidayEndDate",
        "Z{n}HolidayEndPeriod",
        "z{n}HolidayEndDate",
        "z{n}HolidayStartTime",
        "Z{n}HolidayStartTime",
        "z{n}HolidayEndTime",
        "Z{n}HolidayEndTime",
        "Z{n}QuickVetoTemp",
        "Z{n}QuickVetoDuration",
        "Z{n}QuickVetoEndDate",
        "Z{n}QuickVetoEndTime",
        "Hc{n}CircuitType",
        "Z{n}RoomZoneMapping",
    ],
}


@dataclass
class Result:
    topic: str
    response_payload: object = None


def expand_patterns(zones: int = 4) -> list[str]:
    all_topics: set[str] = set()
    for cat, patterns in ROLE_PATTERNS.items():
        if cat in ("hwc", "pressure"):
            all_topics.update(patterns)
        elif cat == "zone":
            for z in range(1, zones + 1):
                for pat in patterns:
                    all_topics.add(pat.format(n=z))
    return sorted(all_topics)


def _flatten(payload: dict) -> dict | object:
    if "value" in payload and isinstance(payload["value"], dict) and "value" in payload["value"]:
        return payload["value"]["value"]
    result = {}
    for k, v in payload.items():
        if isinstance(v, dict) and set(v.keys()) == {"value"}:
            result[k] = v["value"]
        else:
            result[k] = v
    return result


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    topics_to_try = expand_patterns(ZONES)
    results: dict[str, Result] = {}
    seen_devices: set[str] = set()
    get_to_topic: dict[str, str] = {}  # "prefix/device/topic" -> canonical topic name
    get_count = [0]
    phase = [0]  # 0=connecting, 1=gathering, 2=sending, 3=waiting, 4=done

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            print(f"Connection failed: {reason_code}", file=sys.stderr)
            sys.exit(1)
        _client.subscribe(f"{PREFIX}/#")
        print(f"Connected to {BROKER}:{PORT}, subscribed to {PREFIX}/#")

    def on_subscribe(_client, _userdata, _mid, _reason_codes, _properties):
        phase[0] = 1

    def on_message(_client, _userdata, msg):
        topic = msg.topic
        payload_str = msg.payload.decode(errors="replace")
        parts = topic.split("/")
        if len(parts) >= 3:
            dev = parts[1]
            if dev not in ("global", "Broadcast"):
                seen_devices.add(dev)

        if topic in get_to_topic:
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError:
                payload = payload_str
            results[get_to_topic[topic]].response_payload = payload

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe

    client.connect(BROKER, PORT, 60)
    client.loop_start()

    # Phase 1: wait for subscribe ack + gather retained messages
    for _ in range(100):
        if phase[0] >= 1:
            break
        time.sleep(0.05)
    print("Gathering retained messages (3s)...")
    time.sleep(3)

    if not seen_devices:
        print("No devices seen, trying common names: ctlv3, ctlv2, hmu, bai, bai00")
        seen_devices.update(["ctlv3", "ctlv2", "hmu", "bai", "bai00"])
    else:
        print(f"Devices seen: {sorted(seen_devices)}")

    # Phase 2: send get requests
    for device in seen_devices:
        for t in topics_to_try:
            get_topic = f"{PREFIX}/{device}/{t}/get"
            base_topic = f"{PREFIX}/{device}/{t}"
            key = f"{device}/{t}"
            results[key] = Result(topic=base_topic)
            get_to_topic[base_topic] = key
            client.publish(get_topic, "?1")
            get_count[0] += 1

    print(f"Sent {get_count[0]} get requests across {len(seen_devices)} device(s)")
    print(f"Waiting {TIMEOUT}s for responses...\n")

    time.sleep(TIMEOUT)
    client.loop_stop()
    client.disconnect()

    # --- results ---
    responded = []
    silent = []
    for key in sorted(results):
        r = results[key]
        if r.response_payload is not None:
            responded.append((key, r))
        else:
            silent.append((key, r))

    print("\n" + "=" * 80)
    print("RESPONDED")
    print("=" * 80)
    by_dev: dict[str, list] = defaultdict(list)
    for key, r in responded:
        dev = key.split("/")[0]
        by_dev[dev].append((key, r))

    for dev in sorted(by_dev):
        print(f"\n--- {dev} ---")
        for key, r in by_dev[dev]:
            p = r.response_payload
            if isinstance(p, dict):
                flat = _flatten(p)
                print(f"  {key.split('/', 1)[1]}  →  {flat}")
            else:
                print(f"  {key.split('/', 1)[1]}  →  {p}")

    print(f"\n{len(responded)} topics responded, {len(silent)} did not respond")

    if silent:
        print("\n" + "=" * 80)
        print("NO RESPONSE")
        print("=" * 80)
        for key, r in silent:
            print(f"  {key}")


if __name__ == "__main__":
    main()
