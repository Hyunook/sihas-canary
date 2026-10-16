"""BCM-300 settings beyond the v2 core entities: every control the SiHAS app has.

Lives apart from the platform modules so upstream changes to them merge cleanly;
each platform only calls the matching ``bcm_*`` factory below.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.exceptions import ServiceValidationError

from .bcm import BcmCoordinator, BcmEntity, BcmState
from .bcm_codec import (
    BACKLIGHT_OPTIONS,
    CALIBRATION_MAX,
    CALIBRATION_MIN,
    DAYS,
    HEATING_STRENGTH_OPTIONS,
    HEATING_WATER_OPTIONS,
    HOT_WATER_LIMIT_MIN,
    KITURAMI,
    KYUNGDONG,
    LIMIT_MAX,
    LIMIT_MIN,
    MANUFACTURERS,
    PERIOD_BOUNDS,
    PERIOD_MODE_OPTIONS,
    TOUCH_LOCK_OPTIONS,
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


async def _async_write(
    coordinator: BcmCoordinator, register: Reg, compute: Callable[[BcmState], int]
) -> None:
    """Resolve the value from a fresh read inside the coordinator's transaction."""

    def resolve(state: BcmState) -> tuple[Reg, int]:
        try:
            return register, compute(state)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    # The transaction holds the I/O lock and verifies the read-back.
    await coordinator._async_command(resolve)  # noqa: SLF001


def _whole(value: float) -> int:
    if not float(value).is_integer():
        raise ServiceValidationError(f"정수만 입력할 수 있습니다: {value}")
    return int(value)


def _period(state: BcmState) -> PeriodRepeat:
    return PeriodRepeat.from_registers(state[Reg.PERIOD_A], state[Reg.PERIOD_B])


async def _async_set_period(
    coordinator: BcmCoordinator, change: Callable[[PeriodRepeat], PeriodRepeat]
) -> None:
    current = _period(coordinator.data)
    try:
        target = change(current)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    for register in period_write_order(current, target):
        index = 0 if register == Reg.PERIOD_A else 1
        await _async_write(
            coordinator,
            register,
            lambda state, index=index: change(_period(state)).to_registers()[index],
        )


# --------------------------------------------------------------------------- select


class BcmOptionSelect(BcmEntity, SelectEntity):
    """A register whose value is the index into ``options``."""

    def __init__(
        self,
        coordinator: BcmCoordinator,
        key: str,
        register: Reg,
        options: list[str],
        *,
        category: EntityCategory | None = None,
        manufacturer: int | None = None,
    ) -> None:
        super().__init__(coordinator, key)
        self._register = register
        self._attr_options = list(options)
        self._attr_entity_category = category
        self._manufacturer = manufacturer

    def _maker_matches(self, state: BcmState) -> bool:
        return self._manufacturer is None or state[Reg.MANUFACTURER] == self._manufacturer

    @property
    def available(self) -> bool:
        return super().available and self._maker_matches(self.coordinator.data)

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.data[self._register]
        return self.options[value] if 0 <= value < len(self.options) else None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ServiceValidationError(f"지원하지 않는 값: {option}")
        value = self.options.index(option)

        def compute(state: BcmState) -> int:
            if not self._maker_matches(state):
                raise ValueError("이 보일러 제조사에는 해당하지 않는 설정입니다")
            return value

        await _async_write(self.coordinator, self._register, compute)


class BcmPeriodModeSelect(BcmEntity, SelectEntity):
    _attr_options = PERIOD_MODE_OPTIONS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BcmCoordinator) -> None:
        super().__init__(coordinator, "period_mode")

    @property
    def current_option(self) -> str | None:
        return self.options[int(_period(self.coordinator.data).temperature_control)]

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ServiceValidationError(f"지원하지 않는 값: {option}")
        on = bool(self.options.index(option))
        await _async_set_period(
            self.coordinator, lambda p: p.with_changes(temperature_control=on)
        )


