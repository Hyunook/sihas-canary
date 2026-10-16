"""Set up the BCM-300 entry against an in-memory device and drive the new entities."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sihas.bcm import BcmState
from custom_components.sihas.const import DOMAIN

MAC = "a8:2b:d6:e7:d5:05"
NAME = "BCM-300 보일러제어기"
DEV = "bcm_300_boilreojeeogi"

# One live FC03 read (귀뚜라미 NCTR-60), every value matched the app screens.
LIVE = {
    0: 1, 1: 21, 2: 85, 3: 55, 4: 3, 5: 0, 6: 0, 7: 730, 8: 260, 9: 47, 10: 0,
    11: 0, 12: 0, 13: 0, 14: 0, 15: 1, 16: 61, 17: 0, 18: 30, 19: 10, 20: 8,
    21: 80, 22: 55, 23: 40, 24: 10, 25: 85, 26: 45, 27: 0, 28: 1205, 29: 4,
    50: 0xF2FE, 51: 0x4378, 52: 0, 62: 0,
}


class FakeBoiler:
    """Echoes FC06 writes into its register file like the device does."""

    def __init__(self, overrides: dict[int, int] | None = None) -> None:
        self.registers = [0] * 64
        for index, value in {**LIVE, **(overrides or {})}.items():
            self.registers[index] = value
        self.writes: list[tuple[int, int]] = []

    def read(self) -> BcmState:
        return BcmState(tuple(self.registers))

    def write(self, register: int, value: int) -> None:
        self.writes.append((int(register), value))
        self.registers[register] = value


async def _setup(hass: HomeAssistant, boiler: FakeBoiler) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title=NAME,
        data={"ip": "192.168.50.158", "mac": MAC, "type": "BCM", "cfg": 0, "name": NAME},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.sihas.bcm.BcmClient.read", side_effect=boiler.read),
        patch("custom_components.sihas.bcm.BcmClient.write", side_effect=boiler.write),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


@pytest.fixture
def boiler() -> FakeBoiler:
    return FakeBoiler()


@pytest.fixture
async def entry(hass, enable_custom_integrations, boiler):
    with (
        patch("custom_components.sihas.bcm.BcmClient.read", side_effect=boiler.read),
        patch("custom_components.sihas.bcm.BcmClient.write", side_effect=boiler.write),
    ):
        yield await _setup(hass, boiler)


def state(hass: HomeAssistant, entity_id: str) -> str:
    current = hass.states.get(entity_id)
    assert current is not None, entity_id
    return current.state


async def test_live_values(hass, entry):
    expected = {
        f"select.{DEV}_operation_mode": "실내",
        f"select.{DEV}_backlight": "자동 OFF",
        f"select.{DEV}_touch_lock": "잠금 해제",
        f"select.{DEV}_period_mode": "온도제어",
        f"select.{DEV}_heating_water_temperature": "겨울",
        f"number.{DEV}_timer_interval": "7.0",
        f"number.{DEV}_timer_run_time": "30",
        f"number.{DEV}_temperature_calibration": "-2.0",
        f"number.{DEV}_room_max": "40",
        f"number.{DEV}_room_min": "10",
        f"number.{DEV}_ondol_max": "85",
        f"number.{DEV}_ondol_min": "45",
        f"number.{DEV}_hot_water_max": "80",
        f"number.{DEV}_hot_water_min": "55",
        f"number.{DEV}_period_start_hour": "18",
        f"number.{DEV}_period_end_hour": "7",
        f"number.{DEV}_period_interval": "3",
        f"number.{DEV}_period_run_time": "30",
        f"switch.{DEV}_period_repeat": "off",
        f"switch.{DEV}_period_sun": "on",
        f"switch.{DEV}_period_sat": "on",
        f"switch.{DEV}_buzzer": "off",
        f"sensor.{DEV}_current_temperature": "26.0",
        f"sensor.{DEV}_ondol_current_temperature": "47",
        f"sensor.{DEV}_hot_water_current_temperature": "0",
        f"sensor.{DEV}_away_temperature": "8",
        f"sensor.{DEV}_error_code": "0",
        f"sensor.{DEV}_manufacturer": "귀뚜라미",
        f"sensor.{DEV}_controller_model": "NCTR-60(순간식)",
        f"binary_sensor.{DEV}_flame": "off",
        f"binary_sensor.{DEV}_water_refill": "off",
        f"binary_sensor.{DEV}_boiler_link": "on",
    }
    for entity_id, value in expected.items():
        assert state(hass, entity_id) == value, entity_id
    # 경동-only r29 meaning is not created for a 귀뚜라미 boiler.
    assert hass.states.get(f"select.{DEV}_heating_strength") is None
    attributes = hass.states.get(f"sensor.{DEV}_controller_model").attributes
    assert attributes["model_number"] == 61


async def test_climate_identity_is_unchanged(hass, entry):
    """The v1.8.0 climate unique_id was ``BCM-<mac>``; v2 keeps it."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("climate", DOMAIN, f"BCM-{MAC}")
    assert entity_id == f"climate.{DEV}"


async def _call(hass, domain, service, entity_id, **data):
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id, **data}, blocking=True
    )


