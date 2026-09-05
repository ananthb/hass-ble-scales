# Changelog

## 0.5.0

- Body fat, fat-free mass, skeletal muscle, body water and impedance now work.
  They stay unknown until the scale completes an impedance measurement, which
  needs bare, clean, slightly damp feet — dry skin or a dusty plate and only
  weight, BMI and BMR will read.

## 0.4.0

- Added a *Cancel weigh-in* button, for when you claim a weigh-in and then
  someone else steps on the scale.
- Entities no longer sit on a separate per-person device, so the integration
  stops looking like it has created a second copy of each person. **Entity IDs
  changed** — remove and re-add the scale.

## 0.3.0

- Each person now has their own weight and body composition entities. A single
  shared weight entity mixed everybody into one history, which made its graphs
  and statistics meaningless. **Entity IDs changed** — remove and re-add the
  scale.
- Setup is now: pick yourself from Home Assistant's people and stand on the
  scale. Your usual weight is measured rather than typed. Manual entry remains
  for anyone who is not a person in Home Assistant.
- Height, age and sex are optional. Without them you still get weight, BMI,
  basal metabolic rate and per-person matching.

## 0.2.0

- The scale no longer has to be awake to set it up — enter its Bluetooth
  address by hand. These scales sleep between weigh-ins, so the device list was
  usually empty.
- People are set up when you add the integration, rather than only afterwards.
- BMI and basal metabolic rate now appear as soon as a weight arrives, instead
  of waiting for an impedance reading they never needed.
- Added a *"weighing in"* button per person: press yours and the next reading
  is yours, whatever the weight says.

## 0.1.0

- First release. Reads AAA-series broadcast scales, matches readings to people
  by weight, and derives body composition.
