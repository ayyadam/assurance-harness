"""Intent normalisation, equality, modal computation, and the relation check.

The metamorphic *relation* says what the variant's intent should be, given the
seed's intent and the transform applied:
  - invariance (v1): the intent is unchanged → expected == seed modal.
  - directional (v2): exactly one field changes predictably → expected == seed
    modal with that field's delta applied; everything else unchanged.

`expected_variant_key` is the single extension point: v1 returns the seed key
unchanged; v2 directional transforms will carry a delta this function applies.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time
from typing import Any

from ai_evaluation.evaluator import _norm_players
from ai_evaluation.metamorphic.transforms import Directional, Transform

INTENT_FIELDS = ("date", "period", "group_size", "players", "not_before", "not_after")

# A hashable, normalised view of a BookingIntent (or None if the call failed).
IntentKey = tuple | None


def _norm_time(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value.strftime("%H:%M")
    try:
        return datetime.strptime(str(value)[:5], "%H:%M").strftime("%H:%M")
    except ValueError:
        return str(value)


def intent_key(intent: dict | None) -> IntentKey:
    """A hashable, field-normalised key for an intent. Players are order-
    insensitive (reusing the eval's `_norm_players`); None means no intent."""
    if intent is None:
        return None
    return (
        str(intent.get("date") or ""),
        str(intent.get("period") or "any").lower().strip(),
        intent.get("group_size"),
        tuple(_norm_players(intent.get("players"))),
        _norm_time(intent.get("not_before")),
        _norm_time(intent.get("not_after")),
    )


def key_to_fields(key: IntentKey) -> dict[str, Any] | None:
    """Render a key back to a readable {field: value} dict for the report."""
    if key is None:
        return None
    return dict(zip(INTENT_FIELDS, key, strict=True))


def modal(intents: list[dict | None]) -> tuple[IntentKey, float]:
    """Return (modal_key, self_agreement) over N runs of one input.

    modal_key = most frequent intent; self_agreement = its share of the runs
    (1.0 = perfectly consistent, lower = the model is stochastic for this input)."""
    keys = [intent_key(i) for i in intents]
    counter = Counter(keys)
    modal_key, count = counter.most_common(1)[0]
    return modal_key, count / len(keys)


def expected_variant_key(seed_key: IntentKey, transform: Transform) -> IntentKey:
    """What the variant's intent *should* be under this transform's relation.

    v1: every transform is `invariance` → the seed key, unchanged.
    v2: a `directional` transform will carry an expected delta applied here."""
    if transform.kind == "invariance":
        return seed_key
    raise NotImplementedError(f"directional relations are v2 (transform kind={transform.kind!r})")


def relation_holds(seed_key: IntentKey, variant_key: IntentKey, transform: Transform) -> bool:
    """Did the variant satisfy the metamorphic relation for this transform?"""
    return variant_key == expected_variant_key(seed_key, transform)


def directional_expected_key(seed_key: IntentKey, d: Directional) -> IntentKey:
    """The expected variant key for a directional relation (v2): the seed's
    intent with the relation's field overrides applied, everything else
    unchanged. A directional violation is variant_modal != this."""
    fields = key_to_fields(seed_key)
    if fields is None:
        return None
    fields = {**fields, **d.expected}
    return tuple(fields[f] for f in INTENT_FIELDS)
