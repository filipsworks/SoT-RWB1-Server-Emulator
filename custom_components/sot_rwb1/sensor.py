"""Sensor platform — decoded RWB1 telemetry (spec §5)."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SENSOR_DEFINITIONS
from .coordinator import RWB1Coordinator
from .entity import RWB1Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RWB1Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RWB1Sensor(coordinator, key, definition)
        for key, definition in SENSOR_DEFINITIONS.items()
    )


class RWB1Sensor(RWB1Entity, SensorEntity):
    """One decoded telemetry value."""

    def __init__(
        self, coordinator: RWB1Coordinator, key: str, definition: dict
    ) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_name = definition["name"]
        self._attr_icon = definition.get("icon")

        unit = definition.get("unit")
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if dc := definition.get("device_class"):
            self._attr_device_class = SensorDeviceClass(dc)
        if sc := definition.get("state_class"):
            self._attr_state_class = SensorStateClass(sc)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._key)
