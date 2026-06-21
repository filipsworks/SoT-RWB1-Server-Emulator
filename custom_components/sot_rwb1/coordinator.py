"""DataUpdateCoordinator wrapping the RWB1 MQTT bridge.

Telemetry is push-driven: the bridge calls back on every decoded message and we
forward that straight to entities via ``async_set_updated_data``.  The periodic
``_async_update_data`` tick exists only to (a) detect a dropped broker
connection and (b) nudge the dongle for a fresh dump so values don't go stale on
a quiet link between its ~6-minute auto-pushes.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .mqtt_client import RWB1Bridge

_LOGGER = logging.getLogger(__name__)


class RWB1Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Bridges push telemetry from one dongle into Home Assistant."""

    def __init__(
        self,
        hass: HomeAssistant,
        bridge: RWB1Bridge,
        device_id: str,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_id}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.bridge = bridge
        self.device_id = device_id

    async def async_setup(self) -> None:
        """Wire the push callback and open the broker connection."""
        self.bridge.set_update_callback(self._handle_push)
        await self.bridge.async_start()

    @callback
    def _handle_push(self, state: dict[str, Any]) -> None:
        """Receive a decoded state snapshot from the bridge (already on the loop)."""
        self.async_set_updated_data(state)

    async def _async_update_data(self) -> dict[str, Any]:
        if not self.bridge.connected:
            raise UpdateFailed("MQTT broker connection is down")
        # Fire-and-forget: the reply arrives as a push and refreshes state.
        self.bridge.request_dump()
        return dict(self.bridge.state)