def bcm_selects(coordinator: BcmCoordinator) -> list[SelectEntity]:
    entities: list[SelectEntity] = [
        BcmOptionSelect(
            coordinator,
            "backlight",
            Reg.BACKLIGHT,
            BACKLIGHT_OPTIONS,
            category=EntityCategory.CONFIG,
        ),
        BcmOptionSelect(
            coordinator,
            "touch_lock",
            Reg.TOUCH_LOCK,
            TOUCH_LOCK_OPTIONS,
            category=EntityCategory.CONFIG,
        ),
        BcmPeriodModeSelect(coordinator),
    ]
    # r29 means heating strength on 경동 and heating water season on 귀뚜라미 only.
    maker = coordinator.data[Reg.MANUFACTURER]
    if maker == KYUNGDONG:
        entities.append(
            BcmOptionSelect(
                coordinator,
                "heating_strength",
                Reg.SEASON,
                HEATING_STRENGTH_OPTIONS,
                manufacturer=KYUNGDONG,
            )
        )
    elif maker == KITURAMI:
        entities.append(
            BcmOptionSelect(
                coordinator,
                "heating_water_temperature",
                Reg.SEASON,
                HEATING_WATER_OPTIONS,
                manufacturer=KITURAMI,
            )
        )
    return entities


# --------------------------------------------------------------------------- number


class BcmLimitNumber(BcmEntity, NumberEntity):
    """One end of a set point range; the other end bounds it."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BcmCoordinator,
        key: str,
        register: Reg,
        partner: Reg,
        *,
        upper: bool,
        hot_water: bool = False,
    ) -> None:
        super().__init__(coordinator, key)
        self._register = register
        self._partner = partner
        self._upper = upper
        self._hot_water = hot_water
        self._floor = HOT_WATER_LIMIT_MIN if hot_water else LIMIT_MIN

    def _usable(self, state: BcmState) -> bool:
        return not self._hot_water or state.hot_water_kind == "linear"

    @property
    def available(self) -> bool:
        return super().available and self._usable(self.coordinator.data)

    def _bounds(self, state: BcmState) -> tuple[int, int]:
        partner = state[self._partner]
        if self._upper:
            return max(self._floor, partner + 1), LIMIT_MAX
        return self._floor, min(LIMIT_MAX, partner - 1)

    @property
    def native_min_value(self) -> float:
        return self._bounds(self.coordinator.data)[0]

    @property
    def native_max_value(self) -> float:
        return self._bounds(self.coordinator.data)[1]

    @property
    def native_value(self) -> float:
        return self.coordinator.data[self._register]

    async def async_set_native_value(self, value: float) -> None:
        target = _whole(value)

        def compute(state: BcmState) -> int:
            if not self._usable(state):
                raise ValueError("단계식 온수 모델은 온수 상·하한을 바꿀 수 없습니다")
            low, high = self._bounds(state)
            if not low <= target <= high:
                raise ValueError(f"{low}~{high} 사이의 값만 설정할 수 있습니다: {target}")
            return target

        await _async_write(self.coordinator, self._register, compute)


class BcmCalibrationNumber(BcmEntity, NumberEntity):
    # No temperature device class: an offset must not be unit-converted as a reading.
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = CALIBRATION_MIN
    _attr_native_max_value = CALIBRATION_MAX
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BcmCoordinator) -> None:
        super().__init__(coordinator, "temperature_calibration")

    @property
    def native_value(self) -> float:
        return decode_calibration(self.coordinator.data[Reg.CALIBRATION])

    async def async_set_native_value(self, value: float) -> None:
        await _async_write(
            self.coordinator, Reg.CALIBRATION, lambda _: encode_calibration(value)
        )


class BcmTimerNumber(BcmEntity, NumberEntity):
    """r7 holds both the timer period and its run time."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: BcmCoordinator, interval: bool) -> None:
        super().__init__(coordinator, "timer_interval" if interval else "timer_run_time")
        self._interval = interval
        self._attr_native_unit_of_measurement = (
            UnitOfTime.HOURS if interval else UnitOfTime.MINUTES
        )

    @property
    def _limits(self) -> TimerLimits:
        return TimerLimits.from_register(self.coordinator.data[Reg.TIMER_LIMIT])

    @property
    def available(self) -> bool:
        return super().available and self._limits.max_hours >= 1

    @property
    def native_min_value(self) -> float:
        return 0.5 if self._interval else self._limits.minute_step

    @property
    def native_max_value(self) -> float:
        return self._limits.max_hours if self._interval else 60

    @property
    def native_step(self) -> float:
        return 0.5 if self._interval else self._limits.minute_step

    @property
    def native_value(self) -> float:
        hours, minutes = decode_timer(self.coordinator.data[Reg.TIMER_TIME])
        return hours if self._interval else minutes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        limits = self._limits
        return {
            **super().extra_state_attributes,
            "max_interval_hours": limits.max_hours,
            "run_time_step_minutes": limits.minute_step,
        }

    async def async_set_native_value(self, value: float) -> None:
        def compute(state: BcmState) -> int:
            hours, minutes = decode_timer(state[Reg.TIMER_TIME])
            if self._interval:
                hours = value
            else:
                minutes = value
            limits = TimerLimits.from_register(state[Reg.TIMER_LIMIT])
            return encode_timer(hours, minutes, limits)

        await _async_write(self.coordinator, Reg.TIMER_TIME, compute)


