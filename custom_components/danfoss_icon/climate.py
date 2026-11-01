"""Climate entities for Danfoss Icon rooms."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IconConfigEntry
from .api import IconError, IconRoom
from .const import MAX_TEMP, MIN_TEMP, TEMP_STEP
from .coordinator import IconCoordinator
from .entity import IconRoomEntity, setup_room_entities
from .icon import Room, RoomMode

ROOM_MODE_NAMES = {
    RoomMode.AT_HOME: "at_home",
    RoomMode.AWAY: "away",
    RoomMode.ASLEEP: "asleep",
    RoomMode.FATAL: "fatal",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one climate entity per room."""
    coordinator = entry.runtime_data

    def factory(room: IconRoom):
        yield "climate", lambda: IconClimate(coordinator, room.number)

    setup_room_entities(coordinator, async_add_entities, factory)


class IconClimate(IconRoomEntity, ClimateEntity):
    """A room on the Icon master controller.

    Auto follows the room's weekly schedule (at home, away, asleep periods);
    Heat holds the room at a fixed temperature. Setting a temperature changes
    the setpoint of the period that is active right now.
    """

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT]
    _attr_target_temperature_step = TEMP_STEP
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, coordinator: IconCoordinator, number: int) -> None:
        super().__init__(coordinator, number, "climate")

    @property
    def current_temperature(self) -> float | None:
        return self.room.current_temperature

    @property
    def target_temperature(self) -> float | None:
        return self.room.target_temperature

    @property
    def min_temp(self) -> float:
        value = self.room.get(Room.SETPOINT_MINIMUM)
        return value if value is not None else MIN_TEMP

    @property
    def max_temp(self) -> float:
        value = self.room.get(Room.SETPOINT_MAXIMUM)
        return value if value is not None else MAX_TEMP

    @property
    def hvac_mode(self) -> HVACMode | None:
        manual = self.room.manual
        if manual is None:
            return None
        return HVACMode.HEAT if manual else HVACMode.AUTO

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mode = self.room.mode
        return {
            "schedule_period": ROOM_MODE_NAMES.get(mode) if mode is not None else None,
            "floor_temperature": self.room.get(Room.FLOOR_TEMPERATURE),
            "at_home_temperature": self.room.get(Room.SETPOINT_AT_HOME),
            "away_temperature": self.room.get(Room.SETPOINT_AWAY),
            "asleep_temperature": self.room.get(Room.SETPOINT_ASLEEP),
            "room_number": self.room.number + 1,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        try:
            await self.room.set_target_temperature(temperature)
        except IconError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        try:
            await self.room.set_manual(hvac_mode == HVACMode.HEAT)
        except IconError as err:
            raise HomeAssistantError(str(err)) from err
