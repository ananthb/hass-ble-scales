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

## Impedance frames — the broadcast carries none

The `0xA6` frame exists and its checksum validates, but **it carries no
measurement.** Every frame captured across a full session — idle, settling, and
a settled barefoot weigh-in — has bytes 2..3 constant:

```
02 12 00 02 a6 1c     idle
02 13 00 02 a6 1d     idle
02 14 00 02 a6 1e     idle
02 17 00 02 a6 01     immediately after a settled barefoot weigh-in
```

Byte 1 drifts (`0x12`…`0x17`) in a way that looks like a counter. Bytes 2..3 are
`00 02` in every frame. A constant across a real barefoot measurement is not
what a wrong byte offset looks like — a wrong offset gives varying garbage.

Two decoding notes for anyone else trying this:

- **Do not reuse the weight frame's 18-bit mask here.** It drags in two bits
  from the drifting byte 1 and turns 2 into 196610, which looks enough like a
  real number to be believed.
- openScale's handler decodes weight and explicitly declines this frame:
  *"impedance frame seen (ignored)"*, *"protocol known but not implemented
  here"*. There is no reference implementation to check against.

**The vendor Android app does display body composition for this scale.** Since
the broadcast demonstrably does not carry impedance, the app must obtain it
another way — almost certainly over a GATT connection, as these units advertise
`connectable: true` and expose the `0xFFB0` service. That is the open question,
and settling it needs a BLE client within range of the scale.

Until then this integration reports only what the broadcast actually contains:
weight, plus BMI and basal metabolic rate, which are computed from weight,
height, age and sex and never needed impedance.
