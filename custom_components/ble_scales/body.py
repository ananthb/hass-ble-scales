"""Body composition derived from weight, impedance and a person's profile.

WHAT THE SCALE ACTUALLY SENDS
-----------------------------
Two numbers: weight, and a single whole-body impedance at one frequency.
Nothing else. Every "body fat %", "muscle mass" or "metabolic age" you have
ever seen on a consumer scale's display or in its app is *computed* from those
two numbers plus your height, age and sex. The scale does not measure them.

WHY THESE EQUATIONS AND NOT THE VENDOR'S
----------------------------------------
openScale ports several vendors' proprietary regressions, but the ones that
reproduce a scale's display exactly (e.g. Fitdays/icomon WLA25) take TEN
impedance values from a multi-frequency, multi-segment scale. This family
broadcasts one impedance, so those fits cannot be evaluated here at all.

Rather than invent a fit, this module uses published, peer-reviewed
single-frequency BIA equations and cites each one. Consequences to be honest
about:

  * These numbers will NOT match the Meditive app. A different regression on
    the same impedance gives a different answer, and neither is a measurement.
  * They are useful as a TREND for one person on one scale. Absolute values
    from consumer BIA are not clinically meaningful, and the literature these
    equations come from says so itself.
  * Fields with no defensible published single-frequency equation are OMITTED,
    not guessed. That means no bone mass, no visceral fat, no metabolic age.
    An invented number that looks plausible is worse than an absent one.

Impedance here is treated as resistance (R). Single-frequency consumer scales
report a magnitude and do not expose reactance, so equations requiring Xc
(e.g. Kyle 2001) are not usable and are deliberately not approximated.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

SEX_MALE = "male"
SEX_FEMALE = "female"

#: Fraction of fat-free mass that is water in a euhydrated adult. Standard
#: hydration constant (Wang et al. 1999); used to derive total body water from
#: FFM rather than fitting water separately.
HYDRATION_OF_FFM = 0.732


@dataclass(frozen=True)
class Profile:
    """The person a reading belongs to. All three fields change the result."""

    height_cm: float
    age_years: int
    sex: str

    def __post_init__(self) -> None:
        if self.sex not in (SEX_MALE, SEX_FEMALE):
            raise ValueError(f"sex must be {SEX_MALE!r} or {SEX_FEMALE!r}")
        if not 100 <= self.height_cm <= 250:
            raise ValueError("height_cm out of plausible range")
        if not 5 <= self.age_years <= 120:
            raise ValueError("age_years out of plausible range")


@dataclass(frozen=True)
class BodyComposition:
    """Derived values. Every field is an estimate, not a measurement.

    The impedance-dependent fields are Optional because they genuinely are:
    weight and impedance arrive in SEPARATE advertisements, so there is a real
    window during every weigh-in where weight is known and impedance is not.
    BMI and BMR need no impedance at all, so they are populated from the first
    frame rather than made to wait for a number they never depended on.
    """

    bmi: float
    basal_metabolic_rate_kcal: int
    fat_free_mass_kg: float | None = None
    body_fat_kg: float | None = None
    body_fat_percent: float | None = None
    total_body_water_kg: float | None = None
    total_body_water_percent: float | None = None
    skeletal_muscle_kg: float | None = None
    skeletal_muscle_percent: float | None = None

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _bmi(weight_kg: float, height_cm: float) -> float:
    return weight_kg / (height_cm / 100.0) ** 2


def basal_metabolic_rate(weight_kg: float, profile: Profile) -> int:
    """Mifflin-St Jeor (1990) resting energy expenditure, kcal/day.

    Deliberately impedance-free: Mifflin-St Jeor outperforms Harris-Benedict in
    validation studies and needs only weight, height, age and sex, so BMR is
    still available for a weight-only reading with no impedance frame.
    """
    base = 10.0 * weight_kg + 6.25 * profile.height_cm - 5.0 * profile.age_years
    return round(base + (5 if profile.sex == SEX_MALE else -161))


def fat_free_mass(weight_kg: float, impedance: float, profile: Profile) -> float:
    """Fat-free mass in kg, Sun et al. (2003), Am J Clin Nutr 77(2):331-340.

    Derived from NHANES III on 1 829 men and 1 940 women, and chosen here
    because it is impedance-only: it needs resistance, height, weight and sex
    but no reactance, which single-frequency consumer scales cannot report.
    """
    h2r = profile.height_cm**2 / impedance
    if profile.sex == SEX_MALE:
        return -10.68 + 0.65 * h2r + 0.26 * weight_kg + 0.02 * impedance
    return -9.53 + 0.69 * h2r + 0.17 * weight_kg + 0.02 * impedance


def skeletal_muscle_mass(impedance: float, profile: Profile) -> float:
    """Appendicular skeletal muscle mass in kg, Janssen et al. (2000),
    J Appl Physiol 89(2):465-471. Validated against MRI on 388 adults.

    Note this is SKELETAL muscle specifically, which is a subset of fat-free
    mass and reads lower than the "muscle mass" a vendor app shows -- those
    usually report FFM minus bone, a different quantity entirely.
    """
    h2r = profile.height_cm**2 / impedance
    sex_term = 3.825 if profile.sex == SEX_MALE else 0.0
    return 0.401 * h2r + sex_term - 0.071 * profile.age_years + 5.102


def compute(
    weight_kg: float, impedance: float | None, profile: Profile
) -> BodyComposition | None:
    """Derive everything derivable from what is currently known.

    Returns None only when the weight itself is unusable. A missing or
    implausible impedance costs you the composition fields and nothing else --
    BMI and BMR are still returned, because neither ever needed impedance and
    withholding them would just be a bug that looks like caution.

    No BMI-based body-fat fallback is offered when impedance is absent. Those
    estimates are barely better than guessing from weight alone, and presenting
    one in the same field that sometimes holds a BIA estimate would silently
    mix two very different things in one sensor's history.
    """
    if weight_kg <= 0:
        return None

    basics = {
        "bmi": round(_bmi(weight_kg, profile.height_cm), 1),
        "basal_metabolic_rate_kcal": basal_metabolic_rate(weight_kg, profile),
    }

    if impedance is None or impedance <= 0:
        return BodyComposition(**basics)

    ffm = fat_free_mass(weight_kg, impedance, profile)
    # A nonsensical impedance (bare feet not making contact, a child on an
    # adult profile) can drive FFM past body weight, which would yield negative
    # fat. Refuse rather than clamp: a clamped 0 % reads as a real measurement.
    if not 0 < ffm < weight_kg:
        return BodyComposition(**basics)

    fat_kg = weight_kg - ffm
    tbw_kg = ffm * HYDRATION_OF_FFM
    smm_kg = skeletal_muscle_mass(impedance, profile)
    if not 0 < smm_kg < ffm:
        return BodyComposition(**basics)

    return BodyComposition(
        **basics,
        fat_free_mass_kg=round(ffm, 2),
        body_fat_kg=round(fat_kg, 2),
        body_fat_percent=round(fat_kg / weight_kg * 100.0, 1),
        total_body_water_kg=round(tbw_kg, 2),
        total_body_water_percent=round(tbw_kg / weight_kg * 100.0, 1),
        skeletal_muscle_kg=round(smm_kg, 2),
        skeletal_muscle_percent=round(smm_kg / weight_kg * 100.0, 1),
    )
