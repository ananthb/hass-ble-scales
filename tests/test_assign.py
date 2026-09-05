"""Assignment tests. The important ones are the refusals."""

from ble_scales.assign import Person, assign_reading

ANANTH = Person("Ananth", 178, 38, "male", 75.0, 5.0, "person.ananth")
PARTNER = Person("Partner", 165, 35, "female", 62.0, 5.0, "person.partner")
CLOSE = Person("Close", 170, 40, "male", 77.0, 5.0, "person.close")


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
