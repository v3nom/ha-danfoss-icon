"""Tests for the config flow and entities inside Home Assistant."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_icon.api import InvalidOtp, NotIcon, PairingResult
from custom_components.danfoss_icon.const import DOMAIN
from custom_components.danfoss_icon.diagnostics import async_get_config_entry_diagnostics
from custom_components.danfoss_icon.icon import House, MsgClass, Room
from custom_components.danfoss_icon.sdg import generate_private_key
from homeassistant import config_entries
from homeassistant.components.climate import HVACMode
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from .fake_sdg import FakeGrid, FakeMaster
from .helpers import BEDROOM, INITIAL, LIVING, dec, house_values

PEER_ID = "ab" * 32


def _pairing(peer_id: str = PEER_ID) -> PairingResult:
    return PairingResult(private_key=generate_private_key().hex(), peer_id=peer_id, house_name="Our House")


async def _start_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result


async def test_config_flow_creates_house(hass: HomeAssistant) -> None:
    result = await _start_flow(hass)
    with (
        patch("custom_components.danfoss_icon.config_flow.pair", return_value=_pairing()) as pair,
        patch("custom_components.danfoss_icon.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp": "123-456-789", "user_name": "HA"}
        )
    assert pair.call_args.args == ("123-456-789", "HA")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Our House"
    assert result["data"]["peer_id"] == PEER_ID
    assert result["result"].unique_id == PEER_ID


async def test_config_flow_errors(hass: HomeAssistant) -> None:
    result = await _start_flow(hass)
    for error, expected in ((InvalidOtp, "invalid_otp"), (NotIcon, "not_icon"), (RuntimeError, "unknown")):
        with patch("custom_components.danfoss_icon.config_flow.pair", side_effect=error):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"otp": "1", "user_name": "HA"}
            )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": expected}


async def test_config_flow_already_configured(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=PEER_ID, data={}).add_to_hass(hass)
    result = await _start_flow(hass)
    with patch("custom_components.danfoss_icon.config_flow.pair", return_value=_pairing()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp": "123456789", "user_name": "HA"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_pairs_again(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=PEER_ID,
        data={"private_key": "00" * 32, "peer_id": PEER_ID, "house_name": "Our House"},
    )
    entry.add_to_hass(hass)
    new = _pairing()
    with (
        patch("custom_components.danfoss_icon.config_flow.pair", return_value=new),
        patch("custom_components.danfoss_icon.async_setup_entry", return_value=True),
    ):
        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp": "123456789", "user_name": "HA"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["private_key"] == new.private_key

    with patch("custom_components.danfoss_icon.config_flow.pair", return_value=_pairing("cd" * 32)):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"otp": "123456789", "user_name": "HA"}
        )
    assert result["reason"] == "wrong_house"


async def _wait_for(hass: HomeAssistant, predicate, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)
            await hass.async_block_till_done()


async def test_setup_creates_entities(hass: HomeAssistant, socket_enabled) -> None:
    master = FakeMaster(house_values(), INITIAL)
    grid = FakeGrid(master)
    servers = await grid.start()

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Our House",
        unique_id=master.peer_id,
        data={
            "private_key": generate_private_key().hex(),
            "peer_id": master.peer_id,
            "house_name": "Our House",
        },
    )
    entry.add_to_hass(hass)
    try:
        with patch("custom_components.danfoss_icon.sdg.grid.DANFOSS_SERVERS", servers):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await _wait_for(
                hass,
                lambda: hass.states.get("sensor.bedroom_battery") is not None
                and hass.states.get("number.living_room_minimum_floor_temperature") is not None,
            )

        living = hass.states.get("climate.living_room")
        assert living.state == HVACMode.AUTO
        assert living.attributes["current_temperature"] == 21.5
        assert living.attributes["temperature"] == 22
        assert living.attributes["max_temp"] == 28
        assert living.attributes["schedule_period"] == "at_home"

        # A manual refresh (update_entity) must not make entities unavailable
        assert await async_setup_component(hass, "homeassistant", {})
        await hass.services.async_call(
            "homeassistant", "update_entity", {"entity_id": "climate.living_room"}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get("climate.living_room").state == HVACMode.AUTO

        bedroom = hass.states.get("climate.bedroom")
        assert bedroom.state == HVACMode.HEAT
        assert bedroom.attributes["temperature"] == 18.5

        assert hass.states.get("sensor.living_room_floor_temperature").state == "24.25"
        assert hass.states.get("sensor.bedroom_battery").state == "80"
        assert hass.states.get("sensor.bedroom_schedule_period").state == "asleep"
        # Wired thermostat without battery and an air-only one without floor sensor
        assert hass.states.get("sensor.living_room_battery") is None
        assert hass.states.get("sensor.bedroom_floor_temperature") is None
        assert hass.states.get("number.bedroom_minimum_floor_temperature") is None
        assert hass.states.get("binary_sensor.bedroom_thermostat_connection_lost").state == STATE_ON
        assert hass.states.get("binary_sensor.our_house_cloud_connection").state == STATE_ON
        assert hass.states.get("number.our_house_vacation_temperature").state == "15.0"

        devices = dr.async_get(hass)
        master_device = devices.async_get_device({(DOMAIN, master.peer_id)})
        await _wait_for(hass, lambda: devices.async_get(master_device.id).sw_version is not None)
        assert devices.async_get(master_device.id).sw_version == "5.1.42"
        room_device = devices.async_get_device({(DOMAIN, f"{master.peer_id}_room_2")})
        assert room_device.name == "Bedroom"
        assert room_device.via_device_id == master_device.id

        # Changing the temperature writes the active period's setpoint
        await hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": "climate.bedroom", "temperature": 20}, blocking=True,
        )
        await asyncio.wait_for(master.got_write.wait(), 5)
        assert master.writes[-1] == (BEDROOM, Room.SETPOINT_ASLEEP, dec(20))
        assert hass.states.get("climate.bedroom").attributes["temperature"] == 20

        master.got_write.clear()
        await hass.services.async_call(
            "climate", "set_hvac_mode",
            {"entity_id": "climate.living_room", "hvac_mode": "heat"}, blocking=True,
        )
        await asyncio.wait_for(master.got_write.wait(), 5)
        assert master.writes[-1] == (LIVING, Room.ROOM_CONTROL, b"\x00")
        assert hass.states.get("climate.living_room").state == HVACMode.HEAT

        master.got_write.clear()
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": "number.our_house_pause_temperature", "value": 8}, blocking=True,
        )
        await asyncio.wait_for(master.got_write.wait(), 5)
        assert master.writes[-1] == (MsgClass.ALL_ROOMS, House.PAUSE_SETPOINT, dec(8))

        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert "private_key" not in str(diagnostics)
        assert entry.data["private_key"] not in str(diagnostics)
        assert [room["name"] for room in diagnostics["rooms"]] == ["Living room", "Bedroom"]

        entities = er.async_get(hass)
        assert entities.async_get("climate.living_room").unique_id == f"{master.peer_id}_room_0_climate"

        assert await hass.config_entries.async_unload(entry.entry_id)
    finally:
        await grid.stop()
