"""Config flow for the RWB1 Solar DTU (local MQTT) integration.

A single setup step collects everything needed to reach the user's own broker
and the dongle behind it:

  * MQTT server (host + port)
  * DTU number  (the device id used in the ``dtu/<id>/...`` topics)
  * Password    (broker password; username defaults to the DTU number, matching
                 the dongle's own auth scheme — spec §1)

We validate by actually connecting to the broker.  The dongle itself does not
need to be online for setup to succeed — only the broker has to be reachable.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TLS,
    CONF_USERNAME,
    DEFAULT_PORT,
    DEFAULT_TLS,
    DOMAIN,
)
from .mqtt_client import RWB1Bridge

_LOGGER = logging.getLogger(__name__)


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Open a throwaway broker connection to verify host/port/credentials."""
    device_id = str(data[CONF_DEVICE_ID]).strip()
    bridge = RWB1Bridge(
        hass.loop,
        host=data[CONF_HOST],
        port=int(data.get(CONF_PORT, DEFAULT_PORT)),
        device_id=device_id,
        username=data.get(CONF_USERNAME) or device_id,
        password=data.get(CONF_PASSWORD),
        tls=bool(data.get(CONF_TLS, DEFAULT_TLS)),
    )
    try:
        await bridge.async_start()
    except ConnectionError as err:
        raise CannotConnect(str(err)) from err
    finally:
        await bridge.async_stop()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RWB1 Solar DTU."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = str(user_input[CONF_DEVICE_ID]).strip()
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            try:
                await _validate(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating RWB1 config")
                errors["base"] = "unknown"
            else:
                user_input[CONF_DEVICE_ID] = device_id
                return self.async_create_entry(
                    title=f"RWB1 DTU {device_id}", data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Required(CONF_DEVICE_ID): str,
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_TLS, default=DEFAULT_TLS): bool,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot reach the MQTT broker."""
