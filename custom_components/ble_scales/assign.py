"""Deciding whose reading this is.

The scale broadcasts anonymously. It has no idea who stood on it, so every
assignment is inference and every inference can be wrong. The cost of being
wrong is asymmetric and worth stating: a misattributed weight silently
corrupts the history of BOTH people, and nothing downstream can detect it. An
unassigned reading is merely an inconvenience someone can resolve in the UI.

So the rule throughout this module is: assign only when the evidence is
unambiguous, and otherwise return nobody. It never falls back to "closest
match wins" when two candidates are plausible.

Three signals, applied in order:

  0. An explicit claim -- somebody pressed "weighing in next" on their button.
     This beats everything else and is not second-guessed: a person saying who
     they are is better evidence than any inference over their weight, and if
     the claim were overridden by a weight band the button would be useless
     precisely when it is needed (two people of similar weight).
  1. Weight band -- a person claims a reading within `tolerance` of their
     expected weight. Works with no other integration set up.
  2. Presence -- if the band leaves more than one candidate, drop those whose
     linked `person` entity is not home. This breaks the common two-adult tie
     without needing the weights to be far apart.

Deliberately NOT implemented: picking the nearest candidate when several
remain. That is the one heuristic that turns an honest "I don't know" into a
confident corruption of someone's history.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Person:
    """A configured user of the scale.

    Height, age and sex are Optional because the fast way to add someone is to
    stand on the scale and pick them from a list -- at which point their weight
    is known and nothing else is. Without those three, this person still gets
    assignment, a weigh-in button and a weight history; they just do not get
    body composition, which cannot be derived without them. Making them
    mandatory would mean a form full of typing before the integration did
    anything at all.
    """

    name: str
    expected_weight_kg: float
    weight_tolerance_kg: float
    height_cm: float | None = None
    age_years: int | None = None
    sex: str | None = None
    person_entity: str | None = None

    @property
    def can_derive_composition(self) -> bool:
        return None not in (self.height_cm, self.age_years, self.sex)


@dataclass(frozen=True)
class Assignment:
    """Who a reading was given to, and why -- the reason is surfaced in the UI
    so an unassigned reading explains itself instead of just failing."""

    person: Person | None
    reason: str

    @property
    def assigned(self) -> bool:
        return self.person is not None


def assign_reading(
    weight_kg: float,
    people: list[Person],
    is_home: dict[str, bool] | None = None,
    claimed_name: str | None = None,
) -> Assignment:
    """Pick the person a weight belongs to, or nobody.

    `is_home` maps a person_entity id to whether that entity is currently home.
    Entities missing from the mapping are treated as "unknown", which counts as
    present -- absence of evidence must not silently exclude someone.

    `claimed_name` is set when someone pressed their weigh-in button recently.
    The caller is responsible for expiring the claim; by the time it reaches
    here it is taken at face value.
    """
    if not people:
        return Assignment(None, "no people configured")

    if claimed_name is not None:
        claimed = next((p for p in people if p.name == claimed_name), None)
        if claimed is not None:
            # Deliberately NOT sanity-checked against the weight band. Someone
            # who just pressed their own button knows better than a regression
            # over their last known weight, and rejecting the claim on a weight
            # mismatch would break the exact case the button exists for.
            return Assignment(claimed, "claimed by button press")

    in_band = [
        p for p in people if abs(weight_kg - p.expected_weight_kg) <= p.weight_tolerance_kg
    ]

    if not in_band:
        return Assignment(
            None,
            f"{weight_kg:.1f} kg is outside every configured weight band",
        )

    if len(in_band) == 1:
        return Assignment(in_band[0], "matched a single weight band")

    # Ambiguous on weight alone. Presence is allowed to narrow it, never to
    # widen it: only candidates already in the band are considered.
    if is_home:
        present = [
            p
            for p in in_band
            if p.person_entity is None or is_home.get(p.person_entity, True)
        ]
        if len(present) == 1:
            return Assignment(present[0], "weight band tied, resolved by presence")
        if not present:
            return Assignment(
                None, "weight matched, but nobody in the band is home"
            )
        in_band = present

    names = ", ".join(sorted(p.name for p in in_band))
    return Assignment(
        None,
        f"ambiguous between {names} -- assign manually to avoid corrupting history",
    )
