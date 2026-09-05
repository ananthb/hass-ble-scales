# Changelog

## 0.5.0

- Decode impedance with the standard Chipsea broadcast layout: `u16` big endian
  at payload bytes 2..3, divided by 10. It was previously read with the weight
  frame's 18-bit mask, which turned a raw 2 into 196610 Ω.
- Body fat, fat-free mass, skeletal muscle, body water and raw impedance are
  back. They stay unknown until a weigh-in completes a BIA measurement, which
  needs bare, clean, slightly damp feet.

## 0.4.0

- No per-person device. Entities live on the scale device with the person's name
  in the entity name, so the integration no longer renders something that looks
  like a competing Home Assistant person.
- Added a *Cancel weigh-in* button.
- Recorded the frame format in `docs/protocol.md`, including the settled weight
  frame that differs from the sample before it by exactly one bit.

## 0.3.0

- Every measurement belongs to a person. A single shared weight entity
  interleaved everyone into one history, making its long-term statistics
  meaningless.
- Setup is now: pick yourself from Home Assistant's people, then stand on the
  scale. The usual weight is measured rather than typed. Manual entry remains
  for people who are not in Home Assistant.
- Height, age and sex are optional; without them you still get weight, BMI, BMR
  and assignment.

## 0.2.0

- Setup no longer requires the scale to be advertising — enter its Bluetooth
  address by hand.
- People are configured during initial setup rather than only afterwards.
- BMI and basal metabolic rate no longer wait for an impedance frame; neither
  ever depended on one.
- Added a *"weighing in"* button per person, which overrides weight matching.

## 0.1.0

- First release. Reads AAA-series Chipsea broadcast scales passively, assigns
  readings to people by weight, and derives body composition from published BIA
  equations.
