"""Advertisement parsers for broadcast BLE bathroom scales.

Every scale family here puts its reading in the BLE advertisement, so nothing
in this module connects to anything. Parsers are pure functions over
manufacturer data: given the company id and its payload, either return a
reading or return None. That keeps them trivially testable against captured
frames, and it is why this integration can never hold a GATT connection slot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# AAA-series (Chipsea-style) broadcast scales -------------------------------
#
# Protocol per openScale's AAAxHandler (GPL-3.0), verified against a live
# AAA044 unit. Manufacturer data is at least 12 bytes:
#
#   bytes 0..5   the advertiser's own MAC, reversed. Ignored -- every unit in
#                the family repeats its own address here, so it identifies the
#                family shape but never the model.
#   bytes 6..11  payload, XOR-masked with the HIGH BYTE OF THE COMPANY ID.
#
# The company id is not a real SIG assignment being used as one: its high byte
# is the XOR key, so it varies per unit (0xA0AC on the unit captured here). That
# is why this parser takes the company id as an argument rather than matching a
# constant, and why the company id alone must never be used to claim a device.
#
# Decoded payload:
#   [0..3]  u32 big-endian:  bit31 = stable/final, bits 0..17 = grams
#   [4]     frame type:      0xAD weight, 0xA6 impedance
#   [5]     checksum:        sum(payload[0..4]) & 0x1F, compared on low 5 bits

AAA_MIN_LEN = 12
AAA_TYPE_WEIGHT = 0xAD
AAA_TYPE_IMPEDANCE = 0xA6
AAA_GRAMS_MASK = 0x3FFFF
# The grams field is 18 bits, so it saturates at 262.143 kg on its own. An
# upper sanity guard would be unreachable code, and a tighter one (a "nobody
# weighs that much" limit) would silently discard real readings from heavy
# users, so there is deliberately no maximum here. The checksum is the gate.


@dataclass(frozen=True)
class ScaleReading:
    """One decoded advertisement."""

    weight_kg: float | None = None
    impedance: int | None = None
    stable: bool = False

    @property
    def is_empty(self) -> bool:
        return self.weight_kg is None and self.impedance is None


def parse_aaa(company_id: int, data: bytes) -> ScaleReading | None:
    """Decode an AAA-series advertisement payload.

    Returns None when the frame is not AAA-shaped or fails its checksum, which
    is the same thing as "not ours" -- callers must not treat None as an error.
    """
    if len(data) < AAA_MIN_LEN:
        return None

    xor_key = (company_id >> 8) & 0xFF
    payload = bytes(b ^ xor_key for b in data[6:12])

    if (sum(payload[0:5]) & 0x1F) != (payload[5] & 0x1F):
        return None

    value = int.from_bytes(payload[0:4], "big")
    stable = bool((value >> 31) & 1)
    raw = value & AAA_GRAMS_MASK
    frame_type = payload[4]

    if frame_type == AAA_TYPE_WEIGHT:
        if raw == 0:
            return None
        return ScaleReading(weight_kg=raw / 1000.0, stable=stable)

    if frame_type == AAA_TYPE_IMPEDANCE:
        if raw == 0:
            return None
        return ScaleReading(impedance=raw, stable=stable)

    return None


# Family registry -----------------------------------------------------------
#
# Adding a family means adding a parser above and one entry here. Claiming is
# done on the advertised SERVICE UUID, never on the company id alone -- see the
# note above about the id carrying a key rather than a vendor.

Parser = Callable[[int, bytes], "ScaleReading | None"]

FAMILY_AAA = "aaa"

SERVICE_UUID_FFB0 = "0000ffb0-0000-1000-8000-00805f9b34fb"

PARSERS: dict[str, Parser] = {FAMILY_AAA: parse_aaa}

SERVICE_FAMILIES: dict[str, str] = {SERVICE_UUID_FFB0: FAMILY_AAA}
