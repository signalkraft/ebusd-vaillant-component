"""Config flow for ebusd Vaillant."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import mqtt
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)

from .const import (
    CONF_AWAY_MODE_DURATION,
    CONF_MQTT_PREFIX,
    CONF_NAME,
    CONF_QUICK_VETO_DURATION,
    DEFAULT_AWAY_MODE_DURATION,
    DEFAULT_MQTT_PREFIX,
    DEFAULT_NAME,
    DEFAULT_QUICK_VETO_DURATION,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_MQTT_PREFIX, default=DEFAULT_MQTT_PREFIX): str,
    }
)


class EbusdVaillantConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            if not await mqtt.async_wait_for_mqtt_client(self.hass):
                errors["base"] = "mqtt_not_available"
            else:
                await self.async_set_unique_id(user_input[CONF_MQTT_PREFIX])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EbusdVaillantOptionsFlow(config_entry)


class EbusdVaillantOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(),
        )

    def _build_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Optional(
                    CONF_AWAY_MODE_DURATION,
                    default=self._config_entry.options.get(
                        CONF_AWAY_MODE_DURATION, DEFAULT_AWAY_MODE_DURATION
                    ),
                ): vol.Coerce(int),
                vol.Optional(
                    CONF_QUICK_VETO_DURATION,
                    default=self._config_entry.options.get(
                        CONF_QUICK_VETO_DURATION, DEFAULT_QUICK_VETO_DURATION
                    ),
                ): vol.Coerce(int),
            }
        )
