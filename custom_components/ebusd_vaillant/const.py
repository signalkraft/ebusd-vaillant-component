DOMAIN = "ebusd_vaillant"

CONF_MQTT_PREFIX = "mqtt_prefix"
DEFAULT_MQTT_PREFIX = "ebusd"

CONF_NAME = "name"
DEFAULT_NAME = "Vaillant"

CONF_AWAY_MODE_DURATION = "away_mode_duration"
DEFAULT_AWAY_MODE_DURATION = 7

CONF_QUICK_VETO_DURATION = "quick_veto_duration"
DEFAULT_QUICK_VETO_DURATION = 3

# ebusd → HA HVAC mode (heating zones: Z1OpMode, Z2OpMode, hmu/SetMode.hcmode)
EBUSD_TO_HA_HVAC = {
    "auto": "auto",
    "day": "heat",
    "night": "cool",
    "off": "off",
    "heat": "heat",
    "cool": "cool",
}
HA_TO_EBUSD_HVAC = {
    "auto": "auto",
    "heat": "day",
    "cool": "night",
    "off": "off",
}

# ebusd → HA water heater operation modes (HwcOpMode)
HWC_OPERATION_MODES = ["auto", "day", "off"]
