"""The RWB1 Solar DTU (local MQTT) integration.

Talks to an RWB1 solar dongle directly over the user's own MQTT broker,
impersonating the Solar-of-Things cloud.  See rwb1_protocol_spec.md and the
README for the deployment model (point the dongle's DNS at your broker).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TLS,
    CONF_USERNAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TLS,
    DOMAIN,
)
from .coordinator import RWB1Coordinator
from .mqtt_client import RWB1Bridge

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    device_id = str(entry.data[CONF_DEVICE_ID])
    bridge = RWB1Bridge(
        hass.loop,
        host=entry.data[CONF_HOST],
        port=int(entry.data.get(CONF_PORT, DEFAULT_PORT)),
        device_id=device_id,
        username=entry.data.get(CONF_USERNAME) or device_id,
        password=entry.data.get(CONF_PASSWORD),
        tls=bool(entry.data.get(CONF_TLS, DEFAULT_TLS)),
    )

    coordinator = RWB1Coordinator(hass, bridge, device_id, DEFAULT_SCAN_INTERVAL)
    try:
        await coordinator.async_setup()
    except ConnectionError as err:
        # Surface as a retryable setup failure so HA retries automatically.
        from homeassistant.exceptions import ConfigEntryNotReady

        raise ConfigEntryNotReady(str(err)) from err

    # Connected to the broker; seed the coordinator (the dongle itself may not
    # be online yet, which is fine — entities populate as pushes arrive).
    await coordinator.async_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and tear down the MQTT bridge."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: RWB1Coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.bridge.async_stop()
    return unload_ok
