"""Shared base entity for the RWB1 integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RWB1Coordinator


class RWB1Entity(CoordinatorEntity[RWB1Coordinator]):
    """Common device wiring for every RWB1 entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RWB1Coordinator, key: str) -> None:
        super().__init__(coordinator)
        self._device_id = coordinator.device_id
        self._attr_unique_id = f"{DOMAIN}_{self._device_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        identity = (self.coordinator.data or {}).get("identity") or {}
        mac = identity.get("mac")
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=f"RWB1 DTU {self._device_id}",
            manufacturer="Easun / Solar of Things",
            model=identity.get("model") or "RWB1",
            sw_version=identity.get("firmware"),
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
        )
