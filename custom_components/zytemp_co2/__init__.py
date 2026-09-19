"""The ZyTemp CO2 integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import ZyTempCoordinator
from .data import ZyTempConfigEntry

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ZyTempConfigEntry) -> bool:
    """Set up the sensor from a config entry."""
    coordinator = ZyTempCoordinator(hass, entry)
    await coordinator.async_start()
    entry.runtime_data = coordinator

    entry.async_on_unload(coordinator.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZyTempConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ZyTempConfigEntry) -> None:
    """Apply new alarm thresholds without touching the device.

    Reloading the entry would close the USB device and initialise it again,
    leaving every entity unknown for several seconds and firing state triggers
    in the user's automations. Refreshing the listeners recomputes the alarms
    from the new thresholds instead, which is instant.
    """
    entry.runtime_data.async_update_listeners()
