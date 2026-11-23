"""Run the rules on text, pass every mark through zones and the guard, and apply accepted fixes."""
import hashlib
import os

from .guard import apply_guard, check_invariant
from .langid import confirm_language
from .rules import RULES
from .zones import protected_zones


class Speller:
    """Thin wrapper around spylls (Hunspell in pure Python) with a cache.
    A word is accepted if any of the dictionaries knows it (Indian official English mixes
    British and American spellings, e.g. 'regularization' and 'regularisation')."""

    def __init__(self, dic_base, *more):
        from spylls.hunspell import Dictionary
        self.d = Dictionary.from_files(dic_base)
        self.others = [Dictionary.from_files(b) for b in more]
        self.cache, self.sug = {}, {}

    def known(self, w):
        if w not in self.cache:
            self.cache[w] = bool(self.d.lookup(w)) or any(o.lookup(w) for o in self.others)
        return self.cache[w]

    def suggest(self, w):
        if w not in self.sug:
            s = None
            for cand in self.d.suggest(w):
                s = cand
                break
            self.sug[w] = s
        return self.sug[w]


def default_speller():
    here = os.path.dirname(os.path.abspath(__file__))
    d = os.path.normpath(os.path.join(here, "..", "..", "data", "dict"))
    gb, us = os.path.join(d, "en_GB"), os.path.join(d, "en_US")
    if not os.path.exists(gb + ".dic"):
        return None
    return Speller(gb, *([us] if os.path.exists(us + ".dic") else []))


def fingerprint(rule, frm, text, start):
    ctx = text[max(0, start - 20):start + 20]
    return hashlib.sha256(f"{rule}|{frm}|{ctx}".encode("utf-8")).hexdigest()[:12]


def check_text(text, declared=None, spell=None, extra_findings=(), skip_spell=()):
    """Return (lang, kept, blocked) for one paragraph or line.

    extra_findings: marks from other sources (consistency check, AI) to be guarded the same way.
    skip_spell: start offsets of words the spell rule must skip (e.g. halves of a hyphenated line break).
    """
    lang, confirmed = confirm_language(text, declared)
    ctx = {"lang": lang, "spell": spell, "skip_spell": set(skip_spell)}
    raw = []
    for prio, rule in enumerate(RULES):
        if lang not in rule.langs:
            continue
        for s, e, to, why in rule.fn(text, ctx):
            kind = "query" if (rule.kind == "query" or to is None) else "fix"
            raw.append({"start": s, "end": e, "to": to, "rule": rule.rid, "why": why, "kind": kind,
                        "bulk": rule.bulk and kind == "fix", "lane": rule.lane, "prio": prio, "source": "rule"})
    raw.extend(dict(f) for f in extra_findings)
    raw.sort(key=lambda f: (f["start"], f.get("prio", 99)))
    marks, last = [], -1
    for f in raw:                      # no overlapping marks
        if f["start"] >= last:
            marks.append(f)
            last = f["end"]
    kept, blocked = apply_guard(text, marks, protected_zones(text))
    for f in kept + blocked:
        f["from"] = text[f["start"]:f["end"]]
        f["id"] = fingerprint(f["rule"], f["from"], text, f["start"])
        f["lang"] = lang
        if f["kind"] == "query":
            f["lane"] = "one" if f.get("protected") else f.get("lane", "one")
            f["bulk"] = False
    return lang, kept, blocked


def apply_fixes(text, findings, accept=lambda f: True):
    """Apply the 'fix' findings the reviewer accepts. Queries are never applied.
    Raises AssertionError if the result breaks the protected-token invariant."""
    out, cur = [], 0
    for f in sorted(findings, key=lambda f: f["start"]):
        if f["kind"] != "fix" or f.get("to") is None or not accept(f):
            continue
        out.append(text[cur:f["start"]])
        out.append(f["to"])
        cur = f["end"]
    out.append(text[cur:])
    new = "".join(out)
    assert check_invariant(text, new), "protected-token invariant broken"
    return new


def check_document(paragraphs, declared=None, spell=None):
    """Check a list of paragraphs; DIGITS becomes one note per document."""
    results, seen_digits = [], False
    for i, p in enumerate(paragraphs):
        lang, kept, blocked = check_text(p, declared, spell)
        if seen_digits:
            kept = [f for f in kept if f["rule"] != "DIGITS"]
        elif any(f["rule"] == "DIGITS" for f in kept):
            seen_digits = True
        results.append({"index": i, "text": p, "lang": lang, "findings": kept, "blocked": blocked})
    return results
