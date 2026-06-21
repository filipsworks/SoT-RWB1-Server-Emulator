"""Select platform — RWB1 single-digit enum settings (spec §6.3).

Optimistic + restore, for the same reason as the number platform (no reliable
settings read-back — spec §6.5).
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SELECT_SETTING_DEFINITIONS
from .coordinator import RWB1Coordinator
from .entity import RWB1Entity
from .mqtt_client import RWB1WriteError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RWB1Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RWB1Select(coordinator, definition)
        for definition in SELECT_SETTING_DEFINITIONS
    )


class RWB1Select(RWB1Entity, SelectEntity, RestoreEntity):
    """An optimistic, restore-backed enum setting."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RWB1Coordinator, definition: dict) -> None:
        super().__init__(coordinator, f"select_{definition['key']}")
        self._channel = definition["channel"]
        self._options_map: dict[str, str] = definition["options"]
        self._attr_name = definition["name"]
        self._attr_icon = definition.get("icon")
        self._attr_options = list(self._options_map)
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in self._options_map:
                self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        raw = self._options_map.get(option)
        if raw is None:
            raise HomeAssistantError(f"Unknown option {option!r}")
        try:
            await self.coordinator.bridge.async_write_setting(self._channel, raw)
        except RWB1WriteError as err:
            raise HomeAssistantError(str(err)) from err
        self._attr_current_option = option
        self.async_write_ha_state()
