"""Test data: a small Icon house."""

from __future__ import annotations

from custom_components.danfoss_icon.icon import Global, House, MsgClass, Room, RoomControl, RoomMode


def name(text: str) -> bytes:
    """Room and house names: length byte, then a fixed 32-byte field."""
    raw = text.encode()
    return bytes([32]) + raw + bytes(32 - len(raw))


def dec(value: float) -> bytes:
    return round(value * 100).to_bytes(2, "little", signed=True)


MISSING = (-0x8000).to_bytes(2, "little", signed=True)

LIVING = MsgClass.ROOM_FIRST + 0
BEDROOM = MsgClass.ROOM_FIRST + 2


def house_values() -> dict[tuple[int, int], bytes]:
    """Room 0 'Living room' (wired, floor sensor), room 2 'Bedroom' (battery, no floor)."""
    return {
        (MsgClass.ALL_ROOMS, House.HOUSE_NAME): name("Our House"),
        (MsgClass.ALL_ROOMS, House.VACATION_SETPOINT): dec(15),
        (MsgClass.ALL_ROOMS, House.PAUSE_SETPOINT): dec(7),
        (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SOFTWAREREVISION): bytes([0x01, 0x05]),
        (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SOFTWAREBUILDREVISION): (42).to_bytes(2, "little"),
        (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.HARDWAREREVISION): bytes([0x00, 0x02]),
        (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SERIALNUMBER): (123456).to_bytes(4, "little"),
        (LIVING, Room.NAME): name("Living room"),
        (LIVING, Room.ROOM_TEMPERATURE): dec(21.5),
        (LIVING, Room.FLOOR_TEMPERATURE): dec(24.25),
        (LIVING, Room.SETPOINT_AT_HOME): dec(22),
        (LIVING, Room.SETPOINT_AWAY): dec(18),
        (LIVING, Room.SETPOINT_ASLEEP): dec(19),
        (LIVING, Room.SETPOINT_MINIMUM): dec(5),
        (LIVING, Room.SETPOINT_MAXIMUM): dec(28),
        (LIVING, Room.FLOOR_TEMPERATURE_MINIMUM): dec(20),
        (LIVING, Room.FLOOR_TEMPERATURE_MAXIMUM): dec(29),
        (LIVING, Room.ROOM_MODE): bytes([RoomMode.AT_HOME]),
        (LIVING, Room.ROOM_CONTROL): bytes([RoomControl.AUTO]),
        (LIVING, Room.BATTERY_PERCENT): bytes([0]),
        (LIVING, Room.ERROR_CODE): bytes(2),
        (BEDROOM, Room.NAME): name("Bedroom"),
        (BEDROOM, Room.ROOM_TEMPERATURE): dec(19.75),
        (BEDROOM, Room.FLOOR_TEMPERATURE): MISSING,
        (BEDROOM, Room.SETPOINT_AT_HOME): dec(21),
        (BEDROOM, Room.SETPOINT_AWAY): dec(17),
        (BEDROOM, Room.SETPOINT_ASLEEP): dec(18.5),
        (BEDROOM, Room.ROOM_MODE): bytes([RoomMode.ASLEEP]),
        (BEDROOM, Room.ROOM_CONTROL): bytes([RoomControl.MANUAL]),
        (BEDROOM, Room.BATTERY_PERCENT): bytes([80]),
        (BEDROOM, Room.ERROR_CODE): (0x0101).to_bytes(2, "little"),
    }


# What the master pushes by itself right after connecting
INITIAL = [
    (MsgClass.ALL_ROOMS, House.VACATION_SETPOINT),
    (LIVING, Room.ROOM_TEMPERATURE),
    (BEDROOM, Room.ROOM_TEMPERATURE),
]
