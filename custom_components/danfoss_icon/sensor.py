"""Sensors for Danfoss Icon rooms."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IconConfigEntry
from .api import IconRoom
from .climate import ROOM_MODE_NAMES
from .coordinator import IconCoordinator
from .entity import IconRoomEntity, setup_room_entities
from .icon import Room


@dataclass(frozen=True, kw_only=True)
class IconSensorDescription(SensorEntityDescription):
    """Describes a room sensor."""

    value_fn: Callable[[IconRoom], Any]
    # Only add the sensor once the room has reported a value for it, so
    # wired thermostats get no battery and air-only ones no floor sensor
    exists_fn: Callable[[IconRoom], bool] = lambda room: True


SENSORS: tuple[IconSensorDescription, ...] = (
    IconSensorDescription(
        key="room_temperature",
        translation_key="room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda room: room.get(Room.ROOM_TEMPERATURE),
        exists_fn=lambda room: room.get(Room.ROOM_TEMPERATURE) is not None,
    ),
    IconSensorDescription(
        key="floor_temperature",
        translation_key="floor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda room: room.get(Room.FLOOR_TEMPERATURE),
        exists_fn=lambda room: room.has_floor_sensor,
    ),
    IconSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.battery,
        exists_fn=lambda room: room.battery is not None,
    ),
    IconSensorDescription(
        key="schedule_period",
        translation_key="schedule_period",
        device_class=SensorDeviceClass.ENUM,
        options=list(ROOM_MODE_NAMES.values()),
        value_fn=lambda room: ROOM_MODE_NAMES.get(room.mode) if room.mode is not None else None,
        exists_fn=lambda room: room.mode is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up room sensors as their values show up."""
    coordinator = entry.runtime_data

    def factory(room: IconRoom):
        for description in SENSORS:
            if description.exists_fn(room):
                yield description.key, (
                    lambda d=description: IconSensor(coordinator, room.number, d)
                )

    setup_room_entities(coordinator, async_add_entities, factory)


class IconSensor(IconRoomEntity, SensorEntity):
    """A reading from a room thermostat."""

    entity_description: IconSensorDescription

    def __init__(
        self, coordinator: IconCoordinator, number: int, description: IconSensorDescription
    ) -> None:
        super().__init__(coordinator, number, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.room)
