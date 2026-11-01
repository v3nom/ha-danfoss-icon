"""Base entities for Danfoss Icon."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import IconHouse, IconRoom
from .const import CONF_HOUSE_NAME, DOMAIN
from .coordinator import IconCoordinator


def master_device_info(coordinator: IconCoordinator) -> DeviceInfo:
    house = coordinator.house
    return DeviceInfo(
        identifiers={(DOMAIN, house.peer_id)},
        name=coordinator.config_entry.data.get(CONF_HOUSE_NAME) or "Danfoss Icon",
        manufacturer="Danfoss",
        model="Icon master controller",
    )


class IconHouseEntity(CoordinatorEntity[IconCoordinator]):
    """An entity belonging to the master controller."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IconCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.house.peer_id}_{key}"
        self._attr_device_info = master_device_info(coordinator)

    @property
    def house(self) -> IconHouse:
        return self.coordinator.house

    @property
    def available(self) -> bool:
        return super().available and self.house.connected


class IconRoomEntity(CoordinatorEntity[IconCoordinator]):
    """An entity belonging to one room thermostat."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IconCoordinator, number: int, key: str) -> None:
        super().__init__(coordinator)
        peer_id = coordinator.house.peer_id
        self._number = number
        self._attr_unique_id = room_unique_id(peer_id, number, key)
        name = self.room.name or f"Room {number + 1}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{peer_id}_room_{number}")},
            name=name,
            manufacturer="Danfoss",
            model="Icon room thermostat",
            suggested_area=name,
            via_device=(DOMAIN, peer_id),
        )

    @property
    def room(self) -> IconRoom:
        return self.coordinator.house.rooms[self._number]

    @property
    def available(self) -> bool:
        return super().available and self.room.available


def room_unique_id(peer_id: str, number: int, key: str) -> str:
    return f"{peer_id}_room_{number}_{key}"


# A factory yields (key, constructor) for the entities a room should have
# right now. Some entities (floor sensor, battery) only make sense once the
# room has reported the matching value, so this is re-checked on updates.
RoomEntityFactory = Callable[[IconRoom], Iterable[tuple[str, Callable[[], Entity]]]]


def setup_room_entities(
    coordinator: IconCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: RoomEntityFactory,
) -> None:
    """Add room entities now and whenever new rooms or values show up."""
    peer_id = coordinator.house.peer_id
    added: set[str] = set()

    @callback
    def _check() -> None:
        new: list[Entity] = []
        for room in coordinator.house.existing_rooms:
            for key, create in factory(room):
                unique_id = room_unique_id(peer_id, room.number, key)
                if unique_id not in added:
                    added.add(unique_id)
                    new.append(create())
        if new:
            async_add_entities(new)

    _check()
    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(_check))
