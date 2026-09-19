"""Wire protocol of the ZyAura ZG01 CO2 sensor (USB 04d9:a052).

Deliberately free of Home Assistant imports so it can be unit tested on its own.
"""

from __future__ import annotations

from typing import Final

FRAME_SIZE: Final = 8
FRAME_TERMINATOR: Final = 0x0D

OP_CO2: Final = 0x50
OP_TEMPERATURE: Final = 0x42

# Handed to the device with HID SET_REPORT to start the stream. Firmware older
# than 2.00 also uses it as the XOR key of its obfuscation, so the two must be
# the same constant.
FEATURE_KEY: Final = (0xC4, 0xC6, 0xC0, 0x92, 0x40, 0x23, 0xDC, 0x96)

_MAGIC_WORD: Final = (0x48, 0x74, 0x65, 0x6D, 0x70, 0x39, 0x39, 0x65)  # "Htemp99e"
_SHUFFLE: Final = (2, 4, 0, 7, 1, 6, 5, 3)

# The sensor emits a garbage 0x50 frame in the first seconds after init and tops
# out at 10000 ppm; readings outside this window are not real.
# A frame can satisfy the terminator and checksum test by chance, so the
# plaintext/obfuscated decision is only latched once several frames agree.
MODE_LATCH_FRAMES: Final = 3

CO2_MIN_RAW: Final = 100
CO2_MAX_RAW: Final = 10000
TEMPERATURE_MAX_RAW: Final = 5970  # ~99.98 °C


def hidiocsfeature(length: int) -> int:
    """Return the HIDIOCSFEATURE ioctl request for a buffer of *length* bytes."""
    return (3 << 30) | (length << 16) | (ord("H") << 8) | 0x06


def feature_report() -> bytearray:
    """Return the SET_REPORT payload: report number 0 followed by the key."""
    return bytearray((0x00, *FEATURE_KEY))


def decrypt(raw: bytes) -> bytes:
    """Undo the obfuscation applied by firmware older than 2.00."""
    shuffled = bytearray(FRAME_SIZE)
    for source, target in enumerate(_SHUFFLE):
        shuffled[target] = raw[source]
    xored = [shuffled[i] ^ FEATURE_KEY[i] for i in range(FRAME_SIZE)]
    # Rotate the whole 64 bit word right by three bits; index -1 wraps to the end.
    rotated = [((xored[i] >> 3) | (xored[i - 1] << 5)) & 0xFF for i in range(FRAME_SIZE)]
    offsets = [((c >> 4) | (c << 4)) & 0xFF for c in _MAGIC_WORD]
    return bytes((rotated[i] - offsets[i]) & 0xFF for i in range(FRAME_SIZE))


def is_valid(frame: bytes) -> bool:
    """Check that a decoded frame carries its terminator and matching checksum."""
    return (
        len(frame) == FRAME_SIZE
        and frame[FRAME_SIZE // 2] == FRAME_TERMINATOR
        and (frame[0] + frame[1] + frame[2]) & 0xFF == frame[3]
    )


def payload(frame: bytes) -> int:
    """Return the big endian 16 bit measurement carried by a frame."""
    return (frame[1] << 8) | frame[2]


def co2_from_raw(raw: int) -> int | None:
    """Convert a 0x50 payload to ppm, rejecting implausible readings."""
    if not CO2_MIN_RAW <= raw <= CO2_MAX_RAW:
        return None
    return raw


def temperature_from_raw(raw: int) -> float | None:
    """Convert a 0x42 payload, in sixteenths of a kelvin, to degrees Celsius."""
    if raw > TEMPERATURE_MAX_RAW:
        return None
    return raw / 16.0 - 273.15


class FrameDecoder:
    """Decodes frames, working out once whether the firmware obfuscates them.

    Firmware 2.00 and newer sends plaintext; older revisions obfuscate. Which one
    is in front of us can only be told from the data, so the decision is latched
    after several frames agree and dropped again whenever the device is reopened.
    """

    def __init__(self) -> None:
        """Initialise a decoder that has not yet settled on a mode."""
        self.decrypting: bool | None = None
        self._plain_streak = 0
        self._crypt_streak = 0

    def reset(self) -> None:
        """Forget the detected mode; a replugged device may run other firmware."""
        self.decrypting = None
        self._plain_streak = 0
        self._crypt_streak = 0

    def decode(self, raw: bytes) -> bytes | None:
        """Return the decoded frame, or None when it fails its integrity checks."""
        if self.decrypting is True:
            frame = decrypt(raw)
            return frame if is_valid(frame) else None
        if self.decrypting is False:
            return raw if is_valid(raw) else None

        # A frame passes the terminator and checksum test by chance about once in
        # 65536, which at this frame rate happens every few days. Latching on a
        # single frame would therefore flip the mode at random.
        if is_valid(raw):
            self._plain_streak += 1
            if self._plain_streak >= MODE_LATCH_FRAMES:
                self.decrypting = False
            return raw

        frame = decrypt(raw)
        if is_valid(frame):
            self._crypt_streak += 1
            if self._crypt_streak >= MODE_LATCH_FRAMES:
                self.decrypting = True
            return frame

        return None
