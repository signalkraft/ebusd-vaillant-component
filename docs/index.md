# Getting Started

This Home Assistant component connects to an ebusd instance through MQTT and auto-discovers
Vaillant-compatible entities as topics appear. No manual configuration of individual entities is required.

## Installation

Before installing, make sure you have these prerequisites:

- **ebusd** configured to publish Vaillant messages over MQTT, see [my quick install guide](ebusd.md) or [read the full offical guide](https://adapter.ebusd.eu/v5-c6/steps.en.html)
- **Home Assistant** with MQTT integration configured
- You know which topic ebusd is publishing MQTT messages on (`EBUSD_MQTTTOPIC`)

[Hardware Setup Guide](ebusd.md){ .md-button }

=== "HACS"

    1. Go to **HACS :material-arrow-right: Integrations :material-arrow-right: Custom repositories**
       ([HACS custom repositories docs](https://hacs.xyz/docs/faq/custom_repositories/))
    2. Add the repository URL: `https://github.com/signalkraft/ebusd-vaillant-component`
       with category **Integration**
    3. Click **Install** on the ebusd Vaillant integration
    4. Restart Home Assistant
    5. Add the integration through
       **Settings :material-arrow-right: Devices & services :material-arrow-right: Add integration
       :material-arrow-right: ebusd Vaillant**
       ([or click here](https://my.home-assistant.io/redirect/config_flow_start/?domain=ebusd_vaillant))
    6. Configure the MQTT topic prefix (default: `ebusd`) and display name

=== "Manual"

    1. Download the latest `ebusd_vaillant.zip` from the
       [releases page](https://github.com/signalkraft/ebusd-vaillant-component/releases)
    2. Unzip into your Home Assistant `custom_components` directory so the path
       becomes `custom_components/ebusd_vaillant/`
    3. Restart Home Assistant
    4. Add the integration through
       **Settings :material-arrow-right: Devices & services :material-arrow-right: Add integration
       :material-arrow-right: ebusd Vaillant**
       ([or click here](https://my.home-assistant.io/redirect/config_flow_start/?domain=ebusd_vaillant))
    5. Configure the MQTT topic prefix (default: `ebusd`) and display name

!!! info "Initial Startup"

    The component auto-discovers zones, water heater, and sensors on startup by sending discovery messages
    to ebusd for common device types. It may take a few minutes for all entities to be fully discovered.

## Comparison

|                   | ebusd-vaillant-component                                                         | [ebusd over MQTT](https://github.com/john30/ebusd/wiki/MQTT-integration)  | [mypyllant-component](https://github.com/signalkraft/mypyllant-component) |
|-------------------|----------------------------------------------------------------------------------|---------------------------------------------------------------------------|---------------------------------------------------------------------------|
| **Scope**         | Maps eBUS MQTT values to climate controls, partially replicates myVAILLANT app   | Direct mapping from eBUS data to HA entities                              | Matches myVAILLANT app structure & data availability                      |
| **Communication** | Local MQTT<br />Offline capable                                                  | Local MQTT<br />Offline capable                                           | Cloud API<br />No offline access                                          |
| **Requirememts**  | eBUS adapter, ebusd, MQTT broker, HACS                                           | eBUS adapter, ebusd, MQTT broker                                          | sensoNET / myVAILLANT gateway, myVAILLANT account, HACS                   |
| **Brands**        | Only tested on Vaillant                                                          | Any eBUS brand                                                            | Vaillant and some sub-brands                                              |
| **Limitations**   | Shows far less entities than ebusd over MQTT, but users can use both in parallel | Needs custom climate / hot water configuration to get functional controls | Relies on a somewhat temperamental cloud API, exposes less technical data |

## Tested Installation Types

* Vaillant aroTHERM plus heatpump & sensoCOMFORT VRC 720
* Have a different one? Check [data capture](data-capture.md) on how to create test data and get you rsystem supported

### MQTT

See the [MQTT Mapping](mapping.md) page for a complete reference of which topics
map to which Home Assistant controls.

## Development

See [Development](development.md) for instructions on setting up a local test environment, pre-commit hooks, and running tests.
