"""Button platform — RWB1 actions (clear fault, force refresh)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BUTTON_DEFINITIONS, DOMAIN
from .coordinator import RWB1Coordinator
from .entity import RWB1Entity
from .mqtt_client import RWB1WriteError

# FAULTC is a name-only write that triggers the clear-fault action (spec §6.3).
FAULT_CLEAR_CHANNEL = "FAULTC"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RWB1Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RWB1Button(coordinator, definition) for definition in BUTTON_DEFINITIONS
    )


class RWB1Button(RWB1Entity, ButtonEntity):
    """A one-shot dongle action."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RWB1Coordinator, definition: dict) -> None:
        super().__init__(coordinator, f"button_{definition['key']}")
        self._kind = definition["kind"]
        self._attr_name = definition["name"]
        self._attr_icon = definition.get("icon")

    async def async_press(self) -> None:
        if self._kind == "refresh":
            self.coordinator.bridge.request_dump()
            return
        # "fault"
        try:
            await self.coordinator.bridge.async_write_setting(FAULT_CLEAR_CHANNEL, "")
        except RWB1WriteError as err:
            raise HomeAssistantError(str(err)) from err
