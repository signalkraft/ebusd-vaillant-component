"""Helper to build DeviceInfo for ebusd Vaillant entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
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


def move_time_program_entities(hass: HomeAssistant, entry: ConfigEntry, config) -> None:
    """Re-attach all entities of a time program to the device it is now assigned to.

    The Hot Water / Circulation programs are placed on the Hot Water device once
    it is known.  If an earlier discovery pass created them on the Controller
    (the water heater was not discovered yet), this moves them over.
    """
    ent_reg = er.async_get(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **build_device_info(config)
    )
    prefixes = (f"ebusd_time_program_{config.key}", f"ebusd_tp_edit_{config.key}_")
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent.unique_id.startswith(prefixes) and ent.device_id != device.id:
            ent_reg.async_update_entity(ent.entity_id, device_id=device.id)
