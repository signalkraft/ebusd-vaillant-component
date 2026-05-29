---
hide:
  - toc
---

# Options

Configuration options available for the ebusd Vaillant integration.

| Option Name | Description | Default Value |
|---|---|---|
| `away_mode_duration` | Number of days the away mode lasts when activated | `7` |
| `quick_veto_duration` | Number of hours the quick veto lasts when triggered | `3` |
| `max_zones` | Limits how many zone entities are created | `4` |
| `prime_poll_values` | Tries to request typical MQTT topic names to be able to show values immediately on startup. If disabled, entities become available as MQTT values are published | `on` |