class BcmPeriodNumber(BcmEntity, NumberEntity):
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: BcmCoordinator,
        key: str,
        field: str,
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, key)
        self._field = field
        self._attr_native_min_value, self._attr_native_max_value = PERIOD_BOUNDS[field]
        self._attr_native_unit_of_measurement = unit
        if unit is not None:
            self._attr_device_class = NumberDeviceClass.DURATION

    @property
    def native_value(self) -> float:
        return getattr(_period(self.coordinator.data), self._field)

    async def async_set_native_value(self, value: float) -> None:
        target = _whole(value)
        await _async_set_period(
            self.coordinator, lambda p: p.with_changes(**{self._field: target})
        )


def bcm_numbers(coordinator: BcmCoordinator) -> list[NumberEntity]:
    entities: list[NumberEntity] = [
        BcmTimerNumber(coordinator, interval=True),
        BcmTimerNumber(coordinator, interval=False),
        BcmLimitNumber(coordinator, "room_max", Reg.ROOM_MAX, Reg.ROOM_MIN, upper=True),
        BcmLimitNumber(coordinator, "room_min", Reg.ROOM_MIN, Reg.ROOM_MAX, upper=False),
        BcmLimitNumber(
            coordinator, "ondol_max", Reg.ONDOL_MAX, Reg.ONDOL_MIN, upper=True
        ),
        BcmLimitNumber(
            coordinator, "ondol_min", Reg.ONDOL_MIN, Reg.ONDOL_MAX, upper=False
        ),
        BcmCalibrationNumber(coordinator),
        BcmPeriodNumber(coordinator, "period_start_hour", "start_hour"),
        BcmPeriodNumber(coordinator, "period_end_hour", "end_hour"),
        BcmPeriodNumber(
            coordinator, "period_interval", "interval_hours", UnitOfTime.HOURS
        ),
        BcmPeriodNumber(
            coordinator, "period_run_time", "run_minutes", UnitOfTime.MINUTES
        ),
    ]
    # On step-type hot water models r21/r22 are the step count, not temperatures.
    if coordinator.hot_water_kind == "linear":
        entities += [
            BcmLimitNumber(
                coordinator,
                "hot_water_max",
                Reg.HOT_WATER_MAX,
                Reg.HOT_WATER_MIN,
                upper=True,
                hot_water=True,
            ),
            BcmLimitNumber(
                coordinator,
                "hot_water_min",
                Reg.HOT_WATER_MIN,
                Reg.HOT_WATER_MAX,
                upper=False,
                hot_water=True,
            ),
        ]
    return entities


# --------------------------------------------------------------------------- switch


class BcmRegisterSwitch(BcmEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: BcmCoordinator, key: str, register: Reg) -> None:
        super().__init__(coordinator, key)
        self._register = register

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data[self._register]
        return bool(value) if value in (0, 1) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await _async_write(self.coordinator, self._register, lambda _: 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await _async_write(self.coordinator, self._register, lambda _: 0)


class BcmPeriodSwitch(BcmEntity, SwitchEntity):
    """구간반복 사용 or one of its weekdays."""

    def __init__(self, coordinator: BcmCoordinator, day: str | None = None) -> None:
        super().__init__(coordinator, f"period_{day}" if day else "period_repeat")
        self._day = day
        if day:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        period = _period(self.coordinator.data)
        return period.days[DAYS.index(self._day)] if self._day else period.enabled

    async def _async_set(self, on: bool) -> None:
        if self._day:
            day = self._day
            await _async_set_period(self.coordinator, lambda p: p.with_day(day, on))
        else:
            await _async_set_period(self.coordinator, lambda p: p.with_changes(enabled=on))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)


