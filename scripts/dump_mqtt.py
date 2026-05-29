# /// script
# requires-python = ">=3.14"
# dependencies = ["paho-mqtt>=2"]
# ///

import json
import time
from collections import defaultdict

import paho.mqtt.client as mqtt

BROKER = "192.168.12.64"
PORT = 1883
PREFIX = "ebusd"


def main() -> None:
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

    client.connect(BROKER, PORT, 60)
    client.subscribe(f"{PREFIX}/#")
    client.loop_start()

    time.sleep(3)
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
