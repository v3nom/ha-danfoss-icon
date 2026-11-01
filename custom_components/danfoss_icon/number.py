"""Temperature setpoints for Danfoss Icon rooms and the whole house."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IconConfigEntry
from .api import IconError, IconRoom
from .const import MAX_TEMP, MIN_TEMP, TEMP_STEP
from .coordinator import IconCoordinator
from .entity import IconHouseEntity, IconRoomEntity, setup_room_entities
from .icon import House, MsgClass, Room


@dataclass(frozen=True, kw_only=True)
class IconNumberDescription(NumberEntityDescription):
    """Describes a temperature setpoint."""

    code: int
    # Room setpoints are limited by the room's own min/max setting
    room_limits: bool = False


def _setpoint(key: str, code: int, room_limits: bool = False) -> IconNumberDescription:
    return IconNumberDescription(
        key=key,
        translation_key=key,
        code=code,
        room_limits=room_limits,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=MIN_TEMP,
        native_max_value=MAX_TEMP,
        native_step=TEMP_STEP,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    )


ROOM_NUMBERS: tuple[IconNumberDescription, ...] = (
    _setpoint("at_home_temperature", Room.SETPOINT_AT_HOME, room_limits=True),
    _setpoint("away_temperature", Room.SETPOINT_AWAY, room_limits=True),
    _setpoint("asleep_temperature", Room.SETPOINT_ASLEEP, room_limits=True),
    _setpoint("min_floor_temperature", Room.FLOOR_TEMPERATURE_MINIMUM),
    _setpoint("max_floor_temperature", Room.FLOOR_TEMPERATURE_MAXIMUM),
)

HOUSE_NUMBERS: tuple[IconNumberDescription, ...] = (
    _setpoint("vacation_temperature", House.VACATION_SETPOINT),
    _setpoint("pause_temperature", House.PAUSE_SETPOINT),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up setpoint entities."""
    coordinator = entry.runtime_data
    async_add_entities(IconHouseNumber(coordinator, d) for d in HOUSE_NUMBERS)

    def factory(room: IconRoom):
        for description in ROOM_NUMBERS:
            # Floor limits only exist on rooms that report them
            if room.get(Room(description.code)) is not None:
                yield description.key, (
                    lambda d=description: IconRoomNumber(coordinator, room.number, d)
                )

    setup_room_entities(coordinator, async_add_entities, factory)


class IconRoomNumber(IconRoomEntity, NumberEntity):
    """A temperature setting of one room."""

    entity_description: IconNumberDescription

    def __init__(
        self, coordinator: IconCoordinator, number: int, description: IconNumberDescription
    ) -> None:
        super().__init__(coordinator, number, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.room.get(Room(self.entity_description.code))

    @property
    def native_min_value(self) -> float:
        if self.entity_description.room_limits:
            value = self.room.get(Room.SETPOINT_MINIMUM)
            if value is not None:
                return value
        return MIN_TEMP

    @property
    def native_max_value(self) -> float:
        if self.entity_description.room_limits:
            value = self.room.get(Room.SETPOINT_MAXIMUM)
            if value is not None:
                return value
        return MAX_TEMP

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.room.set_value(Room(self.entity_description.code), value)
        except IconError as err:
            raise HomeAssistantError(str(err)) from err


class IconHouseNumber(IconHouseEntity, NumberEntity):
    """A house-wide temperature setting (vacation and pause)."""

    entity_description: IconNumberDescription

    def __init__(self, coordinator: IconCoordinator, description: IconNumberDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        return self.house.get(MsgClass.ALL_ROOMS, self.entity_description.code)

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.house.set_house_value(House(self.entity_description.code), value)
        except IconError as err:
            raise HomeAssistantError(str(err)) from err
