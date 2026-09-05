"""Per-person routing, tested without Home Assistant.

`apply_reading` is deliberately transport-agnostic so this is possible: it
takes a decoded frame and nothing else. These tests cover the thing most likely
to corrupt data -- a reading landing on the wrong person, or on everybody.
"""

from ble_scales.assign import Person
from ble_scales.parser import ScaleReading


def _make(people):
    import sys
    import types

    # Stub the Home Assistant modules the coordinator imports at module scope.
    for name in ("homeassistant", "homeassistant.components",
                 "homeassistant.core", "homeassistant.util"):
        sys.modules.setdefault(name, types.ModuleType(name))
    bt = types.ModuleType("homeassistant.components.bluetooth")
    bt.BluetoothServiceInfoBleak = object
    bt.BluetoothChange = object
    bt.BluetoothScanningMode = types.SimpleNamespace(ACTIVE="active")
    bt.async_register_callback = lambda *a, **k: (lambda: None)
    sys.modules["homeassistant.components.bluetooth"] = bt
    sys.modules["homeassistant.components"].bluetooth = bt
    core = sys.modules["homeassistant.core"]
    core.HomeAssistant = object
    core.callback = lambda f: f
    dt = types.ModuleType("homeassistant.util.dt")
    import datetime as _dt
    dt.utcnow = lambda: _dt.datetime(2026, 9, 5, 12, 0, 0, tzinfo=_dt.timezone.utc)
    sys.modules["homeassistant.util.dt"] = dt
    sys.modules["homeassistant.util"].dt = dt

    from ble_scales.coordinator import ScaleCoordinator

    c = ScaleCoordinator.__new__(ScaleCoordinator)
    from ble_scales.coordinator import PersonState, ScaleState

    c.hass = None
    c.address = "AA:BB:CC:DD:EE:FF"
    c.people = people
    c.state = ScaleState(people={p.name: PersonState() for p in people})
    c._listeners = []
    c._unsub = None
    c._pending_person = None
    c._claim = None
    c._is_home = lambda: {}
    return c


A = Person(name="A", expected_weight_kg=75.0, weight_tolerance_kg=3.0,
           height_cm=178, age_years=38, sex="male")
B = Person(name="B", expected_weight_kg=62.0, weight_tolerance_kg=3.0,
           height_cm=165, age_years=35, sex="female")


def test_weight_lands_only_on_the_matching_person():
    c = _make([A, B])
    c.apply_reading(ScaleReading(weight_kg=75.4, stable=True))
    assert c.person_state("A").weight_kg == 75.4
    assert c.person_state("B").weight_kg is None


def test_impedance_follows_the_person_the_weight_was_assigned_to():
    c = _make([A, B])
    c.apply_reading(ScaleReading(weight_kg=62.2, stable=True))
    c.apply_reading(ScaleReading(impedance=520))
    assert c.person_state("B").impedance == 520
    assert c.person_state("A").impedance is None
    assert c.person_state("B").body is not None
    assert c.person_state("B").body.body_fat_percent is not None


def test_unassigned_reading_touches_nobody():
    c = _make([A, B])
    c.apply_reading(ScaleReading(weight_kg=100.0, stable=True))
    assert c.person_state("A").weight_kg is None
    assert c.person_state("B").weight_kg is None
    assert "outside every configured weight band" in c.state.assignment_reason


def test_impedance_without_a_prior_weight_is_dropped():
    """An orphan impedance frame must not attach itself to whoever weighed in
    last -- that would pair one person's impedance with another's weight."""
    c = _make([A, B])
    c.apply_reading(ScaleReading(impedance=500))
    assert c.person_state("A").impedance is None
    assert c.person_state("B").impedance is None


def test_new_weigh_in_clears_the_previous_impedance():
    c = _make([A])
    c.apply_reading(ScaleReading(weight_kg=75.0, stable=True))
    c.apply_reading(ScaleReading(impedance=500))
    assert c.person_state("A").impedance == 500
    c.apply_reading(ScaleReading(weight_kg=75.6, stable=True))
    assert c.person_state("A").impedance is None


def test_button_claim_routes_to_the_claimed_person():
    c = _make([A, B])
    c._claim = ("B", float("inf"))
    c.apply_reading(ScaleReading(weight_kg=75.2, stable=True))
    assert c.person_state("B").weight_kg == 75.2
    assert c.person_state("A").weight_kg is None
