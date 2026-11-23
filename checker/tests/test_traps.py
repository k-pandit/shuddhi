"""Safety tests: valid official text must come through unchanged, even if a reviewer accepts every fix."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from shuddhi_core import apply_fixes, check_invariant, check_text, default_speller  # noqa: E402

SPELL = default_speller()
TRAPS = [json.loads(l) for l in open(os.path.join(HERE, "..", "traps", "traps.jsonl"), encoding="utf-8")]


@pytest.mark.parametrize("trap", TRAPS, ids=[t["id"] for t in TRAPS])
def test_trap_unchanged_even_if_every_fix_is_accepted(trap):
    lang, kept, blocked = check_text(trap["text"], trap["declared"], SPELL)
    after = apply_fixes(trap["text"], kept, accept=lambda f: True)
    assert after == trap["text"], f"applied changes: {[(f['rule'], f['from'], f['to']) for f in kept if f['kind']=='fix']}"


def test_bengali_never_corrected_to_assamese():
    for t in TRAPS:
        if t["id"].startswith("bengali"):
            _, kept, _ = check_text(t["text"], t["declared"], SPELL)
            assert not [f for f in kept if f["rule"] == "AS-RA"]


def test_protected_tokens_become_queries():
    text = "Pay Rs. 5,000  only by 01-04-2027."
    _, kept, _ = check_text(text, None, SPELL)
    for f in kept:
        if f.get("protected"):
            assert f["kind"] == "query" and not f["bulk"]


def test_ai_suggestion_that_changes_a_number_is_blocked():
    text = "A sum of Rs. 50,000 is sanctioned under Rule 7 (vii)."
    ai = [{"start": 9, "end": 19, "to": "Rs. 5,000", "rule": "AI", "why": "mock AI rewrite", "kind": "fix",
           "bulk": False, "lane": "one", "source": "ai"}]
    _, kept, blocked = check_text(text, None, SPELL, extra_findings=ai)
    assert any(b["rule"] == "AI" for b in blocked)
    assert apply_fixes(text, kept) == text or check_invariant(text, apply_fixes(text, kept))


def test_positive_controls_are_still_fixed():
    """The guard must not make Shuddhi useless: ordinary errors are still corrected."""
    cases = {
        "The Commitee will meet  on Monday .": "The Committee will meet on Monday.",
        "the the report was recieved by the goverment": "the report was received by the government",
        "এই কাম আরু সকলো বিভাগক জনোৱা হ'ব।": "এই কাম আৰু সকলো বিভাগক জনোৱা হ'ব।",
        "यह आदेश लागू होगा |": "यह आदेश लागू होगा।",
    }
    for src, want in cases.items():
        _, kept, _ = check_text(src, None, SPELL)
        assert apply_fixes(src, kept) == want, (src, [(f["rule"], f["from"], f["to"], f["kind"]) for f in kept])
