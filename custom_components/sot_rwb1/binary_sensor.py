"""Binary sensor platform — boolean RWB1 telemetry + dongle online status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BINARY_SENSOR_DEFINITIONS, DOMAIN
from .coordinator import RWB1Coordinator
from .entity import RWB1Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RWB1Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [
        RWB1BinarySensor(coordinator, key, definition)
        for key, definition in BINARY_SENSOR_DEFINITIONS.items()
    ]
    entities.append(RWB1OnlineBinarySensor(coordinator))
    async_add_entities(entities)


class RWB1BinarySensor(RWB1Entity, BinarySensorEntity):
    """A decoded boolean telemetry value (e.g. solar charging switch)."""

    def __init__(
        self, coordinator: RWB1Coordinator, key: str, definition: dict
    ) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_name = definition["name"]
        self._attr_icon = definition.get("icon")
        if dc := definition.get("device_class"):
            self._attr_device_class = BinarySensorDeviceClass(dc)

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get(self._key)


class RWB1OnlineBinarySensor(RWB1Entity, BinarySensorEntity):
    """Whether the dongle is currently reporting to the broker."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = None

    def __init__(self, coordinator: RWB1Coordinator) -> None:
        super().__init__(coordinator, "online")
        self._attr_name = "Online"

    @property
    def is_on(self) -> bool | None:
        return bool((self.coordinator.data or {}).get("online"))
