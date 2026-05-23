# MQTT Entity Mapping

This page documents every MQTT topic the component subscribes to and how it
maps to Home Assistant entities and controls.

## Topic structure

All topics follow the same pattern:

```
{prefix}/{device_id}/{message_name}       # read (subscribed)
{prefix}/{device_id}/{message_name}/set   # write (published)
```

The default prefix is `ebusd`. The `device_id` is the ebusd device identifier
(e.g. `700` for a boiler). Each message payload is JSON with
dot-notation fields, typically `value.value`.

## HVAC mode translation

The component translates between ebusd operating mode values and Home
Assistant HVAC modes:

| ebusd value | HA HVAC mode |
|---|---|
| `auto` | `auto` |
| `day` | `heat` |
| `night` | `cool` |
| `heat` | `heat` |
| `cool` | `cool` |
| `off` | `off` |

For water heaters, the raw ebusd operation mode values (`auto`, `day`, `off`)
are passed through directly.

## Preset modes

The component exposes two preset modes on climate entities:

| Preset | HA constant | Mechanism |
|---|---|---|
| None | `PRESET_NONE` | No active override |
| Boost | `PRESET_BOOST` | Quick veto is active  -  set via target temperature change |
| Away | `PRESET_AWAY` | Holiday period is active  -  set via `async_set_preset_mode` |

Away mode sets a 7-day holiday period starting from today. Boost is triggered
automatically when a target temperature is set in `auto` mode (writes quick
veto temperature + 3-hour duration).

## Heating zones (Z1-Z4)

Climate entities are created for each heating zone that has both a
`Z{n}OpMode` and a non-null `Z{n}RoomTemp` value. The zone index ranges from
1 to 4.

| MQTT message | Field | Access | HA control / attribute |
|---|---|---|---|
| `Z{n}OpMode` | `value.value` | read/write | HVAC mode |
| `Z{n}RoomTemp` | `value.value` | read | Current temperature |
| `Z{n}DayTemp` | `value.value` | read/write | Target temperature (or low in range mode) |
| `Z{n}NightTemp` | `value.value` | read/write | Target temperature low |
| `Z{n}CoolingTemp` | `value.value` | read/write | Target temperature high |
| `Z{n}HolidayStartPeriod` | `value.value` | read/write | Preset "away" start |
| `Z{n}HolidayEndPeriod` | `value.value` | read/write | Preset "away" end |
| `Z{n}QuickVetoTemp` | `value.value` | read/write | Boost target temperature |
| `Z{n}QuickVetoDuration` | `value.value` | read/write | Boost duration (hours); write `0` to cancel |
| `Z{n}QuickVetoEndDate` | `value.value` | read/write | Boost end date; write `01.01.2015` to cancel |
| `Z{n}QuickVetoEndTime` | `value.value` | read/write | Boost end time; write `00:00:00` to cancel |

### Temperature control strategies

Depending on which temperature messages are available, the climate entity
adapts:

| Available messages | HA feature | Behavior |
|---|---|---|
| `Z{n}DayTemp` only | Target temperature | Set temp :material-arrow-right: writes `Z{n}QuickVetoTemp` + 3h duration (boost) |
| `Z{n}DayTemp` + `Z{n}NightTemp` | Target temperature range | High = `DayTemp`, low = `NightTemp`; low change triggers boost |
| `Z{n}DayTemp` + `Z{n}CoolingTemp` | Target temperature range | High = `CoolingTemp`, low = `DayTemp`; low change triggers boost |

## Water heater

A water heater entity is created when both `HwcOpMode` and `HwcTempDesired`
are present.

| MQTT message | Field | Access | HA control / attribute |
|---|---|---|---|
| `HwcOpMode` | `value.value` | read/write | Operation mode (`auto`, `day`, `off`) |
| `HwcTempDesired` | `value.value` | read/write | Target temperature |
| `HwcStorageTemp` | `value.value` | read | Current temperature |
| `HwcStorageTempBottom` | `value.value` | read | Current temperature (fallback) |
| `HwcStorageTempTop` | `value.value` | read | Current temperature (fallback) |

Current temperature is read from the first available message in the order:
`HwcStorageTemp` :material-arrow-right: `HwcStorageTempBottom` :material-arrow-right: `HwcStorageTempTop`.

## Pressure sensor

A pressure sensor entity is created when `WaterPressure` is present.

| MQTT message | Field | Access | HA control / attribute |
|---|---|---|---|
| `WaterPressure` | `value.value` | read | Native value (unit: bar) |
