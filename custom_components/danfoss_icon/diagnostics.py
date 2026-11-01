"""Diagnostics for Danfoss Icon."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import IconConfigEntry
from .icon import Global, MsgClass

_SERIAL = {
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SERIALNUMBER),
    (MsgClass.DEVICEGLOBAL, Global.SERIALNUMBER),
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IconConfigEntry
) -> dict[str, Any]:
    """Connection state and raw values, without the private key."""
    house = entry.runtime_data.house
    return {
        "grid_connected": house.grid_connected,
        "master_connected": house.connected,
        "master_peer_id": f"{house.peer_id[:8]}…",
        "last_error": house.last_error,
        "messages_received": house.messages_received,
        "house_values": {
            f"{cls}/{code}": "**REDACTED**" if (cls, code) in _SERIAL else value
            for (cls, code), value in house.values.items()
        },
        "rooms": [
            {
                "number": room.number,
                "name": room.name,
                "values": {code.name: value for code, value in room.values.items()},
            }
            for room in house.existing_rooms
        ],
    }
