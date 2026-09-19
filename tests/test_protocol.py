"""Unit tests for the ZG01 wire protocol.

The module under test is loaded straight from its file so the suite runs without
Home Assistant installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "zytemp_co2" / "protocol.py"
_SPEC = importlib.util.spec_from_file_location("zytemp_protocol", _PATH)
assert _SPEC and _SPEC.loader
protocol = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(protocol)


def frame(hexdump: str) -> bytes:
    """Build a frame from a hexdump as captured from the device."""
    return bytes.fromhex(hexdump.replace(" ", ""))


# Frames captured from the real sensor (firmware 2.00, plaintext).
CO2_FRAME = frame("50 01 5c ad 0d 00 00 00")
TEMPERATURE_FRAME = frame("42 12 81 d5 0d 00 00 00")
HUMIDITY_FRAME = frame("41 00 00 41 0d 00 00 00")
UNKNOWN_FRAME = frame("6e 4d 62 1d 0d 00 00 00")


def test_ioctl_request_matches_kernel_macro() -> None:
    """HIDIOCSFEATURE(9) must equal the value the kernel headers produce."""
    assert protocol.hidiocsfeature(9) == 0xC0094806


def test_feature_report_prefixes_the_report_number() -> None:
    """The payload is report number 0 followed by the eight key bytes."""
    report = protocol.feature_report()
    assert len(report) == protocol.FRAME_SIZE + 1
    assert report[0] == 0x00
    assert tuple(report[1:]) == protocol.FEATURE_KEY


@pytest.mark.parametrize(
    "captured",
    [CO2_FRAME, TEMPERATURE_FRAME, HUMIDITY_FRAME, UNKNOWN_FRAME],
    ids=["co2", "temperature", "humidity", "unknown-opcode"],
)
def test_captured_frames_are_valid(captured: bytes) -> None:
    """Every frame captured from the device passes both integrity checks."""
    assert protocol.is_valid(captured)


def test_bad_checksum_is_rejected() -> None:
    """A frame whose checksum does not add up is refused."""
    corrupted = bytearray(CO2_FRAME)
    corrupted[3] ^= 0xFF
    assert not protocol.is_valid(bytes(corrupted))


def test_missing_terminator_is_rejected() -> None:
    """A frame without the 0x0D terminator is refused."""
    corrupted = bytearray(CO2_FRAME)
    corrupted[4] = 0x00
    assert not protocol.is_valid(bytes(corrupted))


def test_short_frame_is_rejected() -> None:
    """A truncated read is refused rather than indexed into."""
    assert not protocol.is_valid(CO2_FRAME[:5])


def test_payload_is_big_endian() -> None:
    """The measurement occupies bytes one and two, most significant first."""
    assert protocol.payload(CO2_FRAME) == 0x015C == 348


def test_temperature_conversion() -> None:
    """Temperature arrives in sixteenths of a kelvin."""
    celsius = protocol.temperature_from_raw(protocol.payload(TEMPERATURE_FRAME))
    assert celsius == pytest.approx(22.91, abs=0.01)


def test_temperature_absolute_zero() -> None:
    """A raw zero maps to absolute zero rather than to a plausible reading."""
    assert protocol.temperature_from_raw(0) == pytest.approx(-273.15)


def test_temperature_above_range_is_dropped() -> None:
    """Readings beyond the sensor's range are discarded."""
    assert protocol.temperature_from_raw(protocol.TEMPERATURE_MAX_RAW + 1) is None


def test_co2_passthrough() -> None:
    """A CO2 payload is already in parts per million."""
    assert protocol.co2_from_raw(protocol.payload(CO2_FRAME)) == 348


@pytest.mark.parametrize("raw", [0, 1, protocol.CO2_MIN_RAW - 1, protocol.CO2_MAX_RAW + 1])
def test_implausible_co2_is_dropped(raw: int) -> None:
    """Zero and out-of-range values are the garbage seen right after init."""
    assert protocol.co2_from_raw(raw) is None


