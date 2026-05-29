---
hide:
  - toc
---

# Entities

Entities provided by the ebusd Vaillant integration.

| Entity Name | Description | Type | Supported Features |
|---|---|---|---|
| `EbusdClimateEntity` | Climate entity for a heating zone: target temperature, HVAC mode, and boost/away presets. | `climate` | `TURN_ON, TURN_OFF, PRESET_MODE, TARGET_TEMPERATURE, TARGET_TEMPERATURE_RANGE` |
| `EbusdWaterHeaterEntity` | Water heater for a hot water circuit: temperature, operation mode, away mode, and on/off. | `water_heater` | `TARGET_TEMPERATURE, OPERATION_MODE, ON_OFF, AWAY_MODE` |
| `EbusdPressureSensor` | Pressure sensor measuring heating system water pressure in bar. | `sensor` | `--` |
| `EbusdAwayModeSwitch` | Switch to toggle away mode (holiday) for a heating zone, setting start/end dates on ebusd. | `switch` | `--` |
| `EbusdHwcAwayModeSwitch` | Switch to toggle away mode (holiday) for a hot water circuit, setting dates on ebusd. | `switch` | `--` |
| `EbusdHwcBoostSwitch` | Switch to toggle hot water boost mode (load) on a water heater circuit. | `switch` | `--` |
| `EbusdQuickVetoEndEntity` | Datetime entity showing when the quick veto expires on a heating zone. | `datetime` | `--` |
| `EbusdHolidayEntity` | Datetime entity for holiday start/end dates on a heating zone or hot water circuit. | `datetime` | `--` |
