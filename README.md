# hass-ble-scales

Home Assistant integration for **broadcast** BLE bathroom scales — the
Chipsea/AAA-series units sold under many brand names, Meditive among them. Reads the weight straight out of the Bluetooth advertisement: no
pairing, no connection, no vendor app, no cloud.

Install through HACS as a custom repository, category **Integration**.

## Why passive matters

These scales put the reading in the advertisement itself. This integration
never opens a GATT connection, which is not merely simpler:

- It cannot occupy one of an ESPHome proxy's three connection slots, so it
  cannot starve the other Bluetooth devices sharing that proxy.
- It works through any adapter or proxy Home Assistant already has.
- It works on Home Assistant **Container** as well as OS — it is a HACS
  integration, not an add-on, so it needs no Supervisor.

## What it gives you

**Every measurement belongs to a person.** Each configured person becomes their
own device, with their own weight, impedance, BMI, body fat (% and kg),
fat-free mass, skeletal muscle, body water, BMR, last-measured timestamp and a
*"weighing in"* button.

There is no generic weight sensor, and that is deliberate: one shared entity
would interleave everybody who steps on the scale into a single history, and
its long-term statistics would then describe who weighed in most recently
rather than anybody's actual weight.

The scale device carries only what is about the scale — last measurement time,
signal strength, and why the last reading was or was not assigned.

## Read this before trusting the body-composition numbers

**The scale measures two things: weight and one whole-body impedance.** Nothing
else. Every body-fat or muscle figure — on this integration, in the vendor app,
on the scale's own display — is *computed* from those two numbers plus your
height, age and sex.

This integration uses published, peer-reviewed single-frequency BIA equations
and cites each one in [`body.py`](custom_components/ble_scales/body.py):

- **Fat-free mass** — Sun et al. (2003), *Am J Clin Nutr* 77(2):331-340, from
  NHANES III. Chosen because it needs only resistance, and consumer scales
  cannot report reactance.
- **Skeletal muscle mass** — Janssen et al. (2000), *J Appl Physiol*
  89(2):465-471, validated against MRI.
- **Basal metabolic rate** — Mifflin-St Jeor (1990). Needs no impedance, so it
  works from a weight-only reading.
- **Total body water** — derived from fat-free mass at the standard 73.2 %
  hydration constant.

Three consequences, stated plainly:

1. **These will not match your vendor app.** A different regression over the
   same impedance gives a different answer. Neither is a measurement.
2. **They are a trend, not a truth.** Useful for one person on one scale over
   time. Absolute values from consumer BIA are not clinically meaningful.
3. **Missing fields are missing on purpose.** No bone mass, no visceral fat, no
   metabolic age. There is no defensible published single-frequency equation
   for them, and a plausible-looking invented number is worse than none.

Vendor-exact algorithms do exist — openScale ports several — but the ones that
reproduce a display exactly take *ten* impedances from a multi-frequency,
multi-segment scale. This family broadcasts one, so they cannot be used here.

## Assigning readings to people

The scale broadcasts anonymously, so this is inference. Three signals, in order:

0. **Press your button.** Each configured person gets a *"weighing in"* button.
   Press it and the next reading within five minutes is yours, no matter what
   the weight says. Put them on a dashboard or a tablet by the scale. This beats
   every inference below and is not second-guessed — someone saying who they are
   is better evidence than a regression over their last known weight.
1. **Weight band** — a reading within your configured tolerance (default 5 kg)
   of your expected weight is yours.
2. **Presence** — if several people match on weight, those whose linked
   `person` entity is not home are dropped.

If it is still ambiguous, the reading is left **unassigned** and the
`Assignment reason` sensor says why. This is deliberate: picking the nearest
match would silently corrupt the history of two people at once, and nothing
downstream could detect it. An unassigned reading is a nuisance; a
misattributed one is data loss.

### Setting people up

The quick path is the default: **pick yourself from the people Home Assistant
already knows, then stand on the scale.** Your usual weight is read straight
off it, so there is nothing to type. Height, age and sex are offered on the same
screen, all optional — fill them in for body composition, skip them for weight
only, add them later from the options.

*Add manually* exists for someone who is not a person in Home Assistant, such as
a guest or a child without an account.

Home Assistant's `person` entities cannot store height, age or sex — the schema
is closed to `name`, `user_id`, `device_trackers` and `picture` — so those live
with this integration, keyed to the person's entity id.

People are configured **during initial setup**, and can be added, edited or
removed later under the integration's options. Height, age and sex are what turn
a weight into body composition; with nobody configured you get weight and
impedance only, and the `Assignment reason` sensor will say so.

BMI and basal metabolic rate need no impedance, so they appear as soon as a
weight arrives for a known person. The BIA-derived fields wait for the impedance
frame, which is a separate advertisement.

The scale does not have to be awake to set this up: if nothing is advertising,
the flow asks for the Bluetooth address directly.

## Supported scales

Currently the **AAA-series** broadcast family: service `0xFFB0`, manufacturer
data of at least 12 bytes carrying the MAC reversed plus a six-byte XOR-masked
payload. Verified against an `AAA044` unit.

The manifest claims the whole `0xFFB0` service, which other unrelated scale
families also use, so the config flow **parses and checksums the advertisement
before adopting a device** and refuses anything it cannot decode. That is
deliberate: silently adopting a device and reporting a confidently wrong weight
is the worst possible failure here.

Adding a family means a parser function and one registry entry in
[`parser.py`](custom_components/ble_scales/parser.py). Captures welcome.

## Credits

Protocol decoding is owed to [openScale](https://github.com/oliexdev/openScale)
(GPL-3.0), whose `AAAxHandler` documents this family's framing. AGPL-3.0 and
GPL-3.0 are mutually compatible via section 13 of each.

For a broader set of scales with a different architecture — a Home Assistant
*add-on* covering some 40 families — see
[ble-scale-sync](https://github.com/KristianP26/ble-scale-sync). It requires
Supervisor, so it does not run on Home Assistant Container, and it does not
currently cover this AAA-series family.

## Licence

AGPL-3.0-only. See [`LICENSE`](LICENSE).
