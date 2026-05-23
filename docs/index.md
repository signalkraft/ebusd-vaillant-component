# ebusd Vaillant

This Home Assistant component connects to an ebusd instance through MQTT and auto-discovers
Vaillant-compatible entities as topics appear. No manual configuration of individual entities is required.

## Supported Entities

| Entity type      | Description                                                                                             |
|------------------|---------------------------------------------------------------------------------------------------------|
| **Climate**      | Up to 4 heating zones (Z1-Z4) with mode, temperature control, holiday schedules, and quick veto (boost) |
| **Water Heater** | Hot water circuit control (HWC) with mode, target temperature, and current temperature                  |
| **Sensor**       | Water pressure (bar)                                                                                    |

## Tested Installation Types

* Vaillant aroTHERM plus heatpump & sensoCOMFORT VRC 720
* Have a different one? Check [data capture](data-capture.md) on how to create test data and get you rsystem supported

## Installation

Before installing, make sure you have these prerequisites:

- **ebusd** configured to publish Vaillant messages over MQTT, see [my quick install guide](ebusd.md) or [read the full offical guide](https://adapter.ebusd.eu/v5-c6/steps.en.html)
- **Home Assistant** with MQTT integration configured
- You know which topic ebusd is publishing MQTT messages on (`EBUSD_MQTTTOPIC`)

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

!!! note

    The component auto-discovers zones, water heater, and sensors as ebusd
    publishes their topics. Entities may take a few minutes to appear in
    Home Assistant after adding the integration.

### MQTT

See the [MQTT Mapping](mapping.md) page for a complete reference of which topics
map to which Home Assistant controls.

## Development

A `docker-compose.yml` is provided to spin up a test Home Assistant instance
with the component pre-installed.

1. Copy the environment template:
   ```bash
   cp docker/.env.sample docker/.env
   ```
2. Edit `docker/.env` and set your MQTT broker address and port. ebusd needs to be running and publishing already, it's not included in this setup.
3. Start the container:
   ```bash
   docker compose up -d
   ```
4. Access Home Assistant at [http://localhost:8123](http://localhost:8123) and log in with `test` / `test`.
5. You should find [devices in the integration](https://my.home-assistant.io/redirect/integration/?domain=ebusd_vaillant)