def bcm_switches(coordinator: BcmCoordinator) -> list[SwitchEntity]:
    return [
        BcmPeriodSwitch(coordinator),
        *(BcmPeriodSwitch(coordinator, day) for day in DAYS),
        BcmRegisterSwitch(coordinator, "buzzer", Reg.BUZZER),
    ]


# --------------------------------------------------------------------------- sensor


class BcmRegisterSensor(BcmEntity, SensorEntity):
    def __init__(
        self,
        coordinator: BcmCoordinator,
        key: str,
        value: Callable[[BcmState], Any],
        *,
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        category: EntityCategory | None = None,
        options: list[str] | None = None,
    ) -> None:
        super().__init__(coordinator, key)
        self._value = value
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_entity_category = category
        self._attr_options = options

    @property
    def native_value(self) -> Any:
        return self._value(self.coordinator.data)


class BcmControllerModelSensor(BcmEntity, SensorEntity):
    """Read only: writing r16 to a wrong model breaks the boiler link."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BcmCoordinator) -> None:
        super().__init__(coordinator, "controller_model")

    @property
    def native_value(self) -> str:
        state = self.coordinator.data
        number = state[Reg.CONTROLLER_MODEL]
        name = controller_model_name(state[Reg.MANUFACTURER], number)
        return name if name is not None else str(number)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **super().extra_state_attributes,
            "model_number": self.coordinator.data[Reg.CONTROLLER_MODEL],
        }


def bcm_sensors(coordinator: BcmCoordinator) -> list[SensorEntity]:
    def celsius(register: Reg) -> Callable[[BcmState], int]:
        return lambda state: state[register]

    return [
        BcmRegisterSensor(
            coordinator,
            "ondol_current_temperature",
            celsius(Reg.ONDOL_TEMPERATURE),
            device_class=SensorDeviceClass.TEMPERATURE,
            unit=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BcmRegisterSensor(
            coordinator,
            "hot_water_current_temperature",
            celsius(Reg.HOT_WATER_TEMPERATURE),
            device_class=SensorDeviceClass.TEMPERATURE,
            unit=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        BcmRegisterSensor(
            coordinator,
            "away_temperature",
            celsius(Reg.AWAY_TEMPERATURE),
            device_class=SensorDeviceClass.TEMPERATURE,
            unit=UnitOfTemperature.CELSIUS,
            category=EntityCategory.DIAGNOSTIC,
        ),
        BcmRegisterSensor(
            coordinator,
            "error_code",
            lambda state: state[Reg.ERROR_CODE],
            category=EntityCategory.DIAGNOSTIC,
        ),
        BcmRegisterSensor(
            coordinator,
            "manufacturer",
            lambda state: MANUFACTURERS.get(state[Reg.MANUFACTURER]),
            device_class=SensorDeviceClass.ENUM,
            category=EntityCategory.DIAGNOSTIC,
            options=list(MANUFACTURERS.values()),
        ),
        BcmControllerModelSensor(coordinator),
    ]


# --------------------------------------------------------------------------- binary


class BcmRegisterBinarySensor(BcmEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: BcmCoordinator,
        key: str,
        register: Reg,
        is_on: Callable[[int], bool],
        device_class: BinarySensorDeviceClass,
        category: EntityCategory | None = None,
    ) -> None:
        super().__init__(coordinator, key)
        self._register = register
        self._is_on = is_on
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def is_on(self) -> bool:
        return self._is_on(self.coordinator.data[self._register])


def bcm_binary_sensors(coordinator: BcmCoordinator) -> list[BinarySensorEntity]:
    return [
        BcmRegisterBinarySensor(
            coordinator,
            "flame",
            Reg.FLAME,
            lambda value: value != 0,
            BinarySensorDeviceClass.RUNNING,
        ),
        BcmRegisterBinarySensor(
            coordinator,
            "water_refill",
            Reg.WATER_REFILL,
            lambda value: value != 0,
            BinarySensorDeviceClass.PROBLEM,
            EntityCategory.DIAGNOSTIC,
        ),
        BcmRegisterBinarySensor(
            coordinator,
            "boiler_link",
            Reg.BOILER_LINK,
            lambda value: value == 0,
            BinarySensorDeviceClass.CONNECTIVITY,
            EntityCategory.DIAGNOSTIC,
        ),
    ]

