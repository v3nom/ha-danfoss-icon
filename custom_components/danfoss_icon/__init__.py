"""The Danfoss Icon integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import CannotConnect, IconHouse
from .const import CONF_PEER_ID, CONF_PRIVATE_KEY
from .coordinator import IconCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
]

type IconConfigEntry = ConfigEntry[IconCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: IconConfigEntry) -> bool:
    """Set up a Danfoss Icon house from a config entry."""
    house = IconHouse(entry.data[CONF_PRIVATE_KEY], entry.data[CONF_PEER_ID])
    coordinator = IconCoordinator(hass, entry, house)
    try:
        await coordinator.async_start()
    except CannotConnect as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_stop)

    async def _on_stop(_event: Event) -> None:
        await coordinator.async_stop()

    # Entries are not unloaded on shutdown, so close connections explicitly
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IconConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
