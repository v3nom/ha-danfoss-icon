"""Connection state of the master controller and its room thermostats."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IconConfigEntry
from .api import IconRoom
from .coordinator import IconCoordinator
from .entity import IconHouseEntity, IconRoomEntity, setup_room_entities
from .icon import Room


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up connection sensors."""
    coordinator = entry.runtime_data
    async_add_entities([IconCloudConnection(coordinator)])

    def factory(room: IconRoom):
        if room.get(Room.ERROR_CODE) is not None:
            yield "connection_lost", lambda: IconRoomConnectionLost(coordinator, room.number)

    setup_room_entities(coordinator, async_add_entities, factory)


class IconCloudConnection(IconHouseEntity, BinarySensorEntity):
    """Whether Home Assistant is connected to the master controller."""

    _attr_translation_key = "cloud_connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IconCoordinator) -> None:
        super().__init__(coordinator, "cloud_connection")

    @property
    def available(self) -> bool:
        # Reports the connection itself, so it is always available
        return True

    @property
    def is_on(self) -> bool:
        return self.house.connected


class IconRoomConnectionLost(IconRoomEntity, BinarySensorEntity):
    """The thermostat stopped talking to the master (often a flat battery)."""

    _attr_translation_key = "connection_lost"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: IconCoordinator, number: int) -> None:
        super().__init__(coordinator, number, "connection_lost")

    @property
    def is_on(self) -> bool | None:
        return self.room.communication_lost
