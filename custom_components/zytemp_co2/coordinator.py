"""Push coordinator for the ZyTemp CO2 sensor."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    FIRST_FRAME_TIMEOUT,
    KEY_CO2,
    KEY_TEMPERATURE,
    READING_TTL,
    REOPEN_BACKOFF,
    WATCHDOG_INTERVAL,
    WATCHDOG_TIMEOUT,
)
from .device import DeviceNotFound, Reading, ZyTempDevice

_LOGGER = logging.getLogger(__name__)

type Measurements = dict[str, float | None]


class ZyTempCoordinator(DataUpdateCoordinator[Measurements]):
    """Streams measurements from the sensor into Home Assistant.

    The device pushes frames on its own, so nothing here polls: the event loop
    watches the file descriptor and every decoded frame updates the entities.
    All timing is monotonic, because this board has no RTC and its wall clock
    jumps once NTP catches up after a boot.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Set up a coordinator that has not opened the device yet."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,  # push based, never polled
        )
        self.device = ZyTempDevice()
        self._readings: dict[str, tuple[float, float]] = {}
        self._watched_fd: int | None = None
        self._last_frame = 0.0
        self._reopen_attempt = 0
        self._reopening = False
        self._cancel_watchdog: CALLBACK_TYPE | None = None
        self._cancel_reopen: CALLBACK_TYPE | None = None
        self._first_frame = asyncio.Event()
        self._stopped = False

    async def async_start(self) -> None:
        """Open the sensor and wait for proof that it actually streams data.

        Raises ConfigEntryNotReady, which is used here and nowhere else: once
        setup has succeeded every later reconnect is handled internally, so the
        two retry mechanisms never overlap.
        """
        try:
            await self._async_open()
        except DeviceNotFound as err:
            raise ConfigEntryNotReady("No ZyAura ZG01 sensor found") from err
        except OSError as err:
            raise ConfigEntryNotReady(f"Cannot open the sensor: {err}") from err

        try:
            async with asyncio.timeout(FIRST_FRAME_TIMEOUT):
                await self._first_frame.wait()
        except TimeoutError as err:
            # Leaving the descriptor open here would leak one per retry, because
            # a failed setup never calls async_unload_entry.
            self.async_stop()
            raise ConfigEntryNotReady(
                f"The sensor sent nothing within {FIRST_FRAME_TIMEOUT:.0f} s"
            ) from err

        self.async_set_updated_data(self._snapshot())

    @callback
    def async_stop(self) -> None:
        """Release the device and cancel every pending timer."""
        self._stopped = True
        for cancel in (self._cancel_watchdog, self._cancel_reopen):
            if cancel is not None:
                cancel()
        self._cancel_watchdog = None
        self._cancel_reopen = None
        self._stop_watching()
        self.device.close()

    async def _async_open(self) -> None:
        """Open the device off the event loop and start watching it.

        Both the sysfs scan and the ioctl block: the ioctl issues a synchronous
        USB control transfer with a five second timeout, which on the event loop
        would freeze the whole of Home Assistant.
        """
        await self.hass.async_add_executor_job(self.device.open)
        fd = self.device.fd
        if fd is None:  # pragma: no cover - open either succeeds or raises
            raise OSError("Device did not provide a descriptor")

        self._last_frame = time.monotonic()
        self.hass.loop.add_reader(fd, self._handle_readable)
        self._watched_fd = fd
        self._reopen_attempt = 0
        self._schedule_watchdog()

    @callback
    def _handle_readable(self) -> None:
        """Drain the device; the event loop calls this when the fd is readable."""
        try:
            while True:
                reading = self.device.read()
                if reading is not None:
                    self._store(reading)
        except BlockingIOError:
            return
        except OSError as err:
            # A vanished device reports EIO, not ENODEV, and leaves the fd
            # permanently readable: the reader has to come off first, or this
            # callback spins forever.
            self._handle_loss(f"lost the sensor ({err})")
        except Exception:  # noqa: BLE001 - a raising reader would spin forever
            _LOGGER.exception("Unexpected failure while reading the sensor")
            self._handle_loss("unexpected read failure")

    @callback
    def _handle_loss(self, reason: str) -> None:
        """Detach from a device that stopped working and plan a reconnect."""
        self._stop_watching()
        self.device.close()
        _LOGGER.warning("Reconnecting: %s", reason)
        self.async_set_update_error(UpdateFailed(reason))
        self._schedule_reopen()

    @callback
    def _store(self, reading: Reading) -> None:
        """Record a measurement and publish it when it changed."""
        now = time.monotonic()
        self._last_frame = now
        previous = self._readings.get(reading.key)
        self._readings[reading.key] = (reading.value, now)
        self._first_frame.set()

        # The device repeats every measurement each few seconds. Republishing an
        # unchanged value costs a pass over all entities for nothing.
        if (
            previous is not None
            and previous[0] == reading.value
            and self.last_update_success
        ):
            return
        self.async_set_updated_data(self._snapshot())

    def _snapshot(self) -> Measurements:
        """Return the current readings, reporting stale ones as unknown."""
        now = time.monotonic()
        snapshot: Measurements = {}
        for key in (KEY_CO2, KEY_TEMPERATURE):
            recorded = self._readings.get(key)
            if recorded is None or now - recorded[1] > READING_TTL:
                snapshot[key] = None
            else:
                snapshot[key] = recorded[0]
        return snapshot

    @callback
    def _stop_watching(self) -> None:
        """Take the descriptor off the event loop before anyone closes it.

        Closing it first would let the number be reused by another socket while
        the selector still holds it, desynchronising asyncio's reader map.
        """
        if self._watched_fd is None:
            return
        self.hass.loop.remove_reader(self._watched_fd)
        self._watched_fd = None

    @callback
    def _schedule_watchdog(self) -> None:
        """Arm the next silence check."""
        if self._stopped:
            return
        self._cancel_watchdog = async_call_later(
            self.hass, WATCHDOG_INTERVAL, self._async_watchdog
        )

    @callback
    def _async_watchdog(self, _now: Any) -> None:
        """Notice a device that stopped talking, and expire stale readings."""
        self._cancel_watchdog = None
        if self._stopped or self._watched_fd is None:
            return

        silence = time.monotonic() - self._last_frame
        if silence > WATCHDOG_TIMEOUT:
            self._handle_loss(f"no frame for {silence:.0f} s")
            return

        # One measurement can go quiet while the other keeps arriving, which
        # would otherwise freeze it at its last value for good.
        snapshot = self._snapshot()
        if snapshot != self.data:
            self.async_set_updated_data(snapshot)
        self._schedule_watchdog()

    @callback
    def _schedule_reopen(self) -> None:
        """Plan the next reconnect attempt, unless one is already pending."""
        if self._stopped or self._reopening or self._cancel_reopen is not None:
            return
        delay = REOPEN_BACKOFF[min(self._reopen_attempt, len(REOPEN_BACKOFF) - 1)]
        self._reopen_attempt += 1
        self._cancel_reopen = async_call_later(self.hass, delay, self._async_reopen)

    async def _async_reopen(self, _now: Any) -> None:
        """Try to pick the device up again, backing off while it stays away."""
        self._cancel_reopen = None
        if self._stopped or self._reopening:
            return

        self._reopening = True
        try:
            await self._async_open()
        except (DeviceNotFound, OSError) as err:
            _LOGGER.debug("Sensor still unavailable: %s", err)
            self._reopening = False
            self._schedule_reopen()
            return
        self._reopening = False

        _LOGGER.info("Sensor reconnected on %s", self.device.path)
        self.async_set_updated_data(self._snapshot())

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Return what is needed to debug this device from a distance."""
        now = time.monotonic()
        return {
            "path": self.device.path,
            "obfuscated_firmware": self.device.decrypting,
            "open_count": self.device.open_count,
            "reopen_attempt": self._reopen_attempt,
            "watching": self._watched_fd is not None,
            "seconds_since_last_frame": (
                round(now - self._last_frame, 1) if self._last_frame else None
            ),
            "frames": {
                "valid": self.device.frames_valid,
                "invalid": self.device.frames_invalid,
                "ignored_opcode": self.device.frames_ignored,
            },
            "reading_age": {
                key: round(now - seen, 1) for key, (_, seen) in self._readings.items()
            },
        }
