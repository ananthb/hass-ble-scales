"""Assignment tests. The important ones are the refusals."""

from ble_scales.assign import Person, assign_reading

def _person(name, weight, entity, **kw):
    """Keyword-only, so a change to Person's field order cannot silently
    re-map these fixtures onto the wrong attributes."""
    return Person(
        name=name,
        expected_weight_kg=weight,
        weight_tolerance_kg=kw.pop("tolerance", 5.0),
        person_entity=entity,
        **kw,
    )


ANANTH = _person("Ananth", 75.0, "person.ananth", height_cm=178, age_years=38, sex="male")
PARTNER = _person("Partner", 62.0, "person.partner", height_cm=165, age_years=35, sex="female")
CLOSE = _person("Close", 77.0, "person.close", height_cm=170, age_years=40, sex="male")
#: Added the quick way: weight measured off the scale, nothing else known.
QUICK = _person("Quick", 90.0, "person.quick")


def test_single_band_match():
    result = assign_reading(75.2, [ANANTH, PARTNER])
    assert result.person is ANANTH


def test_outside_every_band_is_unassigned():
    result = assign_reading(100.0, [ANANTH, PARTNER])
    assert result.person is None
    assert "outside every configured weight band" in result.reason


def test_ambiguous_weights_refuse_to_guess():
    """Two overlapping bands and no presence data: must NOT pick the nearest."""
    result = assign_reading(76.0, [ANANTH, CLOSE])
    assert result.person is None
    assert "ambiguous" in result.reason
    assert "Ananth" in result.reason and "Close" in result.reason


def test_presence_breaks_a_tie():
    result = assign_reading(
        76.0, [ANANTH, CLOSE], {"person.ananth": True, "person.close": False}
    )
    assert result.person is ANANTH
    assert "presence" in result.reason


def test_nobody_home_is_unassigned():
    result = assign_reading(
        76.0, [ANANTH, CLOSE], {"person.ananth": False, "person.close": False}
    )
    assert result.person is None


def test_unknown_presence_counts_as_present():
    """A missing person entity must not silently exclude someone."""
    result = assign_reading(76.0, [ANANTH, CLOSE], {"person.close": False})
    assert result.person is ANANTH


def test_no_people_configured():
    result = assign_reading(75.0, [])
    assert result.person is None
    assert "no people configured" in result.reason


def test_button_claim_wins_outright():
    """A claim must beat weight inference, including a confident single match."""
    result = assign_reading(62.0, [ANANTH, PARTNER], claimed_name="Ananth")
    assert result.person is ANANTH
    assert "claimed by button" in result.reason


def test_claim_wins_where_weight_would_be_ambiguous():
    """The case the button exists for: two people of similar weight."""
    result = assign_reading(76.0, [ANANTH, CLOSE], claimed_name="Close")
    assert result.person is CLOSE


def test_claim_wins_over_absent_presence():
    """Pressing your own button while marked away still claims the reading."""
    result = assign_reading(
        76.0,
        [ANANTH, CLOSE],
        {"person.ananth": False, "person.close": False},
        claimed_name="Ananth",
    )
    assert result.person is ANANTH


def test_claim_for_unknown_person_falls_back_to_inference():
    """A stale claim naming someone since deleted must not strand the reading."""
    result = assign_reading(75.2, [ANANTH, PARTNER], claimed_name="Ghost")
    assert result.person is ANANTH
    assert "weight band" in result.reason


def test_claim_with_nobody_configured_is_still_unassigned():
    assert assign_reading(75.0, [], claimed_name="Ananth").person is None


def test_person_without_body_details_still_assigns():
    """The quick path stores only a weight, and that must be enough to be
    recognised -- composition is what is lost, not identity."""
    result = assign_reading(90.5, [QUICK])
    assert result.person is QUICK
    assert QUICK.can_derive_composition is False


def test_person_with_details_can_derive():
    assert ANANTH.can_derive_composition is True
