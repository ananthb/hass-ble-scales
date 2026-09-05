"""Constants for the BLE Scales integration."""

DOMAIN = "ble_scales"

CONF_PEOPLE = "people"
CONF_NAME = "name"
CONF_HEIGHT_CM = "height_cm"
CONF_AGE_YEARS = "age_years"
CONF_SEX = "sex"
CONF_EXPECTED_WEIGHT_KG = "expected_weight_kg"
CONF_WEIGHT_TOLERANCE_KG = "weight_tolerance_kg"
CONF_PERSON_ENTITY = "person_entity"

#: Half-width of the band around a person's expected weight used to claim a
#: reading. 5 kg is wide enough to absorb clothing, time of day and a few weeks
#: of drift, and narrow enough that two adults are usually separable. Where it
#: is not, presence breaks the tie and otherwise the reading is left unassigned.
DEFAULT_WEIGHT_TOLERANCE_KG = 5.0

#: A scale advertises for a few seconds around a weigh-in and then sleeps. If
#: nothing has arrived for this long the sensors go unavailable rather than
#: showing a stale weight forever.
ADVERTISEMENT_TIMEOUT_SECONDS = 300

#: How long a "weighing in next" button press stays valid. Long enough to walk
#: to the scale and for it to settle, short enough that a forgotten press does
#: not silently capture somebody else's weigh-in an hour later.
CLAIM_WINDOW_SECONDS = 300
