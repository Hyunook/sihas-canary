"""Register encodings of the BCM-300 extras (custom_components/sihas/bcm_codec.py).

Reference values come from one live read of a 귀뚜라미 NCTR-60 install, compared
against the SiHAS app screens at the same moment.
"""

import pytest

from custom_components.sihas.bcm_codec import (
    CONTROLLER_MODELS,
    PeriodRepeat,
    Reg,
    TimerLimits,
    controller_model_name,
    decode_calibration,
    decode_timer,
    encode_calibration,
    encode_timer,
    period_write_order,
)

R50, R51 = 0xF2FE, 0x4378  # app: off, every day, 18h→7h, every 3 h for 30 min, 온도제어


def test_period_repeat_decodes_live_reading():
    period = PeriodRepeat.from_registers(R50, R51)
    assert period == PeriodRepeat(
        enabled=False,
        days=(True,) * 7,
        start_hour=18,
        end_hour=7,
        run_minutes=30,
        interval_hours=3,
        temperature_control=True,
    )
    assert period.to_registers() == (R50, R51)


def test_period_repeat_day_bits_are_sunday_first():
    period = PeriodRepeat.from_registers(R50, R51).with_day("sun", False)
    assert period.to_registers()[0] == R50 & ~0x0002
    period = PeriodRepeat.from_registers(R50, R51).with_day("sat", False)
    assert period.to_registers()[0] == R50 & ~0x0080


def test_period_repeat_keeps_unused_bit():
    period = PeriodRepeat.from_registers(R50, R51 | 0x8000)
    assert period.with_changes(run_minutes=10).to_registers()[1] & 0x8000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_hour", -1),
        ("start_hour", 25),
        ("end_hour", 25),
        ("run_minutes", 0),
        ("run_minutes", 64),
        ("interval_hours", 0),
        ("interval_hours", 13),
        ("run_minutes", True),
        ("run_minutes", 1.5),
        ("unknown", 1),
    ],
)
def test_period_repeat_rejects_out_of_range(field, value):
    with pytest.raises(ValueError):
        PeriodRepeat.from_registers(R50, R51).with_changes(**{field: value})


def test_period_repeat_validates_only_changed_fields():
    blank = PeriodRepeat.from_registers(0, 0)  # interval 0 and run 0 are invalid inputs
    assert blank.with_changes(enabled=True).to_registers() == (1, 0)


def _end_hour(registers: dict[Reg, int]) -> int:
    return PeriodRepeat.from_registers(registers[Reg.PERIOD_A], registers[Reg.PERIOD_B]).end_hour


@pytest.mark.parametrize("old", range(25))
def test_end_hour_split_write_never_passes_24(old):
    current = PeriodRepeat.from_registers(R50, R51).with_changes(end_hour=old)
    for new in range(25):
        target = current.with_changes(end_hour=new)
        registers = dict(zip((Reg.PERIOD_A, Reg.PERIOD_B), current.to_registers(), strict=True))
        for register in period_write_order(current, target):
            registers[register] = target.to_registers()[0 if register == Reg.PERIOD_A else 1]
            assert 0 <= _end_hour(registers) <= 24, (old, new, _end_hour(registers))
        assert _end_hour(registers) == new


def test_end_hour_write_order():
    current = PeriodRepeat.from_registers(R50, R51)  # end 7
    assert period_write_order(current, current.with_changes(end_hour=24)) == [
        Reg.PERIOD_A,
        Reg.PERIOD_B,
    ]
    later = current.with_changes(end_hour=24)
    assert period_write_order(later, current) == [Reg.PERIOD_B, Reg.PERIOD_A]
    assert period_write_order(current, current.with_changes(end_hour=6)) == [Reg.PERIOD_A]
    assert period_write_order(current, current) == []


def test_timer_decodes_live_reading():
    assert decode_timer(730) == (7.0, 30)
    assert decode_timer(1210) == (12.0, 10)
    assert decode_timer(25) == (0.5, 25)  # hours 0 is the app's "0.5 시간"
    assert TimerLimits.from_register(1205) == TimerLimits(max_hours=12, minute_step=5)
    assert TimerLimits.from_register(1200) == TimerLimits(max_hours=12, minute_step=1)


@pytest.mark.parametrize(
    ("hours", "minutes", "raw"),
    [(7, 30, 730), (7.0, 30.0, 730), (0.5, 25, 25), (12, 60, 1260), (1, 55, 155)],
)
def test_timer_encodes(hours, minutes, raw):
    assert encode_timer(hours, minutes, TimerLimits(12, 5)) == raw


@pytest.mark.parametrize(
    ("hours", "minutes"),
    [
        (0.5, 30),  # run time must be shorter than the period
        (1, 60),
        (13, 5),  # above r28's 12 hours
        (0, 5),
        (1.5, 5),
        (2, 33),  # not a multiple of r28's 5 minute step
        (2, 0),
        (2, 65),
    ],
)
def test_timer_rejects(hours, minutes):
    with pytest.raises(ValueError):
        encode_timer(hours, minutes, TimerLimits(12, 5))


def test_calibration():
    assert decode_calibration(30) == -2.0
    assert decode_calibration(50) == 0.0
    assert encode_calibration(-2.0) == 30
    assert encode_calibration(5.0) == 100
    assert encode_calibration(-5) == 0
    assert encode_calibration(0.1 + 0.2) == 53  # float noise from the UI step
    for bad in (5.1, -5.1, 0.15):
        with pytest.raises(ValueError):
            encode_calibration(bad)


def test_controller_models_are_per_manufacturer():
    assert len(CONTROLLER_MODELS) == 70
    assert controller_model_name(1, 61) == "NCTR-60(순간식)"
    assert controller_model_name(0, 61) == "NR-60E"
    assert controller_model_name(1, 9999) is None
