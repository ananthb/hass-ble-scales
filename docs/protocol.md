# AAA-series broadcast protocol

Captured from an `AAA044` unit (`A0:91:61:C8:0B:5D`) on 2026-09-05, through
Home Assistant's Bluetooth stack. Frame format is owed to
[openScale](https://github.com/oliexdev/openScale)'s `AAAxHandler` (GPL-3.0);
everything about impedance below is new, because openScale does not decode that
frame.

## Advertisement

```
02 01 04                              flags: BR/EDR not supported
03 03 B0 FF                           16-bit service UUID 0xFFB0
0F FF AC A0 <12 bytes>                manufacturer data, company id 0xA0AC
07 09 "AAA044"                        complete local name
```

The company id is **not** a vendor identifier being used as one. Its high byte
is the XOR key for the payload, so it varies between units. Never claim a device
on it alone.

## Manufacturer data

```
bytes 0..5    the advertiser's own MAC, reversed. Identifies the family shape,
              never the model -- every unit repeats its own address here.
bytes 6..11   payload, XOR-masked with (company_id >> 8) & 0xFF
```

Decoded payload:

```
[0..3]  u32 big-endian: bit31 = settled, bits 0..17 = value
[4]     frame type: 0xAD weight, 0xA6 impedance
[5]     checksum: sum(payload[0..4]) & 0x1F, compared on the low 5 bits
```

## Weight frames — confirmed

Verified against a real weigh-in. The settled frame differs from the sample
before it by exactly one bit:

```
a0 2d e4 32 0d b0  ->  00 8d 44 92 ad 10   settling, 83090 g
20 2d e4 32 0d b0  ->  80 8d 44 92 ad 10   settled,  83090 g
```

The 18-bit field is correct: the same bytes read as 16 bits give 17554, which
is not a plausible weight. It saturates at 262.143 kg, so there is no useful
upper sanity bound to apply — the checksum is the gate.

A weigh-in streams unstable frames as the reading climbs, then repeats the final
value once with bit 31 set:

```
00 8c 00 00 ad 19   stable=0      0 g   (nobody on it yet)
00 8d 0a 22 ad 06   stable=0  68130 g
00 8d 0e 50 ad 18   stable=0  69200 g
80 8d 44 92 ad 10   stable=1  83090 g   <- the one to record
```

## Impedance frames

The `0xA6` frame follows the **standard Chipsea broadcast layout**: impedance is
a `u16` big-endian at payload bytes 2..3, scaled by 10.

```
impedance_ohm = ((payload[2] << 8) | payload[3]) / 10
```

Two independent implementations agree on that field position for this chipset
family: openScale's `OkOkHandler` (`IDX_IMPEDANCE_MSB/LSB = 2/3` in its `0xC0`
variant) and BioScale's Chipsea broadcast decoder, which reads
`(data[2] << 8) | data[3]` and divides by 10.

**Do not reuse the weight frame's 18-bit mask here.** It spans bytes 1..3 and
drags in two bits of byte 1, which drifts between frames — it turns a raw 2
into 196610, a number plausible enough to be believed and one that silently
poisons every equation downstream.

### What a scale with no contact reports

Every frame captured from the AAA044 so far reads a raw of 2, i.e. 0.2 Ω:

```
02 12 00 02 a6 1c     idle
02 13 00 02 a6 1d     idle
02 14 00 02 a6 1e     idle
02 17 00 02 a6 01     immediately after a settled barefoot weigh-in
```

Byte 1 drifts (`0x12`…`0x17`) in a way that looks like a counter; bytes 2..3 are
`00 02` throughout, including immediately after a settled barefoot weigh-in.

That is the scale saying **BIA did not complete**, not that the field is
missing. These electrodes need bare, clean, slightly damp skin — dry or dirty
feet, or a dusty scale surface, and the measurement never runs. The frame is
still broadcast, with a raw at or near zero.

openScale never decoded this frame at all (*"impedance frame seen (ignored)"*,
*"protocol known but not implemented here"*), so a capture carrying a real value
is still worth contributing here when one turns up.

This integration reports no impedance below 100 Ω or above 1500 Ω, treating it
as no measurement. An adult whole-body value at these scales' single frequency
sits well inside that band, and feeding a near-zero into the BIA equations
produces a body fat percentage that looks entirely real.
