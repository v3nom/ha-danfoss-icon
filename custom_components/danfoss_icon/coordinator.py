"""Push-based coordinator for a Danfoss Icon house."""

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import IconHouse
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class IconCoordinator(DataUpdateCoordinator[IconHouse]):
    """Holds one house; the master controller pushes its own updates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, house: IconHouse) -> None:
        # No update_interval: the master pushes changes over the grid.
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN)
        self.house = house
        self._remove_listener: Callable[[], None] | None = None
        self._device_info: tuple | None = None

    async def async_start(self) -> None:
        """Connect and start receiving pushed updates."""
        self._remove_listener = self.house.add_listener(self._handle_update)
        await self.house.start()
        self.async_set_updated_data(self.house)

    async def async_stop(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        await self.house.stop()

    @callback
    def _handle_update(self) -> None:
        self._update_master_device()
        self.async_set_updated_data(self.house)

    def _update_master_device(self) -> None:
        """Firmware and serial arrive after connecting; keep the registry current."""
        house = self.house
        info = (house.firmware, house.hardware, house.serial_number)
        if self._device_info == info or not any(info):
            return
        # get_or_create updates the existing device in place
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            identifiers={(DOMAIN, house.peer_id)},
            sw_version=info[0],
            hw_version=info[1],
            serial_number=info[2],
        )
        self._device_info = info
