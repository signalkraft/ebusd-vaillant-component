# /// script
# requires-python = ">=3.14"
# dependencies = ["paho-mqtt>=2"]
# ///

import argparse
import json
import time
from collections import defaultdict

import paho.mqtt.client as mqtt

BROKER = "192.168.12.64"
PORT = 1883
PREFIX = "ebusd"


def main() -> None:
    p = argparse.ArgumentParser(description="Dump all ebusd MQTT topics")
    p.add_argument("--broker", default=BROKER)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--username", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--timeout", type=int, default=3, help="Seconds to collect")
    args = p.parse_args()

    messages: list[tuple[str, object]] = []

    def on_message(_client, _userdata, msg):
        topic = msg.topic
        payload_str = msg.payload.decode(errors="replace")
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            payload = payload_str
        messages.append((topic, payload))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message

    if args.username:
        client.username_pw_set(args.username, args.password)

    client.connect(args.broker, args.port, 60)
    client.subscribe(f"{PREFIX}/#")
    client.loop_start()

    time.sleep(args.timeout)
    client.loop_stop()
    client.disconnect()

    by_device: dict[str, list[tuple[str, object]]] = defaultdict(list)
    for topic, payload in messages:
        parts = topic.split("/")
        dev = parts[1] if len(parts) >= 3 else "_root"
        by_device[dev].append((parts[-1], payload))

    for dev in sorted(by_device):
        print(f"\n=== {dev} ===")
        for msg_name, payload in sorted(by_device[dev], key=lambda x: x[0]):
            if isinstance(payload, dict):
                flat = _flatten(payload)
                print(f"  {msg_name}: {flat}")
            else:
                print(f"  {msg_name}: {payload}")


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


if __name__ == "__main__":
    main()
