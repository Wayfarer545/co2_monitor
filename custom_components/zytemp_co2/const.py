"""Constants for the ZyTemp CO2 integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "zytemp_co2"

DEVICE_NAME: Final = "CO2 Monitor"
MANUFACTURER: Final = "ZyAura"
MODEL: Final = "ZG01 (MT8057s)"

KEY_CO2: Final = "co2"
KEY_TEMPERATURE: Final = "temperature"

# The device repeats each measurement roughly every five seconds. A reading that
# stops arriving while the other one keeps coming would otherwise stay frozen at
# its last value forever, so each reading expires on its own.
READING_TTL: Final = 120.0

# No frame at all for this long means the device is gone rather than merely idle.
WATCHDOG_TIMEOUT: Final = 60.0
WATCHDOG_INTERVAL: Final = 15.0

# Reconnect delays, in seconds; the last one repeats for as long as it takes.
REOPEN_BACKOFF: Final = (5.0, 10.0, 30.0, 60.0)

# How long the first setup waits for proof that the device really talks.
FIRST_FRAME_TIMEOUT: Final = 20.0

CONF_CO2_WARNING: Final = "co2_warning"
CONF_CO2_CRITICAL: Final = "co2_critical"
CONF_TEMPERATURE_OFFSET: Final = "temperature_offset"

DEFAULT_CO2_WARNING: Final = 1000
DEFAULT_CO2_CRITICAL: Final = 1400
DEFAULT_TEMPERATURE_OFFSET: Final = 0.0

# Clean rural air can sit below the global background, so the lower bound has
# to leave room for a meaningful threshold there.
CO2_THRESHOLD_MIN: Final = 300
CO2_THRESHOLD_MAX: Final = 5000
TEMPERATURE_OFFSET_LIMIT: Final = 10.0

# An alarm clears this far below its threshold so a reading sitting on the line
# does not flap notifications.
ALARM_HYSTERESIS: Final = 50
