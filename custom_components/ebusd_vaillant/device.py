"""Helper to build DeviceInfo for ebusd Vaillant entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DEFAULT_AREA, DEFAULT_MANUFACTURER, DOMAIN


def build_device_info(config) -> DeviceInfo:
    """Return a DeviceInfo for *config*, grouping it under the correct HA device.

    All sub-devices (zones, circuits, hot water) set ``via_device`` to the
    parent system device (identified by the MQTT prefix alone).  The pressure
    sensor is placed directly on the parent, so its ``device_key == parent_key``.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, config.device_key)},
        name=config.device_name,
        manufacturer=config.manufacturer or DEFAULT_MANUFACTURER,
        suggested_area=DEFAULT_AREA,
    )
    if config.model:
        info["model"] = config.model
    if config.sw_version:
        info["sw_version"] = config.sw_version
    if config.hw_version:
        info["hw_version"] = config.hw_version
    if config.device_key != config.parent_key:
        info["via_device"] = (DOMAIN, config.parent_key)
    return info
