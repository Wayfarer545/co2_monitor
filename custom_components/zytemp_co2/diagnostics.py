"""Diagnostics for the ZyTemp CO2 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .data import ZyTempConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZyTempConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The hidraw node number moves whenever the device is replugged, so the device
    section is what makes a remote diagnosis possible at all.
    """
    coordinator = entry.runtime_data
    return {
        "options": dict(entry.options),
        "measurements": coordinator.data,
        "last_update_success": coordinator.last_update_success,
        "device": coordinator.diagnostics,
    }
