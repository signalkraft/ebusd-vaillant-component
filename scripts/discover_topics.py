#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["paho-mqtt>=2.1.0"]
# ///
"""Discover all ebusd MQTT topics and print them with their payloads."""

import argparse
import json
import signal
import sys
import time
from collections import defaultdict

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883
SUBSCRIBE_TOPIC = "ebusd/#"


def parse_args():
    p = argparse.ArgumentParser(description="Discover ebusd MQTT topics")
    p.add_argument("--broker", default=BROKER)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--timeout", type=int, default=10, help="Seconds to collect messages")
    p.add_argument("--filter", default=None, help="Only show topics containing this string")
    p.add_argument("--json-only", action="store_true", help="Only show topics with JSON payloads")
    p.add_argument("--raw", action="store_true", help="Print every message as it arrives")
    return p.parse_args()


def main():
    args = parse_args()
    topics: dict[str, str] = {}

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"Connected to {args.broker}:{args.port}", file=sys.stderr)
        client.subscribe(SUBSCRIBE_TOPIC)

    def on_message(client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            payload = repr(msg.payload)

        if args.filter and args.filter not in topic:
            return

        if args.json_only:
            try:
                json.loads(payload)
            except Exception:
                return

        topics[topic] = payload

        if args.raw:
            print(f"{topic}  →  {payload}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.broker, args.port)
    client.loop_start()

    def shutdown(sig, frame):
        pass

    signal.signal(signal.SIGINT, shutdown)

    print(f"Collecting for {args.timeout}s …", file=sys.stderr)
    time.sleep(args.timeout)
    client.loop_stop()
    client.disconnect()

    if args.raw:
        return

    # Group by device prefix (ebusd/<device>/...)
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for topic, payload in sorted(topics.items()):
        parts = topic.split("/")
        group = "/".join(parts[:2]) if len(parts) >= 2 else topic
        groups[group].append((topic, payload))

    print(f"\n=== Discovered {len(topics)} topics across {len(groups)} devices ===\n")
    for group, items in sorted(groups.items()):
        print(f"[{group}]  ({len(items)} topics)")
        for topic, payload in items:
            # Pretty-print JSON inline if short enough
            try:
                parsed = json.loads(payload)
                display = json.dumps(parsed)
                if len(display) > 120:
                    display = display[:117] + "…"
            except Exception:
                display = payload
            print(f"  {topic}")
            print(f"    {display}")
        print()


if __name__ == "__main__":
    main()
