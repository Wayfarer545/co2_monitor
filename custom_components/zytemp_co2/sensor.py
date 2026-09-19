"""Sensors for the ZyTemp CO2 device."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfRatio, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_TEMPERATURE_OFFSET,
    DEFAULT_TEMPERATURE_OFFSET,
    KEY_CO2,
    KEY_TEMPERATURE,
)
from .coordinator import Measurements, ZyTempCoordinator
from .data import ZyTempConfigEntry
from .entity import ZyTempEntity


@dataclass(frozen=True, kw_only=True)
class ZyTempSensorDescription(SensorEntityDescription):
    """Describes a ZyTemp sensor."""

    value_fn: Callable[[Measurements, float], float | None]


def _temperature(data: Measurements, offset: float) -> float | None:
    """Apply the user's correction to the raw temperature."""
    celsius = data.get(KEY_TEMPERATURE)
    return None if celsius is None else celsius + offset


SENSORS: tuple[ZyTempSensorDescription, ...] = (
    ZyTempSensorDescription(
        key=KEY_CO2,
        translation_key=KEY_CO2,
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data, _offset: data.get(KEY_CO2),
    ),
    ZyTempSensorDescription(
        key=KEY_TEMPERATURE,
        translation_key=KEY_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_temperature,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZyTempConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        ZyTempSensor(coordinator, description) for description in SENSORS
    )


class ZyTempSensor(ZyTempEntity, SensorEntity):
    """A single measurement reported by the device."""

    entity_description: ZyTempSensorDescription

    def __init__(
        self, coordinator: ZyTempCoordinator, description: ZyTempSensorDescription
    ) -> None:
        """Initialise the sensor from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the latest reading, or None while it is unknown.

        A measurement can go stale on its own while the other keeps arriving, so
        this stays None-safe rather than assuming the data is complete.
        """
        data = self.coordinator.data
        if data is None:
            return None
        offset = self.coordinator.config_entry.options.get(
            CONF_TEMPERATURE_OFFSET, DEFAULT_TEMPERATURE_OFFSET
        )
        return self.entity_description.value_fn(data, offset)
