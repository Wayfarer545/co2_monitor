"""Runtime data carried on a ZyTemp CO2 config entry."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from .coordinator import ZyTempCoordinator

type ZyTempConfigEntry = ConfigEntry[ZyTempCoordinator]
