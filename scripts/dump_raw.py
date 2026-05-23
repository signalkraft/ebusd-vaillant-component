#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["paho-mqtt>=2.1.0"]
# ///
"""
Dump raw ebusd MQTT messages to stdout, one JSON object per line (NDJSON).

Useful for piping into jq or saving to a file for offline analysis:
    uv run scripts/dump_raw.py | tee messages.ndjson
    uv run scripts/dump_raw.py | jq 'select(.topic | contains("OpMode"))'
"""

import argparse
import json
import signal
import sys
import time

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883


def parse_args():
    p = argparse.ArgumentParser(description="Dump raw ebusd MQTT messages as NDJSON")
    p.add_argument("--broker", default=BROKER)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--timeout", type=int, default=0, help="Exit after N seconds (0 = run forever)")
    p.add_argument("--topic", default="ebusd/#", help="MQTT topic to subscribe to")
    return p.parse_args()


def main():
    args = parse_args()
    stop = False

    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe(args.topic)
        print(f"# Subscribed to {args.topic}", file=sys.stderr)

    def on_message(client, userdata, msg):
        try:
            payload_str = msg.payload.decode("utf-8")
        except Exception:
            payload_str = repr(msg.payload)

        try:
            payload = json.loads(payload_str)
        except Exception:
            payload = payload_str

        record = {
            "ts": time.time(),
            "topic": msg.topic,
            "payload": payload,
        }
        print(json.dumps(record, ensure_ascii=False))
        sys.stdout.flush()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port)
    client.loop_start()

    def shutdown(sig, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, shutdown)

    if args.timeout:
        time.sleep(args.timeout)
    else:
        while not stop:
            time.sleep(0.1)

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
