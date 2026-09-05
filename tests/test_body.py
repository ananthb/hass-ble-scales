"""Body composition tests.

These pin behaviour and internal consistency, NOT clinical accuracy. The
equations are published regressions; there is no ground truth to assert here,
so the tests check that the maths is self-consistent and that bad inputs are
refused rather than clamped into something that looks like a measurement.
"""

import pytest

from ble_scales.body import (
    SEX_FEMALE,
    SEX_MALE,
    Profile,
    basal_metabolic_rate,
    compute,
)

MALE = Profile(height_cm=178, age_years=38, sex=SEX_MALE)
FEMALE = Profile(height_cm=165, age_years=35, sex=SEX_FEMALE)


def test_profile_rejects_bad_sex():
    with pytest.raises(ValueError):
        Profile(height_cm=178, age_years=38, sex="other")


def test_profile_rejects_impossible_height():
    with pytest.raises(ValueError):
        Profile(height_cm=40, age_years=38, sex=SEX_MALE)


def test_mifflin_st_jeor_male_matches_hand_calculation():
    # 10*75 + 6.25*178 - 5*38 + 5 = 750 + 1112.5 - 190 + 5 = 1677.5 -> 1678
    assert basal_metabolic_rate(75.0, MALE) == 1678


def test_mifflin_st_jeor_female_matches_hand_calculation():
    # 10*62 + 6.25*165 - 5*35 - 161 = 620 + 1031.25 - 175 - 161 = 1315.25 -> 1315
    assert basal_metabolic_rate(62.0, FEMALE) == 1315


def test_composition_is_internally_consistent():
    result = compute(75.0, 500, MALE)
    assert result is not None
    # Fat and fat-free must partition body weight exactly.
    assert result.body_fat_kg + result.fat_free_mass_kg == pytest.approx(75.0, abs=0.02)
    assert result.body_fat_percent == pytest.approx(
        result.body_fat_kg / 75.0 * 100, abs=0.1
    )
    # Water is a fraction of fat-free mass, so it can never exceed it.
    assert result.total_body_water_kg < result.fat_free_mass_kg
    # Skeletal muscle is a subset of fat-free mass.
    assert result.skeletal_muscle_kg < result.fat_free_mass_kg


def test_bmi_matches_definition():
    result = compute(75.0, 500, MALE)
    assert result is not None
    assert result.bmi == pytest.approx(75.0 / 1.78**2, abs=0.05)


def test_sex_changes_the_result():
    same_body = Profile(height_cm=170, age_years=30, sex=SEX_MALE)
    other = Profile(height_cm=170, age_years=30, sex=SEX_FEMALE)
    a = compute(70.0, 500, same_body)
    b = compute(70.0, 500, other)
    assert a is not None and b is not None
    assert a.body_fat_percent != b.body_fat_percent


def test_higher_impedance_means_more_fat():
    """Directional sanity: impedance rises with fat, all else equal."""
    low = compute(75.0, 450, MALE)
    high = compute(75.0, 600, MALE)
    assert low is not None and high is not None
    assert high.body_fat_percent > low.body_fat_percent


def test_bmi_and_bmr_survive_a_missing_impedance():
    """Weight and impedance arrive in separate advertisements, so this is the
    normal state partway through a weigh-in -- not an error case."""
    result = compute(75.0, None, MALE)
    assert result is not None
    assert result.bmi == pytest.approx(23.7, abs=0.1)
    assert result.basal_metabolic_rate_kcal == 1678
    assert result.body_fat_percent is None
    assert result.fat_free_mass_kg is None


def test_absurd_impedance_keeps_bmi_but_drops_composition():
    result = compute(75.0, 1, MALE)
    assert result is not None
    assert result.bmi is not None
    assert result.body_fat_percent is None


def test_zero_weight_still_yields_nothing():
    assert compute(0.0, 500, MALE) is None
