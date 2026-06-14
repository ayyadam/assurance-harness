"""Meaning-preserving text transforms for metamorphic invariance testing.

Each transform turns a booking request into one or more *semantically-equivalent*
variants. By construction the structured BookingIntent should be unchanged — that
invariance is the metamorphic relation `run.py` asserts. The honest hard part is
keeping each transform genuinely meaning-preserving (a sloppy "synonym" that
drifts meaning produces a false violation), so:

  - the synonym map is curated golf-domain vocabulary, NOT a generic thesaurus;
  - typos never touch semantic tokens (weekdays, numbers, periods, times, names).

v1 transforms are all `kind="invariance"`. v2 will add `kind="directional"`
transforms that also declare an expected field change (see relations.py).
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass

# ── Curated, defensible equivalences (golf-domain; meaning genuinely preserved) ──
SYNONYMS: dict[str, list[str]] = {
    "4-ball": ["foursome", "four-ball"],
    "foursome": ["4-ball", "four-ball"],
    "threesome": ["3-ball"],
    "knock": ["round", "game"],
    "round": ["knock", "game"],
}

FILLER_PREFIXES = ["could you please ", "i'd like to ", "hi, "]
FILLER_SUFFIXES = [", thanks", ", cheers", " if possible"]

# Tokens whose corruption would change the *meaning* of the request — never typo
# these. Everything semantic the parser keys off: weekdays, periods, relative
# dates, number words, group words, am/pm/noon.
_PROTECTED_WORDS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "mon",
    "tue",
    "tues",
    "wed",
    "thu",
    "thur",
    "thurs",
    "fri",
    "sat",
    "sun",
    "morning",
    "afternoon",
    "evening",
    "noon",
    "midday",
    "lunchtime",
    "am",
    "pm",
    "today",
    "tomorrow",
    "tonight",
    "week",
    "weekend",
    "day",
    "days",
    "one",
    "two",
    "three",
    "four",
    "first",
    "second",
    "ball",
    "fourball",
    "foursome",
    "threesome",
    "pair",
    "single",
    "before",
    "after",
    "from",
    "between",
    "by",
}


@dataclass(frozen=True)
class Transform:
    """A named transform. `kind` is 'invariance' in v1; v2 adds 'directional'
    transforms that also carry an expected field-change descriptor."""

    name: str
    kind: str
    fn: Callable[[str, random.Random], list[str]]


# ── individual transforms (each: text, rng -> list[variant]) ─────────────────


def _casing(text: str, rng: random.Random) -> list[str]:
    """Upper- and lower-cased — the parser lower-cases internally, so meaning holds."""
    return [text.upper(), text.lower()]


def _whitespace(text: str, rng: random.Random) -> list[str]:
    """Doubled internal spaces + trailing whitespace — cosmetic only."""
    return [re.sub(r" ", "  ", text).rstrip() + "  "]


def _filler(text: str, rng: random.Random) -> list[str]:
    """Politeness/filler wrapping — adds no booking information."""
    prefix = rng.choice(FILLER_PREFIXES)
    suffix = rng.choice(FILLER_SUFFIXES)
    return [prefix + text, text + suffix]


def _typo(text: str, rng: random.Random) -> list[str]:
    """A single-character transposition on ONE non-semantic word (len >= 4,
    lower-case, not a protected/number/proper-noun token). Returns [] if no
    eligible word exists, so we never risk corrupting meaning."""
    words = text.split(" ")
    eligible = [
        i
        for i, w in enumerate(words)
        if len(w) >= 4 and w.isalpha() and w.islower() and w.lower() not in _PROTECTED_WORDS
    ]
    if not eligible:
        return []
    i = rng.choice(eligible)
    w = words[i]
    # transpose two adjacent interior characters (keeps it a recognisable typo)
    j = rng.randrange(1, len(w) - 1)
    typoed = w[:j] + w[j + 1] + w[j] + w[j + 2 :]
    new_words = list(words)
    new_words[i] = typoed
    return [" ".join(new_words)]


def _synonym(text: str, rng: random.Random) -> list[str]:
    """Substitute a curated golf-domain phrase with an equivalent. Up to 2
    variants; case-insensitive match, first occurrence replaced."""
    out: list[str] = []
    lowered = text.lower()
    for phrase, alts in SYNONYMS.items():
        idx = lowered.find(phrase)
        if idx == -1:
            continue
        for alt in alts[:1]:  # one substitution per phrase keeps variant count modest
            out.append(text[:idx] + alt + text[idx + len(phrase) :])
        if len(out) >= 2:
            break
    return out


# ── registry (v1: all invariance) ───────────────────────────────────────────

TRANSFORMS: list[Transform] = [
    Transform("casing", "invariance", _casing),
    Transform("whitespace", "invariance", _whitespace),
    Transform("filler", "invariance", _filler),
    Transform("typo", "invariance", _typo),
    Transform("synonym", "invariance", _synonym),
]


# ── directional relations (v2): meaning-CHANGING transforms ───────────────────
# Each rewrites one phrase so that EXACTLY ONE intent field should change to a
# predictable value, everything else unchanged. The swaps are unambiguous golf
# terms (foursome=4, threesome=3) and clear clock/period edits, so the expected
# outcome is not a judgement call. `expected` values are in NORMALISED key form
# (period lower-case, times "HH:MM", group_size int) so they compare directly.


@dataclass(frozen=True)
class Directional:
    name: str  # label, e.g. "period→afternoon"
    find: str  # phrase to look for (case-insensitive, first occurrence)
    replace: str  # what to swap it to
    expected: dict  # normalised field overrides the swap should produce
    kind: str = "directional"


DIRECTIONAL: list[Directional] = [
    Directional("period→afternoon", "morning", "afternoon", {"period": "afternoon"}),
    Directional("period→morning", "afternoon", "morning", {"period": "morning"}),
    Directional("group:4-ball→threesome", "4-ball", "threesome", {"group_size": 3}),
    Directional("group:threesome→foursome", "threesome", "foursome", {"group_size": 4}),
    Directional("time:9am→11am", "9am", "11am", {"not_before": "11:00"}),
]


def apply_directional(text: str, d: Directional) -> str | None:
    """Return the rewritten text if `d.find` occurs (case-insensitive, first
    occurrence), else None (the relation does not apply to this seed)."""
    idx = text.lower().find(d.find.lower())
    if idx == -1:
        return None
    return text[:idx] + d.replace + text[idx + len(d.find) :]
