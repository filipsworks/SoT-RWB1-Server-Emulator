"""Switch platform — RWB1 boolean settings (spec §6.3).

Two encodings:
  * "prefix" — the boolean lives in the channel name: ``PE<suffix>`` enables,
    ``PD<suffix>`` disables (e.g. backlight ``PEx``/``PDx``).  Value is empty.
  * "digit"  — a fixed channel with an on/off digit value (e.g. ``PBEQE`` 1/0,
    ``PDAULC`` 01/00).

Optimistic + restore (no reliable read-back — spec §6.5).
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SWITCH_SETTING_DEFINITIONS
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
        RWB1Switch(coordinator, definition)
        for definition in SWITCH_SETTING_DEFINITIONS
    )


class RWB1Switch(RWB1Entity, SwitchEntity, RestoreEntity):
    """An optimistic, restore-backed boolean setting."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: RWB1Coordinator, definition: dict) -> None:
        super().__init__(coordinator, f"switch_{definition['key']}")
        self._def = definition
        self._attr_name = definition["name"]
        self._attr_icon = definition.get("icon")
        self._attr_is_on = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in ("on", "off"):
                self._attr_is_on = last.state == "on"

    def _command(self, turn_on: bool) -> tuple[str, str]:
        """Return (channel, value) for the requested state."""
        if self._def["kind"] == "prefix":
            prefix = "PE" if turn_on else "PD"
            return f"{prefix}{self._def['suffix']}", ""
        # "digit"
        return self._def["channel"], self._def["on"] if turn_on else self._def["off"]

    async def _async_set(self, turn_on: bool) -> None:
        channel, value = self._command(turn_on)
        try:
            await self.coordinator.bridge.async_write_setting(channel, value)
        except RWB1WriteError as err:
            raise HomeAssistantError(str(err)) from err
        self._attr_is_on = turn_on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)
