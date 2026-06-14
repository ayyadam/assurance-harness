"""Metamorphic / invariance testing of the booking assistant.

A second evaluation *method* over the same AI feature as the golden-set eval (it
reuses `ai_evaluation.evaluator.SUTClient`). Where the golden set asks "is the
intent correct for these exact phrasings?", this asks "is the intent *stable*
across meaning-preserving rephrasings?" — the robustness a fixed golden set
cannot express.

v1 ships invariance relations (meaning-preserving transforms → intent unchanged).
v2 adds directional relations (meaning-changing transforms → one field changes
predictably, the rest unchanged); the framework in `relations.py` is built for it.
"""
