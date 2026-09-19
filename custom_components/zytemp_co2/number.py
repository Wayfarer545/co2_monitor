"""Alarm thresholds exposed as numbers, editable from a dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfRatio
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CO2_THRESHOLD_MAX,
    CO2_THRESHOLD_MIN,
    CONF_CO2_CRITICAL,
    CONF_CO2_WARNING,
    DEFAULT_CO2_CRITICAL,
    DEFAULT_CO2_WARNING,
    DOMAIN,
)
from .coordinator import ZyTempCoordinator
from .data import ZyTempConfigEntry
from .entity import ZyTempEntity


@dataclass(frozen=True, kw_only=True)
class ZyTempNumberDescription(NumberEntityDescription):
    """Describes a threshold that is stored in the config entry options."""

    option: str
    default: float


THRESHOLDS: tuple[ZyTempNumberDescription, ...] = (
    ZyTempNumberDescription(
        key=CONF_CO2_WARNING,
        translation_key=CONF_CO2_WARNING,
        device_class=NumberDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        native_min_value=CO2_THRESHOLD_MIN,
        native_max_value=CO2_THRESHOLD_MAX,
        native_step=50,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        option=CONF_CO2_WARNING,
        default=DEFAULT_CO2_WARNING,
    ),
    ZyTempNumberDescription(
        key=CONF_CO2_CRITICAL,
        translation_key=CONF_CO2_CRITICAL,
        device_class=NumberDeviceClass.CO2,
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        native_min_value=CO2_THRESHOLD_MIN,
        native_max_value=CO2_THRESHOLD_MAX,
        native_step=50,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        option=CONF_CO2_CRITICAL,
        default=DEFAULT_CO2_CRITICAL,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZyTempConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the threshold numbers."""
    coordinator = entry.runtime_data
    async_add_entities(
        ZyTempThreshold(coordinator, description) for description in THRESHOLDS
    )


class ZyTempThreshold(ZyTempEntity, NumberEntity):
    """A CO2 alarm threshold.

    The value lives in the config entry options, the same place the options flow
    writes it, so editing it here and editing it in the integration's settings
    can never drift apart.
    """

    entity_description: ZyTempNumberDescription

    def __init__(
        self, coordinator: ZyTempCoordinator, description: ZyTempNumberDescription
    ) -> None:
        """Initialise the threshold from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Always available: a threshold is configuration, not a measurement.

        It has to stay editable while the sensor is unplugged, which is exactly
        when the base class would report the entity as unavailable.
        """
        return True

    @property
    def native_value(self) -> float:
        """Return the threshold currently stored in the options."""
        return self.coordinator.config_entry.options.get(
            self.entity_description.option, self.entity_description.default
        )

    async def async_set_native_value(self, value: float) -> None:
        """Store the new threshold, refusing to let the two cross over."""
        entry = self.coordinator.config_entry
        options = {**entry.options, self.entity_description.option: value}
        warning = options.get(CONF_CO2_WARNING, DEFAULT_CO2_WARNING)
        critical = options.get(CONF_CO2_CRITICAL, DEFAULT_CO2_CRITICAL)

        if critical <= warning:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="critical_not_above_warning",
                translation_placeholders={
                    "warning": f"{warning:.0f}",
                    "critical": f"{critical:.0f}",
                },
            )

        # Writing the options fires the entry's update listener, which refreshes
        # the alarms in place without reopening the USB device.
        self.hass.config_entries.async_update_entry(entry, options=options)
