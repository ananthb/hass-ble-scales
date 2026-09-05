"""Parser tests, anchored on frames captured from real hardware."""

from ble_scales.parser import (
    AAA_TYPE_IMPEDANCE,
    AAA_TYPE_WEIGHT,
    parse_aaa,
)

# Captured 2026-09-05 from AAA044 (A0:91:61:C8:0B:5D) via the Home Assistant
# Bluetooth proxy at 6a. Company id 0xA0AC, so the XOR key is 0xA0.
# Raw advertisement:
#   02 01 04 | 03 03 B0 FF | 0F FF AC A0 <12 bytes> | 07 09 "AAA044"
REAL_COMPANY_ID = 0xA0AC
REAL_MFR_DATA = bytes.fromhex("5d0bc86191a0" "a2b4a0a206be")


def _encode(company_id: int, value: int, frame_type: int, mac=b"\x00" * 6) -> bytes:
    """Build a synthetic frame the way the scale would, for round-trip tests."""
    payload = bytearray(value.to_bytes(4, "big") + bytes([frame_type, 0]))
    payload[5] = sum(payload[0:5]) & 0x1F
    key = (company_id >> 8) & 0xFF
    return bytes(mac) + bytes(b ^ key for b in payload)


def test_real_capture_is_a_valid_impedance_frame():
    """The one frame we know is genuine must decode, checksum included."""
    reading = parse_aaa(REAL_COMPANY_ID, REAL_MFR_DATA)
    assert reading is not None
    # Nobody was standing on it: an unstable impedance frame reading 2.
    assert reading.weight_kg is None
    assert reading.impedance == 2
    assert reading.stable is False


def test_real_capture_payload_deobfuscates_as_documented():
    """Pin the XOR result, so a change to the key derivation fails loudly."""
    key = (REAL_COMPANY_ID >> 8) & 0xFF
    assert key == 0xA0
    payload = bytes(b ^ key for b in REAL_MFR_DATA[6:12])
    assert payload == bytes.fromhex("021400" "02a61e")
    assert payload[4] == AAA_TYPE_IMPEDANCE
    assert (sum(payload[0:5]) & 0x1F) == (payload[5] & 0x1F)


def test_stable_weight_frame():
    frame = _encode(REAL_COMPANY_ID, (1 << 31) | 72_350, AAA_TYPE_WEIGHT)
    reading = parse_aaa(REAL_COMPANY_ID, frame)
    assert reading is not None
    assert reading.weight_kg == 72.35
    assert reading.stable is True


def test_unstable_weight_still_decodes():
    """Live weight matters for a scale you are standing on."""
    reading = parse_aaa(REAL_COMPANY_ID, _encode(REAL_COMPANY_ID, 71_000, AAA_TYPE_WEIGHT))
    assert reading is not None
    assert reading.weight_kg == 71.0
    assert reading.stable is False


def test_bad_checksum_is_rejected():
    frame = bytearray(_encode(REAL_COMPANY_ID, (1 << 31) | 72_350, AAA_TYPE_WEIGHT))
    frame[-1] ^= 0x01  # corrupt the checksum byte after masking
    assert parse_aaa(REAL_COMPANY_ID, bytes(frame)) is None


def test_wrong_xor_key_is_rejected_by_checksum():
    """A device on a different company id must not decode as ours."""
    frame = _encode(REAL_COMPANY_ID, (1 << 31) | 72_350, AAA_TYPE_WEIGHT)
    assert parse_aaa(0x02AC, frame) is None


def test_short_frame_is_rejected():
    assert parse_aaa(REAL_COMPANY_ID, REAL_MFR_DATA[:11]) is None


def test_zero_weight_is_rejected():
    assert parse_aaa(REAL_COMPANY_ID, _encode(REAL_COMPANY_ID, 1 << 31, AAA_TYPE_WEIGHT)) is None


def test_field_ceiling_decodes():
    """The grams field is 18 bits, so 262.143 kg is the highest representable
    reading. Pinned so nobody adds an unreachable upper bound above it."""
    frame = _encode(REAL_COMPANY_ID, (1 << 31) | 0x3FFFF, AAA_TYPE_WEIGHT)
    reading = parse_aaa(REAL_COMPANY_ID, frame)
    assert reading is not None
    assert reading.weight_kg == 262.143


def test_unknown_frame_type_is_ignored():
    assert parse_aaa(REAL_COMPANY_ID, _encode(REAL_COMPANY_ID, 70_000, 0x11)) is None
