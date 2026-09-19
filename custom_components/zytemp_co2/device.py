"""Low level access to a ZyAura ZG01 CO2 sensor through /dev/hidraw."""

from __future__ import annotations

import fcntl
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .const import KEY_CO2, KEY_TEMPERATURE
from .protocol import (
    FRAME_SIZE,
    OP_CO2,
    OP_TEMPERATURE,
    FrameDecoder,
    co2_from_raw,
    feature_report,
    hidiocsfeature,
    payload,
    temperature_from_raw,
)

_LOGGER = logging.getLogger(__name__)

SYSFS_HIDRAW: Final = Path("/sys/class/hidraw")
_HID_ID_PREFIX: Final = "HID_ID="
USB_VENDOR_ID: Final = "04D9"
USB_PRODUCT_ID: Final = "A052"


class DeviceNotFound(Exception):
    """No ZG01 sensor is attached to this machine."""


@dataclass(frozen=True, slots=True)
class Reading:
    """One decoded measurement."""

    key: str
    value: float


def find_device_paths() -> list[str]:
    """Return every /dev/hidraw node that belongs to a ZG01 sensor.

    Blocking: reads sysfs. The node number moves when the device is replugged,
    which is why the path is resolved afresh on every open rather than stored in
    the config entry.
    """
    paths: list[str] = []
    try:
        entries = sorted(SYSFS_HIDRAW.iterdir())
    except OSError as err:
        _LOGGER.debug("Cannot list %s: %s", SYSFS_HIDRAW, err)
        return paths

    for entry in entries:
        try:
            uevent = (entry / "device" / "uevent").read_text()
        except OSError:
            continue
        for line in uevent.splitlines():
            if not line.startswith(_HID_ID_PREFIX):
                continue
            parts = line.removeprefix(_HID_ID_PREFIX).split(":")
            if (
                len(parts) == 3
                and parts[1][-4:].upper() == USB_VENDOR_ID
                and parts[2][-4:].upper() == USB_PRODUCT_ID
            ):
                paths.append(f"/dev/{entry.name}")
    return paths


class ZyTempDevice:
    """A ZG01 sensor opened through hidraw.

    The device pushes one measurement per frame on its own; nothing polls it.
    """

    def __init__(self) -> None:
        """Initialise a device that is not open yet."""
        self._fd: int | None = None
        self._decoder = FrameDecoder()
        self.path: str | None = None
        self.frames_valid = 0
        self.frames_invalid = 0
        self.frames_ignored = 0
        self.open_count = 0

    @property
    def fd(self) -> int | None:
        """Return the open file descriptor, or None while closed."""
        return self._fd

    @property
    def decrypting(self) -> bool | None:
        """Return whether the firmware obfuscates frames, None until detected."""
        return self._decoder.decrypting

    def open(self) -> str:
        """Locate the sensor, open it and start its data stream.

        Blocking: the ioctl issues a synchronous USB control transfer with a five
        second timeout, so this must never run on the event loop.

        Raises DeviceNotFound when no sensor is attached, and OSError (including
        PermissionError) when one is attached but cannot be opened.
        """
        paths = find_device_paths()
        if not paths:
            raise DeviceNotFound("No ZyAura ZG01 sensor found")
        if len(paths) > 1:
            _LOGGER.warning(
                "Found %d ZG01 sensors (%s); using the first one",
                len(paths),
                ", ".join(paths),
            )

        path = paths[0]
        fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, hidiocsfeature(FRAME_SIZE + 1), feature_report())
        except OSError:
            os.close(fd)
            raise

        self._fd = fd
        self.path = path
        self.open_count += 1
        self._decoder.reset()
        _LOGGER.debug("Opened %s (fd %d)", path, fd)
        return path

    def close(self) -> None:
        """Close the device. Safe to call when already closed."""
        if self._fd is None:
            return
        fd = self._fd
        # Clear the handle first: a failed close must not leave a stale fd behind
        # for a later call to close a second time.
        self._fd = None
        try:
            os.close(fd)
        except OSError as err:
            _LOGGER.debug("Error closing %s: %s", self.path, err)
        else:
            _LOGGER.debug("Closed %s (fd %d)", self.path, fd)

    def read(self) -> Reading | None:
        """Read one frame, returning a measurement when it carries one.

        Raises BlockingIOError when nothing is queued, and OSError when the
        device has gone away. Note that hidraw reports a vanished device as EIO,
        not ENODEV: the kernel checks that before it checks O_NONBLOCK.
        """
        if self._fd is None:
            raise OSError("Device is not open")

        raw = os.read(self._fd, FRAME_SIZE)
        if len(raw) != FRAME_SIZE:
            self.frames_invalid += 1
            return None

        frame = self._decoder.decode(raw)
        if frame is None:
            self.frames_invalid += 1
            return None

        self.frames_valid += 1
        value = payload(frame)
        if frame[0] == OP_CO2:
            co2 = co2_from_raw(value)
            return None if co2 is None else Reading(KEY_CO2, co2)
        if frame[0] == OP_TEMPERATURE:
            celsius = temperature_from_raw(value)
            return None if celsius is None else Reading(KEY_TEMPERATURE, celsius)

        # The device cycles through roughly a dozen opcodes; the rest are either
        # undocumented or belong to sensors this model does not have.
        self.frames_ignored += 1
        return None