@pytest.mark.parametrize("raw", [protocol.CO2_MIN_RAW, protocol.CO2_MAX_RAW])
def test_co2_range_is_inclusive(raw: int) -> None:
    """The accepted range includes both of its bounds."""
    assert protocol.co2_from_raw(raw) == raw


def rotate_left(data: bytes, bits: int) -> bytes:
    """Rotate a 64 bit big endian word left, undoing the protocol's right shift."""
    word = int.from_bytes(data, "big")
    rotated = ((word << bits) | (word >> (64 - bits))) & 0xFFFFFFFFFFFFFFFF
    return rotated.to_bytes(8, "big")


def obfuscate(plain: bytes) -> bytes:
    """Apply the pre-2.00 firmware obfuscation, inverting every decrypt step."""
    offsets = [((c >> 4) | (c << 4)) & 0xFF for c in protocol._MAGIC_WORD]
    rotated = bytes((plain[i] + offsets[i]) & 0xFF for i in range(8))
    xored = rotate_left(rotated, 3)
    shuffled = bytes(xored[i] ^ protocol.FEATURE_KEY[i] for i in range(8))
    raw = bytearray(8)
    for source, target in enumerate(protocol._SHUFFLE):
        raw[source] = shuffled[target]
    return bytes(raw)


@pytest.mark.parametrize(
    "captured",
    [CO2_FRAME, TEMPERATURE_FRAME, HUMIDITY_FRAME, UNKNOWN_FRAME],
    ids=["co2", "temperature", "humidity", "unknown-opcode"],
)
def test_decrypt_undoes_obfuscation(captured: bytes) -> None:
    """Obfuscating a frame and decrypting it returns the original bytes."""
    assert protocol.decrypt(obfuscate(captured)) == captured


def test_obfuscated_frame_fails_the_plaintext_check() -> None:
    """An obfuscated frame does not masquerade as a plaintext one."""
    assert not protocol.is_valid(obfuscate(CO2_FRAME))


def test_decoder_latches_plaintext_after_enough_frames() -> None:
    """The mode stays undecided until several frames agree, then sticks."""
    decoder = protocol.FrameDecoder()
    for _ in range(protocol.MODE_LATCH_FRAMES - 1):
        assert decoder.decode(CO2_FRAME) == CO2_FRAME
        assert decoder.decrypting is None
    assert decoder.decode(CO2_FRAME) == CO2_FRAME
    assert decoder.decrypting is False


def test_decoder_latches_obfuscated_after_enough_frames() -> None:
    """Obfuscated frames are detected and decoded the same way."""
    decoder = protocol.FrameDecoder()
    hidden = obfuscate(TEMPERATURE_FRAME)
    for _ in range(protocol.MODE_LATCH_FRAMES):
        assert decoder.decode(hidden) == TEMPERATURE_FRAME
    assert decoder.decrypting is True


def test_latched_decoder_rejects_the_other_mode() -> None:
    """Once latched, a frame in the opposite encoding is refused, not guessed."""
    decoder = protocol.FrameDecoder()
    for _ in range(protocol.MODE_LATCH_FRAMES):
        decoder.decode(CO2_FRAME)
    assert decoder.decrypting is False
    assert decoder.decode(obfuscate(CO2_FRAME)) is None


def test_reset_forgets_the_detected_mode() -> None:
    """Reopening the device re-detects the firmware it is talking to."""
    decoder = protocol.FrameDecoder()
    for _ in range(protocol.MODE_LATCH_FRAMES):
        decoder.decode(CO2_FRAME)
    decoder.reset()
    assert decoder.decrypting is None
    assert decoder.decode(obfuscate(CO2_FRAME)) == CO2_FRAME


def test_garbage_decodes_to_nothing() -> None:
    """Bytes that fit neither mode are dropped instead of being reported."""
    decoder = protocol.FrameDecoder()
    assert decoder.decode(bytes(8)) is None
    assert decoder.decrypting is None
