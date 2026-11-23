"""Protected-token guard.

The safety invariant of Shuddhi: no automatic or bulk action may change a number, amount,
date, reference number or section number. Every mark from every source (rules, consistency
checks, AI) passes through `apply_guard` before a reviewer sees it.

* A mark whose span overlaps a protected token or protected zone becomes a QUERY (never applied).
* A mark whose replacement would change the value of a protected token is BLOCKED (dropped, logged).
"""
import re
from collections import Counter

# Digits in Latin, Bengali-Assamese and Devanagari scripts.
DIG = r"0-9০-৯०-९"
D = f"[{DIG}]"

PROTECTED_PATTERNS = [
    # Amounts: Rs. / ₹ / টকা followed by a number with Indian or western grouping.
    ("amount", re.compile(rf"(?:₹|Rs\.?|INR)\s*{D}[{DIG},]*(?:\.{D}+)?(?:\s*/-)?", re.I)),
    # Dates such as 13-10-2023, 13/10/2023, 13.10.2023 and 2023-10-13.
    ("date", re.compile(rf"(?<!{D}){D}{{1,4}}[-/.]{D}{{1,2}}[-/.]{D}{{2,4}}(?!{D})")),
    # Dates written as 13th October, 2023 / October 13, 2023.
    ("date", re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}\b")),
    ("date", re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b")),
    # Reference / file numbers: No. AAP.37/2023/148, No.SMP.45/2026/12, ECF No. 123456.
    ("reference", re.compile(rf"\b(?:No|Nos|Memo|Letter|File|ECF)\s*\.?\s*:?\s*[A-Z][A-Za-z().&-]*\s*\.?\s*{D}[\w./()-]*", re.I)),
    ("reference", re.compile(rf"\b[A-Z]{{2,}}[A-Z.()&-]*\.?\s*{D}+(?:/[\w.()-]+)+")),
    # Section, rule, clause and article numbers: Rule 7 (vii), Section 52(1)(q), Article 309.
    ("section", re.compile(rf"\b(?:Section|Sec\.|Rule|Rules|Clause|Article|Para|Paragraph|Schedule|Chapter|Sub-section)\s*{D}+[A-Za-z]?(?:\s*\([0-9a-zivx]+\))*", re.I)),
    # Any remaining number in any script (keeps digit runs, with grouping).
    ("number", re.compile(rf"{D}(?:[{DIG},.]*{D})?")),
]


def protected_spans(text):
    """Return a sorted list of (start, end, kind) protected-token spans, merged where they overlap."""
    spans = []
    for kind, rx in PROTECTED_PATTERNS:
        for m in rx.finditer(text):
            if m.end() > m.start():
                spans.append((m.start(), m.end(), kind))
    spans.sort()
    merged = []
    for s, e, k in spans:
        if merged and s < merged[-1][1]:
            ps, pe, pk = merged[-1]
            merged[-1] = (ps, max(pe, e), pk)
        else:
            merged.append((s, e, k))
    return merged


def digit_signature(text):
    """All digit runs in the text, normalised to Latin digits, as a multiset.
    Used to check that a replacement does not change any number's value."""
    table = {ord(c): str(i) for i, c in enumerate("০১২৩৪৫৬৭৮৯")}
    table.update({ord(c): str(i) for i, c in enumerate("०१२३४५६७८९")})
    norm = text.translate(table)
    return Counter(re.findall(r"[0-9]+", norm))


def tokens_signature(text):
    """Exact protected tokens (text, kind) as a multiset: the invariant compares these."""
    return Counter((text[s:e], k) for s, e, k in protected_spans(text))


def overlaps(a_s, a_e, b_s, b_e):
    return a_s < b_e and b_s < a_e


def apply_guard(text, findings, zones=()):
    """Classify every finding against protected tokens and zones.

    findings: list of dicts with keys start, end, to, kind ('fix' or 'query'), bulk.
    zones: list of (start, end, kind) protected zones (quotes, citations, corrigenda, names).
    Returns (kept, blocked). Kept findings may have kind downgraded to 'query' and bulk=False.
    """
    prot = protected_spans(text)
    kept, blocked = [], []
    for f in findings:
        f = dict(f)
        frm = text[f["start"]:f["end"]]
        to = f.get("to")
        hit_tok = [p for p in prot if overlaps(f["start"], f["end"], p[0], p[1])]
        hit_zone = [z for z in zones if overlaps(f["start"], f["end"], z[0], z[1])]
        if f["kind"] == "fix" and to is not None and digit_signature(frm) != digit_signature(to):
            f["status"] = "blocked: would change a number"
            blocked.append(f)
            continue
        if hit_tok or hit_zone:
            if f["kind"] == "fix":
                f["kind"] = "query"
                f["why"] = f.get("why", "") + (" [protected token: query only]" if hit_tok
                                               else f" [protected zone ({hit_zone[0][2]}): query only]")
            f["bulk"] = False
            f["protected"] = True
        else:
            f["protected"] = False
        kept.append(f)
    return kept, blocked


def digit_sequence(text):
    table = {ord(c): str(i) for i, c in enumerate("০১২৩৪৫৬৭৮৯")}
    table.update({ord(c): str(i) for i, c in enumerate("०१२३४५६७८९")})
    return re.findall(r"[0-9]+", text.translate(table))


def check_invariant(before, after):
    """True if no protected value changed between `before` and `after`:
    * the digit runs are identical and in the same order (no number added, removed or altered), and
    * every amount, reference and section token of `before` still appears verbatim in `after`.
    (Spacing around a date may be tidied, so dates are covered by the digit check.)"""
    if digit_sequence(before) != digit_sequence(after):
        return False
    for s, e, k in protected_spans(before):
        if k in ("amount", "reference", "section") and before[s:e] not in after:
            return False
    return True
