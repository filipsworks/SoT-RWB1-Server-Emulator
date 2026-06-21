"""Number platform — writable RWB1 setpoints (spec §6.3).

The dongle protocol has no reliable per-setting read-back (settings are
bit-packed inside shared HEEP frames we can't yet decode — spec §6.5), so these
controls are *optimistic*: they reflect the last value successfully written and
restore it across restarts.  A write only updates the displayed value once the
dongle ACKs it (a NAK raises, leaving the value unchanged).
"""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUMBER_SETTING_DEFINITIONS
from .coordinator import RWB1Coordinator
from .entity import RWB1Entity
from .mqtt_client import RWB1WriteError
from .protocol import format_value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RWB1Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RWB1Number(coordinator, definition)
        for definition in NUMBER_SETTING_DEFINITIONS
    )


class RWB1Number(RWB1Entity, RestoreNumber):
    """An optimistic, restore-backed numeric setpoint."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RWB1Coordinator, definition: dict) -> None:
        super().__init__(coordinator, f"number_{definition['key']}")
        self._channel = definition["channel"]
        self._fmt = definition["fmt"]
        self._step5 = definition.get("step5", False)
        self._attr_name = definition["name"]
        self._attr_icon = definition.get("icon")
        self._attr_native_min_value = definition["min"]
        self._attr_native_max_value = definition["max"]
        self._attr_native_step = definition["step"]
        if unit := definition.get("unit"):
            self._attr_native_unit_of_measurement = unit
        if dc := definition.get("device_class"):
            self._attr_device_class = NumberDeviceClass(dc)
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value

    async def async_set_native_value(self, value: float) -> None:
        try:
            value_str = format_value(self._fmt, value, step5=self._step5)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        try:
            await self.coordinator.bridge.async_write_setting(self._channel, value_str)
        except RWB1WriteError as err:
            raise HomeAssistantError(str(err)) from err
        self._attr_native_value = value
        self.async_write_ha_state()
