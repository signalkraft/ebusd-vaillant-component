DOMAIN = "ebusd_vaillant"

DEFAULT_MANUFACTURER = "Vaillant"
DEFAULT_AREA = "Heating"

CONF_MQTT_PREFIX = "mqtt_prefix"
DEFAULT_MQTT_PREFIX = "ebusd"

CONF_NAME = "name"
DEFAULT_NAME = "Vaillant"

CONF_AWAY_MODE_DURATION = "away_mode_duration"
DEFAULT_AWAY_MODE_DURATION = 7

CONF_QUICK_VETO_DURATION = "quick_veto_duration"
DEFAULT_QUICK_VETO_DURATION = 3

CONF_QUICK_VETO_TEMP = "quick_veto_temp"
DEFAULT_QUICK_VETO_TEMP = 21.0

CONF_MAX_ZONES = "max_zones"
DEFAULT_MAX_ZONES = 4

CONF_ZONES_WITH_TEMP_ONLY = "zones_with_temp_only"
DEFAULT_ZONES_WITH_TEMP_ONLY = True

CONF_PRIME_VALUES = "prime_poll_values"
DEFAULT_PRIME_VALUES = True

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

# Map RunDataStatuscode values from ebusd/hmu to HA HVAC action.
_STAT_HVAC_ACTION_HEATING = frozenset(
    {
        "heat_compressor_active",
        "heat_prerun",
        "heat_overrun",
        "heat_immersion_heater_active",
    }
)
_STAT_HVAC_ACTION_COOLING = frozenset(
    {
        "cool_compressor_active",
        "cool_prerun",
        "cool_overrun",
    }
)

# Common ebusd device names to probe for discovery priming.
# Sending ?1 to these names is harmless (unknown names are silently ignored).
DISCOVERY_DEVICE_NAMES = ["ctlv3", "ctlv2", "hmu", "bai", "bai00"]

# Human-readable labels for well-known ebusd device IDs, used to build
# device_name for discovered sensors.  Keys are lower-cased device IDs.
# Unknown device IDs fall back to device_id.upper().
DEVICE_TYPE_LABELS: dict[str, str] = {
    "hmu": "Heat Pump",
    "bai": "Boiler",
    "bai00": "Boiler",
    "ctlv2": "Controller",
    "ctlv3": "Controller",
}

# Minimal topic set needed to trigger entity discovery in _analyze().
# Once entities are discovered, full priming kicks in via _prime_values().
_DISCOVERY_TOPICS_HWC = ["HwcOpMode", "HwcTempDesired"]
_DISCOVERY_TOPICS_PRESSURE = ["WaterPressure"]
_DISCOVERY_TOPICS_ZONE = ["Z{n}OpMode", "Z{n}RoomTemp"]
_DISCOVERY_TOPICS_HC = [
    "Hc{n}MinFlowTempDesired",
    "Hc{n}MinCoolTempDesired",
    "Hc{n}MinCoolingTempDesired",
]
