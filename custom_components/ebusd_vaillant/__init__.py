"""ebusd Vaillant integration."""

from __future__ import annotations

import asyncio
import json
import logging

import voluptuous as vol
import yaml
from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import entity_registry as er

from .const import CONF_MQTT_PREFIX, CONF_NAME, DEFAULT_MQTT_PREFIX, DEFAULT_NAME, DOMAIN
from .coordinator import EbusdCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["climate", "datetime", "sensor", "switch", "water_heater"]
SERVICE_DUMP_MQTT = "dump_mqtt_values"
SERVICE_RECORD_TOPIC = "record_topic_changes"


def _flatten_payload(payload):
    """Unwrap ebusd's nested value wrappers into plain scalars or dicts."""
    if not isinstance(payload, dict):
        return payload
    # Single-field {"value": {"value": X}} → X
    if set(payload.keys()) == {"value"}:
        inner = payload["value"]
        if isinstance(inner, dict) and "value" in inner:
            return inner["value"]
    # Multi-field {"field": {"value": X}, ...} → {field: X, ...}
    result = {}
    for k, v in payload.items():
        if isinstance(v, dict) and set(v.keys()) == {"value"}:
            result[k] = v["value"]
        else:
            result[k] = v
    return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    prefix = entry.data.get(CONF_MQTT_PREFIX, DEFAULT_MQTT_PREFIX)
    display_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    coordinator = EbusdCoordinator(hass, prefix, display_name, entry)
    await coordinator.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_DUMP_MQTT):

        async def _dump_mqtt(call: ServiceCall) -> dict:
            all_values: dict = {}
            for coord in hass.data.get(DOMAIN, {}).values():
                if isinstance(coord, EbusdCoordinator):
                    for device, msgs in coord.mqtt_values.items():
                        flat = {}
                        for msg_name, payload in msgs.items():
                            value = _flatten_payload(payload)
                            if value == "" or value is None:
                                continue
                            flat[msg_name] = value
                        if flat:
                            all_values[f"{coord._prefix}/{device}"] = flat
            yaml.dump(all_values, default_flow_style=False, allow_unicode=True, sort_keys=True)
            return all_values

        hass.services.async_register(
            DOMAIN,
            SERVICE_DUMP_MQTT,
            _dump_mqtt,
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RECORD_TOPIC):

        async def _record_topic_changes(call: ServiceCall) -> dict:
            timeout: int = call.data.get("timeout", 10)
            by_device: dict[str, dict] = {}

            async def _on_message(msg) -> None:
                parts = msg.topic.split("/")
                if len(parts) < 3:
                    return
                device, msg_name = parts[1], parts[2]
                try:
                    payload = json.loads(msg.payload)
                except (json.JSONDecodeError, ValueError):
                    payload = msg.payload
                value = _flatten_payload(payload)
                if value == "" or value is None:
                    return
                by_device.setdefault(device, {})[msg_name] = value

            unsubscribe = await mqtt.async_subscribe(hass, f"{prefix}/#", _on_message)
            try:
                await asyncio.sleep(timeout)
            finally:
                unsubscribe()

            return {f"{prefix}/{device}": msgs for device, msgs in by_device.items()}

        hass.services.async_register(
            DOMAIN,
            SERVICE_RECORD_TOPIC,
            _record_topic_changes,
            schema=vol.Schema(
                {
                    vol.Optional("timeout", default=10): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=3600)
                    ),
                }
            ),
            supports_response=SupportsResponse.ONLY,
        )

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        ent_reg.async_remove(ent.entity_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator:
        coordinator.async_stop()
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_DUMP_MQTT)
        hass.services.async_remove(DOMAIN, SERVICE_RECORD_TOPIC)
    return unloaded
