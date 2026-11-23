"""Consistency check within one document: the same name or term spelled two ways.

Both spellings may be real words ("PLAIN" and "Plan"), so a dictionary cannot see the error.
We compare capitalised words and phrases inside one document and raise a QUERY (never a fix)
for pairs that differ by one or two letters.
"""
import re
from collections import defaultdict

from rapidfuzz.distance import Levenshtein

PAREN = re.compile(r"\(([A-Za-z][A-Za-z .&-]{2,30})\)")
CAPWORD = re.compile(r"\b[A-Z][a-z]{4,}\b|\b[A-Z]{4,}\b")
ROMAN = re.compile(r"(?<![a-z])[ivxlc]+(?![a-z])")
COMMON = {"there", "these", "their", "where", "which", "while", "other", "under", "after", "shall", "order",
          "orders", "notification", "government", "department"}


def _sing(x):
    return " ".join(w.rstrip("s") for w in x.split())


def consistency_findings(paragraphs):
    """paragraphs: list of strings (one document). Returns query findings with paragraph index."""
    occ = defaultdict(list)
    for pi, t in enumerate(paragraphs):
        for rx in (PAREN, CAPWORD):
            for m in rx.finditer(t):
                g = m.group(1) if rx is PAREN else m.group()
                s = m.start(1) if rx is PAREN else m.start()
                occ[g.casefold()].append((pi, s, s + len(g), g))
    keys = [k for k in occ if k not in COMMON]
    out = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if abs(len(a) - len(b)) > 2 or min(len(a), len(b)) < 4:
                continue
            if ROMAN.sub("", a) == ROMAN.sub("", b) or _sing(a) == _sing(b) or a.endswith(b) or b.endswith(a):
                continue
            d = Levenshtein.distance(a, b)
            if 0 < d <= (1 if min(len(a), len(b)) < 7 else 2):
                # the rarer spelling is the likely error; query every occurrence of it
                rare, common = (a, b) if len(occ[a]) <= len(occ[b]) else (b, a)
                for pi, s, e, g in occ[rare]:
                    out.append({"para": pi, "start": s, "end": e, "to": None, "rule": "CONSISTENCY", "kind": "query",
                                "bulk": False, "lane": "one", "source": "consistency",
                                "why": f"'{g}' vs '{occ[common][0][3]}' elsewhere in this document: same name?"})
    return out