async def test_period_end_hour_spans_two_registers(hass, entry, boiler):
    await _call(hass, "number", "set_value", f"number.{DEV}_period_end_hour", value=24)
    assert [register for register, _ in boiler.writes] == [50, 51]
    assert state(hass, f"number.{DEV}_period_end_hour") == "24"
    boiler.writes.clear()
    await _call(hass, "number", "set_value", f"number.{DEV}_period_end_hour", value=7)
    assert [register for register, _ in boiler.writes] == [51, 50]
    assert boiler.registers[50:52] == [0xF2FE, 0x4378]


async def test_period_fields(hass, entry, boiler):
    await _call(hass, "switch", "turn_on", f"switch.{DEV}_period_repeat")
    await _call(hass, "switch", "turn_off", f"switch.{DEV}_period_mon")
    await _call(hass, "select", "select_option", f"select.{DEV}_period_mode", option="예약제어")
    await _call(hass, "number", "set_value", f"number.{DEV}_period_interval", value=12)
    assert boiler.registers[50] == (0xF2FE | 0x0001) & ~0x0004
    assert boiler.registers[51] == (0x4378 & ~0x4000 & ~0x3F00) | (12 << 8)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "number", "set_value", f"number.{DEV}_period_run_time", value=64)


async def test_timer(hass, entry, boiler):
    await _call(hass, "number", "set_value", f"number.{DEV}_timer_interval", value=12)
    assert boiler.registers[7] == 1230
    await _call(hass, "number", "set_value", f"number.{DEV}_timer_run_time", value=10)
    assert boiler.registers[7] == 1210
    await _call(hass, "number", "set_value", f"number.{DEV}_timer_interval", value=0.5)
    assert boiler.registers[7] == 10
    writes = len(boiler.writes)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "number", "set_value", f"number.{DEV}_timer_run_time", value=30)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "number", "set_value", f"number.{DEV}_timer_run_time", value=7)
    assert len(boiler.writes) == writes


async def test_settings(hass, entry, boiler):
    await _call(
        hass, "number", "set_value", f"number.{DEV}_temperature_calibration", value=0.3
    )
    await _call(hass, "select", "select_option", f"select.{DEV}_backlight", option="항상 ON")
    await _call(hass, "select", "select_option", f"select.{DEV}_touch_lock", option="전체 잠금")
    await _call(
        hass,
        "select",
        "select_option",
        f"select.{DEV}_heating_water_temperature",
        option="봄",
    )
    await _call(hass, "switch", "turn_on", f"switch.{DEV}_buzzer")
    await _call(hass, "number", "set_value", f"number.{DEV}_room_max", value=45)
    assert boiler.writes == [(18, 53), (17, 3), (52, 2), (29, 2), (62, 1), (23, 45)]


async def test_limits_are_bounded_by_partner(hass, entry, boiler):
    with pytest.raises(ServiceValidationError):
        await _call(hass, "number", "set_value", f"number.{DEV}_room_max", value=10)
    with pytest.raises(ServiceValidationError):
        await _call(hass, "number", "set_value", f"number.{DEV}_hot_water_min", value=2)
    assert boiler.writes == []


async def test_step_hot_water_hides_limits(hass, enable_custom_integrations):
    boiler = FakeBoiler({3: 1, 21: 2, 22: 0, 15: 0, 16: 21, 29: 0})  # 경동 NR-20E, 3단 온수
    await _setup(hass, boiler)
    assert hass.states.get(f"number.{DEV}_hot_water_max") is None
    assert state(hass, f"select.{DEV}_hot_water_level") == "중온"
    assert state(hass, f"select.{DEV}_heating_strength") == "약"
    assert hass.states.get(f"select.{DEV}_heating_water_temperature") is None
    assert state(hass, f"sensor.{DEV}_controller_model") == "NR-20E"


async def test_translations_load(hass, entry):
    for language, name in (("ko", "백라이트"), ("en", "Backlight")):
        strings = await async_get_translations(hass, language, "entity", [DOMAIN])
        prefix = f"component.{DOMAIN}.entity"
        assert strings[f"{prefix}.select.bcm_backlight.name"] == name
        assert f"{prefix}.select.bcm_backlight.state.ON/OFF" in strings
        assert f"{prefix}.binary_sensor.bcm_boiler_link.name" in strings


async def test_operation_mode_bits_read_modify_write(hass, entry, boiler):
    """r4: b0 hot water, b1 heating, b2 ondol (else room), b3 bath (귀뚜라미 only)."""
    await _call(hass, "select", "select_option", f"select.{DEV}_operation_mode", option="온돌")
    assert boiler.registers[4] == 0b0111
    await _call(hass, "switch", "turn_on", f"switch.{DEV}_bath_mode")
    assert boiler.registers[4] == 0b1111
    await _call(hass, "select", "select_option", f"select.{DEV}_operation_mode", option="온수")
    assert boiler.registers[4] == 0b1101
    assert state(hass, f"select.{DEV}_operation_mode") == "온수"
    assert state(hass, f"switch.{DEV}_bath_mode") == "on"


async def test_two_step_hot_water(hass, enable_custom_integrations):
    boiler = FakeBoiler({3: 1, 21: 1, 22: 0})
    await _setup(hass, boiler)
    entity_id = f"select.{DEV}_hot_water_level"
    assert hass.states.get(entity_id).attributes["options"] == ["저온", "고온"]
    assert state(hass, entity_id) == "고온"
    assert hass.states.get(f"number.{DEV}_hot_water_temperature") is None
    assert hass.states.get(f"number.{DEV}_hot_water_min") is None
