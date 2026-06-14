"""Fast, deterministic unit tests for the metamorphic layer — no SUT, no LLM, so
they run in the standard pytest gate. They assert the two things the metamorphic
*method* relies on being correct:

  1. the transforms are meaning-preserving BY CONSTRUCTION (a transform that
     silently changed meaning would manufacture false invariance violations);
  2. intent normalisation / equality / modal reduction behave (the machinery
     that turns N noisy runs into a comparable verdict).
"""

import random

from ai_evaluation.metamorphic.relations import (
    intent_key,
    key_to_fields,
    modal,
    relation_holds,
)
from ai_evaluation.metamorphic.transforms import TRANSFORMS, _casing, _filler, _synonym, _typo, _whitespace

RNG = random.Random(0)


# ── transforms preserve meaning by construction ──────────────────────────────


def test_casing_changes_only_case():
    variants = _casing("Book a 4-ball Saturday morning", RNG)
    assert variants == ["BOOK A 4-BALL SATURDAY MORNING", "book a 4-ball saturday morning"]


def test_whitespace_is_cosmetic_only():
    (variant,) = _whitespace("two of us tomorrow", RNG)
    # same tokens, just re-spaced — strip-and-split must recover the original words
    assert variant.split() == "two of us tomorrow".split()
    assert "  " in variant  # actually doubled the spacing


def test_filler_wraps_without_losing_the_request():
    text = "a 4-ball on Sunday"
    prefixed, suffixed = _filler(text, random.Random(1))
    assert prefixed.endswith(text) and prefixed != text
    assert suffixed.startswith(text) and suffixed != text


def test_typo_only_touches_a_non_semantic_word_and_is_a_transposition():
    text = "fancy a knock this Saturday morning"
    (variant,) = _typo(text, random.Random(2))
    orig_words, new_words = text.split(" "), variant.split(" ")
    assert len(orig_words) == len(new_words)
    changed = [(o, n) for o, n in zip(orig_words, new_words, strict=True) if o != n]
    assert len(changed) == 1  # exactly one word perturbed
    o, n = changed[0]
    assert sorted(o) == sorted(n)  # a transposition: same letters, reordered
    # semantic tokens must be untouched
    assert "Saturday" in new_words and "morning" in new_words


def test_typo_returns_empty_when_no_eligible_word():
    # all tokens are protected / too short / proper nouns -> nothing safe to typo
    assert _typo("two on Sunday am", random.Random(3)) == []


def test_synonym_substitutes_a_curated_phrase_only_when_present():
    assert _synonym("a 4-ball on Sunday", RNG) == ["a foursome on Sunday"]
    assert _synonym("just me, Saturday", RNG) == []  # no golf-domain phrase to swap


def test_registry_is_all_invariance_in_v1():
    assert {t.kind for t in TRANSFORMS} == {"invariance"}


# ── intent normalisation / equality / modal ──────────────────────────────────


def test_intent_key_normalises_period_and_players_order():
    a = intent_key(
        {
            "date": "2026-06-13",
            "period": "Morning",
            "group_size": 3,
            "players": ["Sarah", "Dave"],
            "not_before": None,
            "not_after": None,
        }
    )
    b = intent_key(
        {
            "date": "2026-06-13",
            "period": "morning",
            "group_size": 3,
            "players": ["Dave", "sarah"],
            "not_before": None,
            "not_after": None,
        }
    )
    assert a == b  # case + player order are not meaningful differences


def test_intent_key_normalises_time_strings():
    k = intent_key({"date": "2026-06-13", "group_size": 1, "players": [], "not_before": "09:00:00", "not_after": ""})
    fields = key_to_fields(k)
    assert fields["not_before"] == "09:00"
    assert fields["not_after"] is None


def test_intent_key_none_for_failed_call():
    assert intent_key(None) is None


def test_modal_picks_most_frequent_with_agreement():
    morning = {"date": "2026-06-13", "period": "morning", "group_size": 1, "players": []}
    afternoon = {"date": "2026-06-13", "period": "afternoon", "group_size": 1, "players": []}
    modal_key, agreement = modal([morning, morning, afternoon])
    assert modal_key == intent_key(morning)
    assert agreement == 2 / 3


def test_relation_holds_is_equality_for_invariance():
    casing = next(t for t in TRANSFORMS if t.name == "casing")
    k1 = intent_key({"date": "2026-06-13", "period": "any", "group_size": 4, "players": []})
    k2 = intent_key({"date": "2026-06-13", "period": "any", "group_size": 2, "players": []})
    assert relation_holds(k1, k1, casing) is True
    assert relation_holds(k1, k2, casing) is False
