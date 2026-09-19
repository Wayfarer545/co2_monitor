"""CO2 alarms for the ZyTemp device."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ALARM_HYSTERESIS,
    CONF_CO2_CRITICAL,
    CONF_CO2_WARNING,
    DEFAULT_CO2_CRITICAL,
    DEFAULT_CO2_WARNING,
    KEY_CO2,
)
from .coordinator import ZyTempCoordinator
from .data import ZyTempConfigEntry
from .entity import ZyTempEntity


@dataclass(frozen=True, kw_only=True)
class ZyTempAlarmDescription(BinarySensorEntityDescription):
    """Describes a CO2 alarm and the option that sets its threshold."""

    option: str
    default: int


ALARMS: tuple[ZyTempAlarmDescription, ...] = (
    ZyTempAlarmDescription(
        key=CONF_CO2_WARNING,
        translation_key=CONF_CO2_WARNING,
        device_class=BinarySensorDeviceClass.PROBLEM,
        option=CONF_CO2_WARNING,
        default=DEFAULT_CO2_WARNING,
    ),
    ZyTempAlarmDescription(
        key=CONF_CO2_CRITICAL,
        translation_key=CONF_CO2_CRITICAL,
        device_class=BinarySensorDeviceClass.PROBLEM,
        option=CONF_CO2_CRITICAL,
        default=DEFAULT_CO2_CRITICAL,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZyTempConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the CO2 alarms."""
    coordinator = entry.runtime_data
    async_add_entities(ZyTempAlarm(coordinator, description) for description in ALARMS)


class ZyTempAlarm(ZyTempEntity, BinarySensorEntity):
    """Turns on while CO2 sits above a user defined threshold."""

    entity_description: ZyTempAlarmDescription

    def __init__(
        self, coordinator: ZyTempCoordinator, description: ZyTempAlarmDescription
    ) -> None:
        """Initialise the alarm from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """Return whether the alarm is raised, or None while CO2 is unknown."""
        return self._state

    async def async_added_to_hass(self) -> None:
        """Evaluate the alarm against whatever the device has already sent."""
        await super().async_added_to_hass()
        self._state = self._evaluate()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Re-evaluate the alarm on new data or on a threshold change."""
        self._state = self._evaluate()
        super()._handle_coordinator_update()

    def _evaluate(self) -> bool | None:
        """Compare the current reading against the configured threshold."""
        data = self.coordinator.data
        co2 = data.get(KEY_CO2) if data else None
        if co2 is None:
            # Reporting "no alarm" for a missing reading would be a quiet false
            # negative on something people rely on to be warned.
            return None

        threshold = self.coordinator.config_entry.options.get(
            self.entity_description.option, self.entity_description.default
        )
        if self._state:
            # Clear only once well below the threshold, so a reading hovering on
            # the line does not flap notifications.
            return co2 > threshold - ALARM_HYSTERESIS
        return co2 > threshold
