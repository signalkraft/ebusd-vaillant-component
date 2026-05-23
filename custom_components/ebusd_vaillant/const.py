DOMAIN = "ebusd_vaillant"

CONF_MQTT_PREFIX = "mqtt_prefix"
DEFAULT_MQTT_PREFIX = "ebusd"

CONF_NAME = "name"
DEFAULT_NAME = "Vaillant"

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
