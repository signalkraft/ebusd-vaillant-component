"""Helper to build DeviceInfo for ebusd Vaillant entities."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DEFAULT_AREA, DEFAULT_MANUFACTURER, DOMAIN


def _find_parent_device_id(hass: HomeAssistant, parent_key: str) -> str | None:
    """Return the registry id of the parent system device, if registered."""
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, parent_key)})
    return device.id if device else None


def build_device_info(hass: HomeAssistant, config) -> DeviceInfo:
    """Return a DeviceInfo for *config*, grouping it under the correct HA device.

    All sub-devices (zones, circuits, hot water) link to the
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
        if "via_device_id" in DeviceInfo.__annotations__:
            # Newer HA: ``via_device`` is deprecated in favour of the registry id.
            # The parent is registered in async_setup_entry before platforms load.
            parent_id = _find_parent_device_id(hass, config.parent_key)
            if parent_id is not None:
                info["via_device_id"] = parent_id
        else:
            info["via_device"] = (DOMAIN, config.parent_key)
    return info
