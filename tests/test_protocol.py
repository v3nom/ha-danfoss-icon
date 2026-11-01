"""Tests for the SDG and Icon protocol layers."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

from nacl.bindings import crypto_secretbox
import pytest

from custom_components.danfoss_icon import icon
from custom_components.danfoss_icon.api import IconHouse, NotIcon, pair
from custom_components.danfoss_icon.icon import House, MsgClass, Room, RoomMode
from custom_components.danfoss_icon.sdg import generate_private_key, proto
from custom_components.danfoss_icon.sdg.crypto import xsalsa20_xor

from .fake_sdg import FakeGrid, FakeMaster, message
from .helpers import BEDROOM, INITIAL, LIVING, MISSING, dec, house_values, name


def test_xsalsa20_matches_libsodium() -> None:
    key, nonce = os.urandom(32), os.urandom(24)
    expected = crypto_secretbox(bytes(64), nonce, key)[16:]
    assert xsalsa20_xor(bytes(96), nonce, key)[32:] == expected


def test_proto_roundtrip() -> None:
    data = proto.encode([(1, proto.FIXED32, 0xF09D8C95), (2, proto.VARINT, 300), (5, proto.LENGTH, "x")])
    assert proto.decode(data) == {1: 0xF09D8C95, 2: 300, 5: b"x"}


def test_icon_parsing() -> None:
    data = (
        message(LIVING, Room.ROOM_TEMPERATURE, dec(21.5))
        + message(BEDROOM, Room.FLOOR_TEMPERATURE, MISSING)
        + message(LIVING, Room.NAME, name("Living room"))
        + message(MsgClass.ROOM_FIRST + 7, Room.NAME, bytes([32]) + bytes(32))
    )
    packets = list(icon.iter_packets(data + b"\x63\x00"))  # truncated tail dropped
    assert [(c, k) for c, k, _ in packets] == [
        (LIVING, Room.ROOM_TEMPERATURE),
        (BEDROOM, Room.FLOOR_TEMPERATURE),
        (LIVING, Room.NAME),
        (MsgClass.ROOM_FIRST + 7, Room.NAME),
    ]
    assert icon.decode_value(icon.DECIMAL, packets[0][2]) == 21.5
    # Missing sensors report 0x8000, which must not become -327.68
    assert icon.decode_value(icon.DECIMAL, packets[1][2]) is None
    assert icon.decode_value(icon.STRING, packets[2][2]) == "Living room"
    assert icon.decode_value(icon.STRING, packets[3][2]) == ""
    assert icon.room_number(MsgClass.ROOM_FIRST + 7) == 7
    assert icon.room_number(MsgClass.ALL_ROOMS) is None


def test_icon_requests() -> None:
    # read: prefix 1, class, code LE, length 0
    assert icon.read_request(LIVING, Room.NAME) == bytes([1, 99]) + (29250).to_bytes(2, "little") + b"\x00"
    # write: prefix 0, class, code LE, length 2, value*100 LE
    assert icon.write_decimal(BEDROOM, Room.SETPOINT_ASLEEP, 18.5) == bytes(
        [0, 101]
    ) + (1291).to_bytes(2, "little") + b"\x02" + (1850).to_bytes(2, "little")
    with pytest.raises(ValueError):
        icon.room_class(45)


async def test_pair_reads_icon_config() -> None:
    config = {"houseName": "Our House", "housePeerId": " " + "AB" * 32 + " ", "houseEditUsers": False}
    with (
        patch("custom_components.danfoss_icon.api.Grid.connect", AsyncMock()),
        patch("custom_components.danfoss_icon.api.Grid.close", AsyncMock()),
        patch("custom_components.danfoss_icon.api.Grid.pair_remote", AsyncMock(return_value=b"p" * 32)),
        patch("custom_components.danfoss_icon.api.Grid.fetch_house_config", AsyncMock(return_value=config)),
    ):
        result = await pair("123-456-789", "HA")
    assert result.peer_id == "ab" * 32
    assert result.house_name == "Our House"
    assert len(bytes.fromhex(result.private_key)) == 32


async def test_pair_rejects_devireg_house() -> None:
    config = {"houseName": "Flat", "rooms": [{"roomName": "Bath", "peerId": "cd" * 32}]}
    with (
        patch("custom_components.danfoss_icon.api.Grid.connect", AsyncMock()),
        patch("custom_components.danfoss_icon.api.Grid.close", AsyncMock()),
        patch("custom_components.danfoss_icon.api.Grid.pair_remote", AsyncMock(return_value=b"p" * 32)),
        patch("custom_components.danfoss_icon.api.Grid.fetch_house_config", AsyncMock(return_value=config)),
        pytest.raises(NotIcon),
    ):
        await pair("123-456-789", "HA")


async def _wait_for(predicate, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def test_house_end_to_end(socket_enabled) -> None:
    master = FakeMaster(house_values(), INITIAL)
    grid = FakeGrid(master)
    servers = await grid.start()
    house = IconHouse(generate_private_key().hex(), master.peer_id, servers)
    found: list[int] = []
    house.add_room_listener(lambda room: found.append(room.number))
    try:
        await house.start()
        await _wait_for(lambda: len(house.existing_rooms) == 2 and house.rooms[2].mode is not None)
        assert house.connected
        assert grid.calls[0][3] == b"dominion-1.0"
        assert sorted(found) == [0, 2]

        living, bedroom = house.rooms[0], house.rooms[2]
        assert living.name == "Living room"
        assert living.current_temperature == 21.5
        assert living.get(Room.FLOOR_TEMPERATURE) == 24.25
        assert living.has_floor_sensor
        assert living.battery is None  # wired thermostat reports 0
        assert living.target_temperature == 22  # at home
        assert living.manual is False
        assert living.communication_lost is False

        assert bedroom.mode is RoomMode.ASLEEP
        assert bedroom.target_temperature == 18.5
        assert not bedroom.has_floor_sensor
        assert bedroom.battery == 80
        assert bedroom.manual is True
        assert bedroom.communication_lost is True

        await _wait_for(lambda: house.firmware is not None and house.house_name is not None)
        assert house.house_name == "Our House"
        assert house.firmware == "5.1.42"
        assert house.serial_number == "123456"
        assert house.get(MsgClass.ALL_ROOMS, House.PAUSE_SETPOINT) == 7

        # Setting a temperature changes the active period's setpoint
        await bedroom.set_target_temperature(20)
        await asyncio.wait_for(master.got_write.wait(), 5)
        assert master.writes[-1] == (BEDROOM, Room.SETPOINT_ASLEEP, dec(20))
        assert bedroom.target_temperature == 20

        master.got_write.clear()
        await living.set_manual(True)
        await asyncio.wait_for(master.got_write.wait(), 5)
        assert master.writes[-1] == (LIVING, Room.ROOM_CONTROL, b"\x00")

        master.got_write.clear()
        await house.set_house_value(House.VACATION_SETPOINT, 16.5)
        await asyncio.wait_for(master.got_write.wait(), 5)
        assert master.writes[-1] == (MsgClass.ALL_ROOMS, House.VACATION_SETPOINT, dec(16.5))

        # Values pushed later are picked up
        await master.push(LIVING, Room.ROOM_MODE, bytes([RoomMode.AWAY]))
        await _wait_for(lambda: living.mode is RoomMode.AWAY)
        assert living.target_temperature == 18
    finally:
        await house.stop()
        await grid.stop()


async def test_house_reconnects(socket_enabled) -> None:
    master = FakeMaster(house_values(), INITIAL)
    grid = FakeGrid(master)
    servers = await grid.start()
    house = IconHouse(generate_private_key().hex(), master.peer_id, servers)
    try:
        with patch("custom_components.danfoss_icon.api.RECONNECT_DELAY", 0.1):
            await house.start()
            await _wait_for(lambda: house.connected and len(house.existing_rooms) == 2)
            away = icon.read_request(LIVING, Room.SETPOINT_AWAY)
            await _wait_for(lambda: any(away in data for data in master.received))
            before = sum(data.count(away) for data in master.received)
            master.tunnel.writer.close()
            await _wait_for(lambda: master.connections == 2 and house.connected)
            assert len(house.existing_rooms) == 2
            # Known rooms are refreshed again after reconnecting
            await _wait_for(lambda: sum(data.count(away) for data in master.received) > before)
    finally:
        await house.stop()
        await grid.stop()
