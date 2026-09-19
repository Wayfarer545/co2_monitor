"""Shared entity base for the ZyTemp CO2 integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import ZyTempCoordinator


class ZyTempEntity(CoordinatorEntity[ZyTempCoordinator]):
    """Base entity, bound to the one physical sensor behind this entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZyTempCoordinator, key: str) -> None:
        """Attach the entity to the device that produced the reading."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=DEVICE_NAME,
        )

    @property
    def available(self) -> bool:
        """Report unavailable while the device has produced nothing at all.

        The base class only tracks the last update's success, which stays true
        for the whole window between a device disappearing and the watchdog
        noticing it.
        """
        return super().available and self.coordinator.data is not None
