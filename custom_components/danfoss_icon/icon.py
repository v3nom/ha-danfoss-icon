"""Danfoss Icon application protocol ("dominion-1.0").

The Icon master controller speaks the same message format as DEVIreg Smart:
each message is 1 byte class, 2 bytes code (little-endian), 1 byte payload
length, then the payload. Several messages may arrive merged in one packet.
Outgoing messages carry one extra leading byte: 0 to write a value, 1 to
request it.

On the Icon the class says *what* a value belongs to: rooms use classes
99..143 (room number = class - 99), house-wide settings use class 190.
Codes and classes come from the openHAB Danfoss binding by Pavel Fedin
(Sonic-Amiga) and the ha-danfoss add-on by soundvibe.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import IntEnum

PROTOCOL = "dominion-1.0"
HEADER_SIZE = 4
MAX_ROOMS = 45


class MsgClass(IntEnum):
    """Message classes the integration uses."""

    CLOUDIO_DEVICEGLOBAL = 0
    MDG = 3
    DEVICEGLOBAL = 50
    ROOM_FIRST = 99
    ROOM_LAST = 143
    ALL_ROOMS = 190


class Global(IntEnum):
    """Codes in the device-global classes (0 and 50)."""

    SOFTWAREBUILDREVISION = 8
    SERIALNUMBER = 22
    HARDWAREREVISION = 34
    SOFTWAREREVISION = 35


class Mdg(IntEnum):
    """Codes in the MDG (cloud connection) class."""

    CONNECTION_COUNT = 30470


class House(IntEnum):
    """Codes in the ALL_ROOMS class."""

    VACATION_SETPOINT = 2955
    HOUSE_NAME = 29251
    PAUSE_SETPOINT = 29253


class Room(IntEnum):
    """Codes in the per-room classes."""

    ROOM_TEMPERATURE = 768
    FLOOR_TEMPERATURE = 772
    BATTERY_PERCENT = 783
    ERROR_CODE = 1008
    SETPOINT_MINIMUM = 1287
    SETPOINT_MAXIMUM = 1288
    SETPOINT_AT_HOME = 1289
    SETPOINT_AWAY = 1290
    SETPOINT_ASLEEP = 1291
    FLOOR_TEMPERATURE_MINIMUM = 1292
    FLOOR_TEMPERATURE_MAXIMUM = 1293
    ROOM_MODE = 4106
    ROOM_CONTROL = 4107
    HEATING_COOLING_STATE = 4115
    NAME = 29250


class RoomMode(IntEnum):
    """Values of Room.ROOM_MODE: which part of the schedule is active."""

    AT_HOME = 0
    AWAY = 1
    ASLEEP = 2
    FATAL = 3


class RoomControl(IntEnum):
    """Values of Room.ROOM_CONTROL."""

    MANUAL = 0
    AUTO = 1
    SCHEDULE = 20


# Room.ERROR_CODE: the thermostat stopped talking to the master
ROOM_ERROR_COMM_LOST = 0x0101

# Value kinds
DECIMAL = "decimal"
BYTE = "byte"
SHORT = "short"
UINT = "uint"
VERSION = "version"
STRING = "string"

ROOM_KINDS: dict[Room, str] = {
    Room.ROOM_TEMPERATURE: DECIMAL,
    Room.FLOOR_TEMPERATURE: DECIMAL,
    Room.BATTERY_PERCENT: BYTE,
    Room.ERROR_CODE: SHORT,
    Room.SETPOINT_MINIMUM: DECIMAL,
    Room.SETPOINT_MAXIMUM: DECIMAL,
    Room.SETPOINT_AT_HOME: DECIMAL,
    Room.SETPOINT_AWAY: DECIMAL,
    Room.SETPOINT_ASLEEP: DECIMAL,
    Room.FLOOR_TEMPERATURE_MINIMUM: DECIMAL,
    Room.FLOOR_TEMPERATURE_MAXIMUM: DECIMAL,
    Room.ROOM_MODE: BYTE,
    Room.ROOM_CONTROL: BYTE,
    Room.HEATING_COOLING_STATE: BYTE,
    Room.NAME: STRING,
}

HOUSE_KINDS: dict[tuple[int, int], str] = {
    (MsgClass.ALL_ROOMS, House.VACATION_SETPOINT): DECIMAL,
    (MsgClass.ALL_ROOMS, House.PAUSE_SETPOINT): DECIMAL,
    (MsgClass.ALL_ROOMS, House.HOUSE_NAME): STRING,
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SOFTWAREBUILDREVISION): SHORT,
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SERIALNUMBER): UINT,
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.HARDWAREREVISION): VERSION,
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SOFTWAREREVISION): VERSION,
    (MsgClass.DEVICEGLOBAL, Global.SERIALNUMBER): UINT,
    (MsgClass.MDG, Mdg.CONNECTION_COUNT): BYTE,
}

# Values requested from each room once its name shows up. The master also
# pushes them on its own, so this only fills gaps.
ROOM_REFRESH: tuple[Room, ...] = (
    Room.ROOM_TEMPERATURE,
    Room.FLOOR_TEMPERATURE,
    Room.SETPOINT_AT_HOME,
    Room.SETPOINT_AWAY,
    Room.SETPOINT_ASLEEP,
    Room.SETPOINT_MINIMUM,
    Room.SETPOINT_MAXIMUM,
    Room.FLOOR_TEMPERATURE_MINIMUM,
    Room.FLOOR_TEMPERATURE_MAXIMUM,
    Room.ROOM_MODE,
    Room.ROOM_CONTROL,
    Room.BATTERY_PERCENT,
    Room.ERROR_CODE,
)

HOUSE_REFRESH: tuple[tuple[int, int], ...] = (
    (MsgClass.ALL_ROOMS, House.HOUSE_NAME),
    (MsgClass.ALL_ROOMS, House.VACATION_SETPOINT),
    (MsgClass.ALL_ROOMS, House.PAUSE_SETPOINT),
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SOFTWAREREVISION),
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SOFTWAREBUILDREVISION),
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.HARDWAREREVISION),
    (MsgClass.CLOUDIO_DEVICEGLOBAL, Global.SERIALNUMBER),
)


def room_class(number: int) -> int:
    """Message class of a room."""
    if not 0 <= number < MAX_ROOMS:
        raise ValueError(f"Room number {number} out of range")
    return MsgClass.ROOM_FIRST + number


def room_number(msg_class: int) -> int | None:
    """Room number of a message class, or None if it is not a room class."""
    if MsgClass.ROOM_FIRST <= msg_class <= MsgClass.ROOM_LAST:
        return msg_class - MsgClass.ROOM_FIRST
    return None


def iter_packets(data: bytes) -> Iterator[tuple[int, int, bytes]]:
    """Split received data into (class, code, payload); many may be merged."""
    pos = 0
    while len(data) - pos >= HEADER_SIZE:
        msg_class = data[pos]
        code = int.from_bytes(data[pos + 1 : pos + 3], "little")
        length = data[pos + 3]
        end = pos + HEADER_SIZE + length
        if end > len(data):
            break  # Malformed tail; drop it
        yield msg_class, code, data[pos + HEADER_SIZE : end]
        pos = end


def decode_value(kind: str, payload: bytes) -> float | int | str | None:
    """Decode a payload of a known kind."""
    if kind == DECIMAL:
        raw = int.from_bytes(payload[:2], "little", signed=True)
        # Missing sensors report 0x8000
        return None if raw == -0x8000 else raw / 100
    if kind == BYTE:
        return payload[0]
    if kind == SHORT:
        return int.from_bytes(payload[:2], "little")
    if kind == UINT:
        return int.from_bytes(payload[:4], "little")
    if kind == VERSION:
        raw = int.from_bytes(payload[:2], "little")
        return f"{raw >> 8}.{raw & 0xFF}"
    if kind == STRING:
        # Length byte, then text. Never-set strings are all zeros.
        text = payload[1 : 1 + payload[0]].split(b"\x00", 1)[0]
        return text.decode(errors="replace").strip()
    raise ValueError(kind)


def _message(prefix: int, msg_class: int, code: int, payload: bytes) -> bytes:
    return (
        bytes([prefix, msg_class])
        + int(code).to_bytes(2, "little")
        + bytes([len(payload)])
        + payload
    )


def read_request(msg_class: int, code: int) -> bytes:
    """Ask the master to report a value."""
    return _message(1, msg_class, code, b"")


def write_decimal(msg_class: int, code: int, value: float) -> bytes:
    """Set a temperature-like value (fixed point, two decimals)."""
    return _message(0, msg_class, code, round(value * 100).to_bytes(2, "little", signed=True))


def write_byte(msg_class: int, code: int, value: int) -> bytes:
    """Set a one-byte value."""
    return _message(0, msg_class, code, bytes([value & 0xFF]))
