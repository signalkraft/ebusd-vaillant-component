#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["paho-mqtt>=2.1.0"]
# ///
"""Watch one or more MQTT topics and pretty-print messages as they arrive."""

import argparse
import json
import signal
import sys
import time

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883


def parse_args():
    p = argparse.ArgumentParser(description="Watch ebusd MQTT topics in real time")
    p.add_argument(
        "topics", nargs="*", default=["ebusd/#"], help="Topics to subscribe to (default: ebusd/#)"
    )
    p.add_argument("--broker", default=BROKER)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--username", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--timeout", type=int, default=0, help="Exit after N seconds (0 = run forever)")
    return p.parse_args()


def main():
    args = parse_args()
    stop = False

    def on_connect(client, userdata, flags, reason_code, properties):
        for topic in args.topics:
            client.subscribe(topic)
            print(f"Subscribed to: {topic}", file=sys.stderr)

    def on_message(client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            payload = repr(msg.payload)

        ts = time.strftime("%H:%M:%S")

        try:
            parsed = json.loads(payload)
            pretty = json.dumps(parsed, indent=2)
        except Exception:
            pretty = payload

        print(f"\n[{ts}] {topic}")
        print(pretty)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    if args.username:
        client.username_pw_set(args.username, args.password)

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
