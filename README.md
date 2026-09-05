# hass-ble-scales

Home Assistant integration for broadcast BLE bathroom scales. It reads the
weight straight out of the Bluetooth advertisement — no pairing, no connection,
no vendor app, no cloud — and gives each person their own weight, body
composition and BMI.

## Install

Add `https://github.com/ananthb/hass-ble-scales` as a custom repository in
[HACS](https://hacs.xyz), category **Integration**, then restart Home Assistant.

## Configure

Add the integration, then pick yourself from the people Home Assistant already
knows and stand on the scale — your usual weight is measured, not typed. Height,
age and sex are optional and only affect body composition.

Readings are matched to people by weight; where two people are too close to
separate, press their *"weighing in"* button before stepping on.

> If weight and BMI work but body fat and muscle stay unknown, the scale did not
> complete an impedance measurement. Wipe the plate and stand on it barefoot
> with slightly damp feet.

## Supported scales

| Family | Advertised name | Service | Status |
|---|---|---|---|
| AAA-series (Chipsea) | `AAA044` | `0xFFB0` | verified against hardware |
| AAA-series (Chipsea) | `AAA002`, `AAA007`, `AAA013` | `0xFFB0` | same frame format, untested |

Sold under many brand names — Meditive among them. Any scale on service
`0xFFB0` is offered for setup only if its advertisement parses and its checksum
validates, so a device using that service with a different frame format is
declined rather than adopted and misread.

If yours is not listed, open an issue with a capture — adding a family is a
parser function and one registry entry in
[`parser.py`](custom_components/ble_scales/parser.py).

## Notes

- [`docs/protocol.md`](docs/protocol.md) — the frame format, with captures.
- [`body.py`](custom_components/ble_scales/body.py) — which published equations
  the body composition uses, and why those numbers are a trend rather than a
  measurement.

Protocol decoding is owed to [openScale](https://github.com/oliexdev/openScale).

## Licence

GPL-3.0-only. See [`LICENSE`](LICENSE).
