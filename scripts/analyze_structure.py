#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["paho-mqtt>=2.1.0"]
# ///
"""
Analyze ebusd MQTT message structure to identify climate-relevant topics.

Looks for patterns matching:
  - OpMode  → mode control
  - TempDesired / DayTemp / NightTemp / ActualTemp → temperature setpoints
  - SensorData → sensor readings
  - Hwc* → hot water circuit
  - Z1* / Z2* → heating zones
"""

import argparse
import json
import re
import signal
import sys
import time
from collections import defaultdict

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883

# Patterns that suggest climate-relevant messages
CLIMATE_PATTERNS = [
    (re.compile(r"OpMode", re.I), "mode"),
    (re.compile(r"(DayTemp|NightTemp|TempDesired|ActualRoomTemp)", re.I), "temperature_setpoint"),
    (re.compile(r"(SensorData|ActualTemp|CurrentTemp)", re.I), "sensor"),
    (re.compile(r"Hwc", re.I), "hot_water"),
    (re.compile(r"Z[12][A-Z]", re.I), "zone"),
    (re.compile(r"(FlowTemp|ReturnTemp)", re.I), "flow_temp"),
]


def classify(topic: str) -> list[str]:
    return [label for pat, label in CLIMATE_PATTERNS if pat.search(topic)]


def extract_value(payload: str) -> str | None:
    """Try to pull a scalar value out of an ebusd JSON payload."""
    try:
        data = json.loads(payload)
        # ebusd typically wraps in {"value": {"value": X}} or {"value": X}
        if isinstance(data, dict):
            v = data.get("value")
            if isinstance(v, dict):
                return str(v.get("value", v))
            if v is not None:
                return str(v)
        return json.dumps(data)
    except Exception:
        return payload.strip() or None


def parse_args():
    p = argparse.ArgumentParser(description="Analyze ebusd MQTT for climate topics")
    p.add_argument("--broker", default=BROKER)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--timeout", type=int, default=15, help="Seconds to collect messages")
    p.add_argument(
        "--all", action="store_true", help="Show all topics, not just climate-relevant ones"
    )
    return p.parse_args()


def main():
    args = parse_args()
    messages: dict[str, str] = {}

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"Connected - collecting for {args.timeout}s …", file=sys.stderr)
        client.subscribe("ebusd/#")

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            return
        # Skip /set and /get command topics
        if msg.topic.endswith("/set") or msg.topic.endswith("/get"):
            return
        messages[msg.topic] = payload

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port)
    client.loop_start()
    signal.signal(signal.SIGINT, lambda s, f: None)
    time.sleep(args.timeout)
    client.loop_stop()
    client.disconnect()

    # Organize by device
    by_device: dict[str, list[tuple[str, list[str], str | None]]] = defaultdict(list)
    for topic, payload in sorted(messages.items()):
        parts = topic.split("/")
        device = parts[1] if len(parts) >= 2 else "unknown"
        tags = classify(topic)
        if tags or args.all:
            value = extract_value(payload)
            by_device[device].append((topic, tags, value))

    print(f"\n=== Climate-relevant topics ({sum(len(v) for v in by_device.values())} total) ===\n")
    for device, items in sorted(by_device.items()):
        print(f"Device: {device}")
        for topic, tags, value in items:
            tag_str = ", ".join(tags) if tags else " - "
            print(f"  [{tag_str:35s}]  {topic}")
            if value is not None:
                print(f"  {'':37s}  → {value}")
        print()

    # Print a suggested topic map
    print("=== Suggested topic map for custom component ===\n")
    for device, items in sorted(by_device.items()):
        mode_topics = [t for t, tags, _ in items if "mode" in tags]
        temp_topics = [t for t, tags, _ in items if "temperature_setpoint" in tags]
        sensor_topics = [t for t, tags, _ in items if "sensor" in tags]
        if mode_topics or temp_topics:
            print(f"{device}:")
            for t in mode_topics:
                print(f"  mode:    {t}")
            for t in temp_topics:
                print(f"  temp:    {t}")
            for t in sensor_topics:
                print(f"  sensor:  {t}")
            print()


if __name__ == "__main__":
    main()
