# Capturing test data

To add test data for a new Vaillant system (different boiler model, additional
zone configurations, etc.), you can capture live MQTT messages from your ebusd
instance:

## Method 1: Inside Home Assistant

After installing the integration, use the built-in diagnostic services:

1. Go to **Settings :material-arrow-right: Developer tools :material-arrow-right: Services**
   or open <https://my.home-assistant.io/redirect/developer_services/>
2. Call the service `ebusd_vaillant.dump_mqtt_values`  -  returns all cached
   values accumulated since startup as a YAML-compatible dict, keyed by device
3. Call the service `ebusd_vaillant.record_topic_changes` with a `timeout`
   (e.g. 30 seconds)  -  subscribes to the ebusd prefix and returns every
   message received during that window

Save the result to `tests/data/<name>.yml` (use any descriptive filename).
The test suite runs against every `.yml` and `.yaml` file in that directory.

## Method 2: External MQTT client

Run the provided scripts from any machine with MQTT access to your ebusd
broker:

```shell
# Analyze climate-relevant topics (15 second capture)
uv run scripts/analyze_structure.py --broker 127.0.0.1 --timeout 30

# Dump all raw messages as NDJSON (pipe to a file for offline analysis)
uv run scripts/dump_raw.py --broker 127.0.0.1 --timeout 30 > messages.ndjson
```

Both scripts accept `--broker`, `--port`, and `--timeout` arguments.
