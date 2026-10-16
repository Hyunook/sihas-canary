"""Pure BCM-300 register encodings for the settings the SiHAS app exposes.

Kept free of Home Assistant imports so the bit layouts can be unit tested.
Layouts were taken from the SiHAS app (com.sihas_new_app 1.8.14) and checked
against one live FC03 read; the commit that added this file lists the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum


class Reg(IntEnum):
    TIMER_TIME = 7
    ONDOL_TEMPERATURE = 9
    HOT_WATER_TEMPERATURE = 10
    FLAME = 11
    ERROR_CODE = 12
    WATER_REFILL = 13
    BOILER_LINK = 14
    MANUFACTURER = 15
    CONTROLLER_MODEL = 16
    BACKLIGHT = 17
    CALIBRATION = 18
    AWAY_TEMPERATURE = 20
    HOT_WATER_MAX = 21
    HOT_WATER_MIN = 22
    ROOM_MAX = 23
    ROOM_MIN = 24
    ONDOL_MAX = 25
    ONDOL_MIN = 26
    TIMER_LIMIT = 28
    SEASON = 29
    PERIOD_A = 50
    PERIOD_B = 51
    TOUCH_LOCK = 52
    BUZZER = 62


MANUFACTURERS: dict[int, str] = {
    0: "경동",
    1: "귀뚜라미",
    2: "대성",
    3: "린나이",
    4: "기타1",
    5: "기타2",
    6: "기타3",
    7: "테스트 데모",
}
KYUNGDONG = 0
KITURAMI = 1

# Model numbers repeat across makers (61 is NR-60E for 경동, NCTR-60 for 귀뚜라미).
CONTROLLER_MODELS: dict[tuple[int, int], str] = {
    (0, 5): "NR-5S/FR-5",
    (0, 6): "NR-20M/FR-6",
    (0, 10): "NR-10E",
    (0, 15): "NR-15SB",
    (0, 16): "NR-15SW",
    (0, 20): "NR-20S/20D(w/BCM-W35)",
    (0, 21): "NR-20E",
    (0, 22): "NR-20H",
    (0, 25): "NR-25S",
    (0, 30): "NR-30S",
    (0, 35): "NR-35E",
    (0, 40): "NR-40S/D",
    (0, 41): "NR-40E",
    (0, 61): "NR-60E",
    (0, 63): "NR-63S",
    (1, 10): "CTR-10WIFI",
    (1, 11): "NCTR-10WIFI",
    (1, 51): "NCTR-50",
    (1, 53): "NCTR-50N",
    (1, 61): "NCTR-60(순간식)",
    (1, 66): "CTR-65WIFI",
    (1, 71): "NCTR-70(저탕식)",
    (1, 1500): "CTR-1500",
    (1, 2000): "HOT-2000",
    (1, 3000): "CTR-3000",
    (1, 5000): "CTR-5000",
    (1, 5001): "NCTR-5000",
    (1, 5500): "CTR-5500",
    (1, 5700): "CTR-5700+(순간식)",
    (1, 5710): "CTR-5700+(저탕식)",
    (1, 6001): "NCTR_6000",
    (1, 6101): "NCTR_6100",
    (1, 7000): "CTR-7000",
    (1, 8000): "CTR-8000",
    (2, 11): "DCR-11",
    (2, 21): "DCR-21",
    (2, 100): "DR-100",
    (2, 120): "DSR-120(B)",
    (2, 200): "DSR-200",
    (2, 220): "DSR-220(B)",
    (2, 225): "DSR-225(E/B)",
    (2, 240): "DR-240(S/N)",
    (2, 371): "DSR-371",
    (2, 500): "DSR-500",
    (2, 501): "DR-500",
    (2, 550): "DSR-550",
    (2, 730): "DSR-730",
    (2, 740): "DR-740",
    (2, 900): "DR-900S",
    (2, 910): "DR-910W",
    (3, 28): "RBMC-28",
    (3, 32): "RBMC-32",
    (3, 35): "RBMC-35",
    (3, 36): "RBMC-36",
    (3, 38): "RBMC-38",
    (3, 40): "RBMC-40",
    (3, 41): "RBMC-41",
    (3, 43): "RBMC-43",
    (3, 44): "RBMC-44/WF-S100",
    (3, 53): "RBMC-53",
    (3, 54): "RBMC-54(S)",
    (3, 56): "RBMC-56",
    (3, 59): "RBMC-59",
    (3, 62): "RBMC-62",
    (3, 67): "RBMC-67",
    (3, 100): "WF-S100",
    (4, 300): "디맥스 DIR-300",
    (4, 400): "디맥스 DIR-400",
    (4, 600): "디맥스 DIR-600",
    (4, 700): "디맥스 DIR-700",
}

# Option lists are indexed by register value, labels as the app shows them.
HEATING_STRENGTH_OPTIONS = ["약", "중", "강"]  # r29, 경동
HEATING_WATER_OPTIONS = ["여름", "가을", "봄", "초겨울", "겨울"]  # r29, 귀뚜라미
BACKLIGHT_OPTIONS = ["자동 OFF", "ON/OFF", "항상 OFF", "항상 ON"]  # r17
TOUCH_LOCK_OPTIONS = ["잠금 해제", "온도 잠금", "전체 잠금"]  # r52
PERIOD_MODE_OPTIONS = ["예약제어", "온도제어"]  # r51 b14

CALIBRATION_MIN = -5.0
CALIBRATION_MAX = 5.0
LIMIT_MIN = 1
LIMIT_MAX = 99
# r21 values 1 and 2 mean "two/three step hot water", not a temperature.
HOT_WATER_LIMIT_MIN = 3


def controller_model_name(manufacturer: int, model: int) -> str | None:
    return CONTROLLER_MODELS.get((manufacturer, model))


def decode_calibration(raw: int) -> float:
    return round(raw / 10 - 5, 1)


def encode_calibration(value: float) -> int:
    if not CALIBRATION_MIN <= value <= CALIBRATION_MAX:
        raise ValueError(
            f"보정값은 {CALIBRATION_MIN}~{CALIBRATION_MAX} 사이여야 합니다: {value}"
        )
    tenths = round((value + 5) * 10, 6)
    if not float(tenths).is_integer():
        raise ValueError(f"보정값은 0.1 단위여야 합니다: {value}")
    return int(tenths)


# --- r7: 예약 주기/가동 시간 = hours * 100 + minutes; hours 0 is a 30 minute period.


@dataclass(frozen=True)
class TimerLimits:
    """r28 = longest period in hours * 100 + run-time step in minutes."""

    max_hours: int
    minute_step: int

    @classmethod
    def from_register(cls, raw: int) -> TimerLimits:
        return cls(raw // 100, raw % 100 or 1)


def decode_timer(raw: int) -> tuple[float, int]:
    hours, minutes = divmod(raw, 100)
    return (0.5 if hours == 0 else float(hours)), minutes


def encode_timer(interval_hours: float, run_minutes: int, limits: TimerLimits) -> int:
    if interval_hours != 0.5 and not float(interval_hours).is_integer():
        raise ValueError(f"예약 주기는 0.5시간 또는 정수 시간이어야 합니다: {interval_hours}")
    if not 0.5 <= interval_hours <= limits.max_hours:
        raise ValueError(
            f"예약 주기는 0.5~{limits.max_hours}시간 사이여야 합니다: {interval_hours}"
        )
    if not float(run_minutes).is_integer() or not 1 <= run_minutes <= 60:
        raise ValueError(f"가동 시간은 1~60분 사이의 정수여야 합니다: {run_minutes}")
    run_minutes = int(run_minutes)
    if run_minutes % limits.minute_step:
        raise ValueError(
            f"가동 시간은 {limits.minute_step}분 단위여야 합니다: {run_minutes}"
        )
    if run_minutes >= interval_hours * 60:
        raise ValueError("가동 시간은 예약 주기보다 짧아야 합니다")
    hours = 0 if interval_hours == 0.5 else int(interval_hours)
    return hours * 100 + run_minutes


# --- r50/r51: 구간반복.
# r50: b0 enabled, b1..b7 days Sun..Sat, b8..12 start hour, b13..15 end hour bits 0..2.
# r51: b0..1 end hour bits 3..4, b2..7 run minutes, b8..13 interval hours,
#      b14 temperature control (else schedule control), b15 unused.

DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
PERIOD_BOUNDS: dict[str, tuple[int, int]] = {
    "start_hour": (0, 24),
    "end_hour": (0, 24),
    "run_minutes": (1, 63),
    "interval_hours": (1, 12),
}


@dataclass(frozen=True)
class PeriodRepeat:
    enabled: bool
    days: tuple[bool, ...]
    start_hour: int
    end_hour: int
    run_minutes: int
    interval_hours: int
    temperature_control: bool
    reserved: int = 0

    @classmethod
    def from_registers(cls, r50: int, r51: int) -> PeriodRepeat:
        return cls(
            enabled=bool(r50 & 0x0001),
            days=tuple(bool(r50 & (1 << (1 + i))) for i in range(7)),
            start_hour=(r50 >> 8) & 0x1F,
            end_hour=((r51 & 0x0003) << 3) | (r50 >> 13),
            run_minutes=(r51 >> 2) & 0x3F,
            interval_hours=(r51 >> 8) & 0x3F,
            temperature_control=bool(r51 & 0x4000),
            reserved=r51 & 0x8000,
        )

    def to_registers(self) -> tuple[int, int]:
        r50 = int(self.enabled)
        for i, on in enumerate(self.days):
            r50 |= int(on) << (1 + i)
        r50 |= (self.start_hour & 0x1F) << 8
        r50 |= (self.end_hour & 0x07) << 13
        r51 = (self.end_hour >> 3) & 0x03
        r51 |= (self.run_minutes & 0x3F) << 2
        r51 |= (self.interval_hours & 0x3F) << 8
        r51 |= int(self.temperature_control) << 14
        r51 |= self.reserved & 0x8000
        return r50, r51

    def with_changes(self, **changes) -> PeriodRepeat:
        """Validate only the changed fields; the rest is what the device holds."""
        for field, value in changes.items():
            if field in PERIOD_BOUNDS:
                low, high = PERIOD_BOUNDS[field]
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{field} 는 정수여야 합니다: {value!r}")
                if not low <= value <= high:
                    raise ValueError(f"{field} 는 {low}~{high} 사이여야 합니다: {value}")
            elif field == "days":
                if len(value) != 7:
                    raise ValueError("요일은 7개여야 합니다")
            elif field not in ("enabled", "temperature_control"):
                raise ValueError(f"알 수 없는 구간반복 항목: {field}")
        return replace(self, **changes)

    def with_day(self, day: str, on: bool) -> PeriodRepeat:
        days = list(self.days)
        days[DAYS.index(day)] = on
        return self.with_changes(days=tuple(days))


def period_write_order(current: PeriodRepeat, target: PeriodRepeat) -> list[Reg]:
    """Registers to write, ordered so the split end hour never passes through >24.

    The end hour spans both registers; writing the side that lowers it first keeps
    the intermediate value between the old and the new value.
    """
    old50, old51 = current.to_registers()
    new50, new51 = target.to_registers()
    pairs = ((Reg.PERIOD_A, old50, new50), (Reg.PERIOD_B, old51, new51))
    changed = [reg for reg, old, new in pairs if old != new]
    if len(changed) == 2 and (target.end_hour >> 3) <= (current.end_hour >> 3):
        changed.reverse()
    return changed
