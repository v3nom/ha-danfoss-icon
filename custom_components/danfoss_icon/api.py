"""High-level client for a Danfoss Icon house.

Pairing with the Icon app yields a key pair and the peer ID of the house's
master controller. The master is reached over one SDG tunnel and reports
every room on it; rooms are found by asking each of the 45 room slots for
its name.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
import re
import time
from typing import Any

from . import icon
from .icon import MsgClass, Room, RoomControl, RoomMode
from .sdg import Grid, SDGError, generate_private_key

_LOGGER = logging.getLogger(__name__)

RECONNECT_DELAY = 10
PING_AFTER = 15
STALE_AFTER = 30
WATCHDOG_INTERVAL = 5

_PEER_ID = re.compile(r"^[0-9a-f]{64}$")


class IconError(Exception):
    """Base error for the Icon client."""


class CannotConnect(IconError):
    """The SDG grid could not be reached."""


class InvalidOtp(IconError):
    """The one-time pairing code was rejected or expired."""


class NotIcon(IconError):
    """The shared house is not a Danfoss Icon house."""


@dataclass
class PairingResult:
    """Everything needed to talk to the house later."""

    private_key: str
    peer_id: str
    house_name: str


async def pair(
    otp: str, user_name: str, servers: list[tuple[str, int]] | None = None
) -> PairingResult:
    """Pair with the Icon app using a 'Share house' one-time code."""
    private_key = generate_private_key()
    grid = Grid(private_key, servers)
    try:
        await grid.connect()
    except (OSError, TimeoutError, SDGError) as err:
        raise CannotConnect(str(err)) from err
    try:
        try:
            phone_id = await grid.pair_remote(otp)
        except ValueError as err:
            raise InvalidOtp(str(err)) from err
        except (TimeoutError, SDGError) as err:
            # A wrong or expired code shows up as a refusal or a timeout
            raise InvalidOtp(str(err)) from err
        try:
            config = await grid.fetch_house_config(phone_id, user_name)
        except (OSError, TimeoutError, SDGError, ValueError) as err:
            raise CannotConnect(f"Could not receive the house from the app: {err}") from err
    finally:
        await grid.close()

    # The Icon app pads the master's peer ID with spaces
    peer_id = str(config.get("housePeerId") or "").strip().lower()
    if not _PEER_ID.match(peer_id):
        raise NotIcon("The shared house has no Icon master controller")
    return PairingResult(
        private_key=private_key.hex(),
        peer_id=peer_id,
        house_name=str(config.get("houseName") or "").strip() or "Danfoss Icon",
    )


class IconRoom:
    """One room (thermostat slot) on the master controller."""

    def __init__(self, house: IconHouse, number: int) -> None:
        self._house = house
        self.number = number
        self.values: dict[Room, Any] = {}

    @property
    def name(self) -> str:
        return self.values.get(Room.NAME) or ""

    @property
    def exists(self) -> bool:
        """Unused room slots report an empty name."""
        return bool(self.name)

    def get(self, code: Room) -> Any:
        return self.values.get(code)

    @property
    def mode(self) -> RoomMode | None:
        value = self.values.get(Room.ROOM_MODE)
        try:
            return RoomMode(value) if value is not None else None
        except ValueError:
            return None

    @property
    def manual(self) -> bool | None:
        value = self.values.get(Room.ROOM_CONTROL)
        return None if value is None else value == RoomControl.MANUAL

    @property
    def setpoint_code(self) -> Room:
        """The setpoint that drives the room in its current mode."""
        mode = self.mode
        if mode is RoomMode.AWAY:
            return Room.SETPOINT_AWAY
        if mode is RoomMode.ASLEEP:
            return Room.SETPOINT_ASLEEP
        return Room.SETPOINT_AT_HOME

    @property
    def target_temperature(self) -> float | None:
        return self.values.get(self.setpoint_code)

    @property
    def current_temperature(self) -> float | None:
        """Room air temperature; floor temperature for floor-only thermostats."""
        room = self.values.get(Room.ROOM_TEMPERATURE)
        return room if room is not None else self.values.get(Room.FLOOR_TEMPERATURE)

    @property
    def battery(self) -> int | None:
        """Battery level; wired thermostats report 0 or nothing."""
        value = self.values.get(Room.BATTERY_PERCENT)
        return value if value and value <= 100 else None

    @property
    def has_floor_sensor(self) -> bool:
        return self.values.get(Room.FLOOR_TEMPERATURE) is not None

    @property
    def communication_lost(self) -> bool | None:
        code = self.values.get(Room.ERROR_CODE)
        return None if code is None else code == icon.ROOM_ERROR_COMM_LOST

    @property
    def available(self) -> bool:
        return self._house.connected and self.exists

    async def set_value(self, code: Room, value: float) -> None:
        """Write a temperature setting of this room."""
        await self._house.write_decimal(icon.room_class(self.number), code, value)
        self._house.update_room(self, code, round(value * 100) / 100)

    async def set_target_temperature(self, temperature: float) -> None:
        """Change the setpoint used by the current mode."""
        await self.set_value(self.setpoint_code, temperature)

    async def set_manual(self, manual: bool) -> None:
        """Switch between manual (fixed setpoint) and schedule control."""
        control = RoomControl.MANUAL if manual else RoomControl.AUTO
        await self._house.write_byte(icon.room_class(self.number), Room.ROOM_CONTROL, control)
        self._house.update_room(self, Room.ROOM_CONTROL, int(control))


class IconHouse:
    """An Icon house: one grid connection and one tunnel to the master."""

    def __init__(
        self,
        private_key: str,
        peer_id: str,
        servers: list[tuple[str, int]] | None = None,
    ) -> None:
        self._private_key = bytes.fromhex(private_key)
        self.peer_id = peer_id
        self._servers = servers
        self._grid: Grid | None = None
        self._grid_lock = asyncio.Lock()
        self._tunnel = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_packet = 0.0
        self._listeners: list[Callable[[], None]] = []
        self._room_listeners: list[Callable[[IconRoom], None]] = []
        self._refreshed: set[int] = set()
        self.rooms = {number: IconRoom(self, number) for number in range(icon.MAX_ROOMS)}
        self.values: dict[tuple[int, int], Any] = {}
        self.connected = False
        self.last_error: str | None = None
        self.messages_received = 0

    # House values

    def get(self, msg_class: int, code: int) -> Any:
        return self.values.get((msg_class, code))

    @property
    def existing_rooms(self) -> list[IconRoom]:
        return [room for room in self.rooms.values() if room.exists]

    @property
    def house_name(self) -> str | None:
        return self.get(MsgClass.ALL_ROOMS, icon.House.HOUSE_NAME) or None

    @property
    def firmware(self) -> str | None:
        version = self.get(MsgClass.CLOUDIO_DEVICEGLOBAL, icon.Global.SOFTWAREREVISION)
        build = self.get(MsgClass.CLOUDIO_DEVICEGLOBAL, icon.Global.SOFTWAREBUILDREVISION)
        if version is None:
            return None
        return f"{version}.{build}" if build is not None else version

    @property
    def hardware(self) -> str | None:
        return self.get(MsgClass.CLOUDIO_DEVICEGLOBAL, icon.Global.HARDWAREREVISION)

    @property
    def serial_number(self) -> str | None:
        serial = self.get(MsgClass.CLOUDIO_DEVICEGLOBAL, icon.Global.SERIALNUMBER)
        if not serial:
            serial = self.get(MsgClass.DEVICEGLOBAL, icon.Global.SERIALNUMBER)
        return str(serial) if serial else None

    @property
    def grid_connected(self) -> bool:
        return self._grid is not None and self._grid.connected

    # Listeners

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Called whenever any value or the connection state changes."""
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def add_room_listener(self, callback: Callable[[IconRoom], None]) -> Callable[[], None]:
        """Called when a room shows up for the first time."""
        self._room_listeners.append(callback)
        return lambda: self._room_listeners.remove(callback)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:
                # A listener bug must never take down the connection
                _LOGGER.exception("Error in Danfoss Icon update listener")

    def _notify_room(self, room: IconRoom) -> None:
        for callback in list(self._room_listeners):
            try:
                callback(room)
            except Exception:
                _LOGGER.exception("Error in Danfoss Icon room listener")

    # Connection

    async def start(self) -> None:
        """Connect to the grid, then keep a tunnel to the master open."""
        try:
            await self.get_grid()
        except (OSError, TimeoutError, SDGError) as err:
            raise CannotConnect(str(err)) from err
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._close_tunnel()
        if self._grid:
            await self._grid.close()
            self._grid = None

    async def get_grid(self) -> Grid:
        async with self._grid_lock:
            if self._grid is None or not self._grid.connected:
                grid = Grid(self._private_key, self._servers)
                await grid.connect()
                self._grid = grid
            return self._grid

    def _close_tunnel(self) -> None:
        if self._tunnel:
            self._tunnel.close()
            self._tunnel = None
        if self.connected:
            self.connected = False
            self._notify()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                self.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.warning("Danfoss Icon master offline: %s", self.last_error)
            self._close_tunnel()
            await asyncio.sleep(RECONNECT_DELAY)

    async def _session(self) -> None:
        grid = await self.get_grid()
        self._tunnel = await grid.connect_to_peer(bytes.fromhex(self.peer_id), icon.PROTOCOL)
        self._last_packet = time.monotonic()
        self._refreshed.clear()
        self.connected = True
        self.last_error = None
        _LOGGER.info("Connected to Danfoss Icon master")
        self._notify()

        loop = asyncio.get_running_loop()
        watchdog = loop.create_task(self._watchdog())
        scan = loop.create_task(self._scan())
        first = True
        try:
            while True:
                data = await self._tunnel.recv()
                if first:
                    # The first message carries one garbage byte, a known quirk
                    data, first = data[1:], False
                await self._handle(data)
        finally:
            watchdog.cancel()
            scan.cancel()

    async def _scan(self) -> None:
        """Ask for house info and every room's name; named rooms exist."""
        try:
            for msg_class, code in icon.HOUSE_REFRESH:
                await self._send(icon.read_request(msg_class, code))
            for number in range(icon.MAX_ROOMS):
                await self._send(icon.read_request(icon.room_class(number), Room.NAME))
        except (OSError, IconError) as err:
            # The receive loop notices the broken tunnel and reconnects
            _LOGGER.debug("Room scan interrupted: %s", err)

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            idle = time.monotonic() - self._last_packet
            if idle > STALE_AFTER and self._tunnel:
                # Closing the tunnel ends the receive loop, which reconnects
                _LOGGER.warning("Danfoss Icon master silent for %ds, reconnecting", idle)
                self._tunnel.close()
                return
            if idle > PING_AFTER and self._tunnel:
                # Something small that every master answers
                try:
                    await self._send(
                        icon.read_request(MsgClass.ALL_ROOMS, icon.House.VACATION_SETPOINT)
                    )
                except (OSError, IconError) as err:
                    _LOGGER.debug("Ping failed: %s", err)

    async def _handle(self, data: bytes) -> None:
        self._last_packet = time.monotonic()
        self.messages_received += 1
        _LOGGER.debug("Master sent %s", data.hex())
        changed = False
        new_rooms: list[IconRoom] = []
        for msg_class, code, payload in icon.iter_packets(data):
            number = icon.room_number(msg_class)
            if number is not None:
                room = self.rooms[number]
                existed = room.exists
                if self._store_room(room, code, payload):
                    changed = True
                    if not existed and room.exists:
                        new_rooms.append(room)
            elif self._store_house(msg_class, code, payload):
                changed = True

        for room in new_rooms:
            _LOGGER.info("Found Danfoss Icon room %d: %s", room.number, room.name)
            self._notify_room(room)
        if changed:
            self._notify()
        for room in new_rooms:
            await self._refresh_room(room)

    def _store_room(self, room: IconRoom, code: int, payload: bytes) -> bool:
        try:
            known = Room(code)
        except ValueError:
            return False
        try:
            value = icon.decode_value(icon.ROOM_KINDS[known], payload)
        except (IndexError, ValueError):
            _LOGGER.debug("Bad payload for room %d %s: %s", room.number, known.name, payload.hex())
            return False
        if room.values.get(known) == value and known in room.values:
            return False
        room.values[known] = value
        return True

    def _store_house(self, msg_class: int, code: int, payload: bytes) -> bool:
        kind = icon.HOUSE_KINDS.get((msg_class, code))
        if kind is None:
            return False
        try:
            value = icon.decode_value(kind, payload)
        except (IndexError, ValueError):
            return False
        if self.values.get((msg_class, code)) == value and (msg_class, code) in self.values:
            return False
        self.values[(msg_class, code)] = value
        return True

    async def _refresh_room(self, room: IconRoom) -> None:
        if room.number in self._refreshed:
            return
        self._refreshed.add(room.number)
        msg_class = icon.room_class(room.number)
        for code in icon.ROOM_REFRESH:
            await self._send(icon.read_request(msg_class, code))

    def update_room(self, room: IconRoom, code: Room, value: Any) -> None:
        """Apply a value we just wrote, so the UI does not wait for the echo."""
        if room.values.get(code) != value:
            room.values[code] = value
            self._notify()

    def update_house(self, msg_class: int, code: int, value: Any) -> None:
        if self.values.get((msg_class, code)) != value:
            self.values[(msg_class, code)] = value
            self._notify()

    # Commands

    async def _send(self, data: bytes) -> None:
        if not self._tunnel or not self.connected:
            raise IconError("The Icon master controller is not connected")
        await self._tunnel.send(data)

    async def write_decimal(self, msg_class: int, code: int, value: float) -> None:
        await self._send(icon.write_decimal(msg_class, code, value))
        # Read it back so the master's view of the value wins
        await self._send(icon.read_request(msg_class, code))

    async def write_byte(self, msg_class: int, code: int, value: int) -> None:
        await self._send(icon.write_byte(msg_class, code, value))
        await self._send(icon.read_request(msg_class, code))

    async def set_house_value(self, code: icon.House, value: float) -> None:
        """Write a house-wide temperature (vacation or pause setpoint)."""
        await self.write_decimal(MsgClass.ALL_ROOMS, code, value)
        self.update_house(MsgClass.ALL_ROOMS, code, round(value * 100) / 100)
