#!/usr/bin/env python3
"""
Shuddhi benchmark.

Part 1 - seeded errors on public Assam Gazette English text
  Corpus: lines from pages of the public Gazette PDFs that are machine-readable text and carry no
  personal data (name-change, disciplinary, vigilance, arrest notices are excluded by code).
  Errors of 8 types are seeded with a fixed random seed. Shuddhi is compared with a plain
  dictionary spell-checker (Hunspell en_GB via spylls), which is what most tools offer.

Part 2 - adversarial protected-token test
  About 200 cases built to tempt a proofreading tool into changing a number, amount, date,
  reference, section number, citation, quotation, corrigendum, Bengali text or a doubled Indic word,
  including mock "AI suggestions" that rewrite figures. A worst-case reviewer accepts EVERY fix.
  Pass condition: protected-token edits = 0. The rules of the earlier prototype are run on the
  same cases for comparison.

Usage: python bench/run_bench.py --gazette ../data/gazette --seed 42 --out out/bench
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict

import pdfplumber

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from shuddhi_core import apply_fixes, check_invariant, check_text, default_speller  # noqa: E402
from shuddhi_core.consistency import consistency_findings  # noqa: E402
from shuddhi_core.rules import MISSPELL  # noqa: E402
from shuddhi_pdf import LEGACY_FONT, classify_page, page_lines, privacy_reason  # noqa: E402

SEED_TYPES = ["swap", "drop", "double-letter", "known-misspelling", "doubled-word", "space-before-punct",
              "double-space", "name-variant"]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


# ----------------------------------------------------------------------------- corpus
def build_corpus(gazette_dir):
    manifest, lines = [], []
    for name in sorted(os.listdir(gazette_dir)):
        if not name.endswith(".pdf"):
            continue
        path = os.path.join(gazette_dir, name)
        with open(path, "rb") as f:
            fsha = hashlib.sha256(f.read()).hexdigest()
        with pdfplumber.open(path) as pdf:
            for i, pg in enumerate(pdf.pages, 1):
                info = classify_page(pg)
                if info["class"] in ("SCANNED", "EMPTY", "LEGACY"):
                    manifest.append({"file": name, "page": i, "used": False, "reason": info["class"].lower()})
                    continue
                pls = page_lines(pg)
                reason = privacy_reason("\n".join(l["text"] for l in pls))
                if reason:
                    manifest.append({"file": name, "page": i, "used": False, "reason": "personal data: " + reason})
                    continue
                n0 = len(lines)
                for k, l in enumerate(pls):
                    t = l["text"].strip()
                    if len(t.split()) < 6 or t.endswith(("-", "‐", "­")) or (k and pls[k - 1]["text"].endswith(("-", "‐", "­"))):
                        continue
                    if k <= 1 and t[:1].islower():
                        continue
                    if "THE ASSAM GAZETTE" in t.upper():
                        continue
                    lines.append({"file": name, "page": i, "text": t})
                manifest.append({"file": name, "file_sha256": fsha, "page": i, "used": True, "lines": len(lines) - n0})
    return manifest, lines


# ----------------------------------------------------------------------------- seeding
def candidate_words(text, spell, rng):
    ws = [m for m in re.finditer(r"\b[a-z]{5,}\b", text) if spell.known(m.group())]
    rng.shuffle(ws)
    return ws


def seed_one(text, kind, rng, spell, doc_paras):
    """Return (new_text, (start, end), original_fragment) or None if the type cannot be seeded here."""
    if kind in ("swap", "drop", "double-letter"):
        for m in candidate_words(text, spell, rng):
            w = m.group()
            k = rng.randrange(1, len(w) - 1)
            if kind == "swap":
                nw = w[:k] + w[k + 1] + w[k] + w[k + 2:]
            elif kind == "drop":
                nw = w[:k] + w[k + 1:]
            else:
                nw = w[:k] + w[k] + w[k:]
            if nw != w and not spell.known(nw):
                return text[:m.start()] + nw + text[m.end():], (m.start(), m.start() + len(nw)), w
        return None
    if kind == "known-misspelling":
        inv = defaultdict(list)
        for bad, good in MISSPELL.items():
            if " " not in good:
                inv[good].append(bad)
        for m in re.finditer(r"\b[A-Za-z]+\b", text):
            low = m.group().lower()
            if low in inv:
                bad = rng.choice(inv[low])
                nb = bad[0].upper() + bad[1:] if m.group()[0].isupper() else bad
                return text[:m.start()] + nb + text[m.end():], (m.start(), m.start() + len(nb)), m.group()
        return None
    if kind == "doubled-word":
        ms = list(re.finditer(r"\b[a-z]{3,}\b", text))
        if not ms:
            return None
        m = rng.choice(ms)
        new = text[:m.end()] + " " + m.group() + text[m.end():]
        return new, (m.start(), m.end() + 1 + len(m.group())), m.group()
    if kind == "space-before-punct":
        ms = [m for m in re.finditer(r"[a-z](,)\s", text)]
        if not ms:
            return None
        m = rng.choice(ms)
        s = m.start(1)
        return text[:s] + " " + text[s:], (s, s + 2), ","
    if kind == "double-space":
        ms = list(re.finditer(r"(?<=[a-z]) (?=[a-z])", text))
        if not ms:
            return None
        m = rng.choice(ms)
        return text[:m.start()] + "  " + text[m.end():], (m.start(), m.start() + 2), " "
    if kind == "name-variant":
        joined = " ".join(doc_paras)
        names = Counter(re.findall(r"\b[A-Z][a-z]{5,}\b", joined))
        cands = [m for m in re.finditer(r"\b[A-Z][a-z]{5,}\b", text) if names[m.group()] >= 2]
        if not cands:
            return None
        m = rng.choice(cands)
        w = m.group()
        k = rng.randrange(2, len(w) - 1)
        nw = w[:k] + w[k + 1:] if rng.random() < 0.5 else w[:k] + w[k] + w[k:]
        if nw == w:
            return None
        return text[:m.start()] + nw + text[m.end():], (m.start(), m.start() + len(nw)), w
    return None


def shuddhi_marks(paras, spell):
    marks = defaultdict(list)
    for pi, t in enumerate(paras):
        _, kept, _ = check_text(t, "en", spell)
        for f in kept:
            marks[pi].append(f)
    for f in consistency_findings(paras):
        marks[f["para"]].append(f)
    return marks


def baseline_marks(paras, spell):
    """A plain dictionary spell-checker: flag every word the dictionary does not know."""
    marks = defaultdict(list)
    for pi, t in enumerate(paras):
        for m in re.finditer(r"\b[A-Za-z]{2,}\b", t):
            if not spell.known(m.group()):
                marks[pi].append({"start": m.start(), "end": m.end(), "rule": "DICT", "to": spell.suggest(m.group())})
    return marks


def overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def run_seeded(lines, spell, seed, variants, doc_size, clean_share):
    rng = random.Random(seed)
    docs = [lines[i:i + doc_size] for i in range(0, len(lines) - doc_size + 1, doc_size)]
    stats = {tool: {"tp": Counter(), "n": Counter(), "fp": 0, "marks": 0, "fixed_right": 0, "fix_tp": 0}
             for tool in ("shuddhi", "baseline")}
    clean_words = 0
    clean_marks = {"shuddhi": 0, "baseline": 0}
    for v in range(variants):
        for d in docs:
            paras = [l["text"] for l in d]
            # marks already present on the unseeded text (natural errors or false alarms)
            pre = {"shuddhi": shuddhi_marks(paras, spell), "baseline": baseline_marks(paras, spell)}
            if v == 0:
                clean_words += sum(len(p.split()) for p in paras)
                for tool in pre:
                    clean_marks[tool] += sum(len(x) for x in pre[tool].values())
            if rng.random() < clean_share:
                continue
            seeded = list(paras)
            seeds = []
            for _ in range(rng.randint(1, 3)):
                kind = rng.choice(SEED_TYPES)
                pi = rng.randrange(len(seeded))
                if any(s["para"] == pi for s in seeds):
                    continue
                r = seed_one(seeded[pi], kind, rng, spell, seeded)
                if r is None:
                    continue
                seeded[pi], span, orig = r
                seeds.append({"para": pi, "span": span, "kind": kind, "orig": orig})
            if not seeds:
                continue
            seeded_paras = {s["para"] for s in seeds}
            for tool, fn in (("shuddhi", shuddhi_marks), ("baseline", baseline_marks)):
                marks = fn(seeded, spell)
                st = stats[tool]
                for s in seeds:
                    st["n"][s["kind"]] += 1
                    hit = [m for m in marks[s["para"]] if overlap((m["start"], m["end"]), s["span"])]
                    if hit:
                        st["tp"][s["kind"]] += 1
                        fx = [m for m in hit if m.get("kind", "fix") == "fix" and m.get("to") is not None]
                        if s["kind"] in ("swap", "drop", "double-letter", "known-misspelling") and fx:
                            st["fix_tp"] += 1
                            if fx[0]["to"].lower() == s["orig"].lower():
                                st["fixed_right"] += 1
                # false alarms: marks in seeded paragraphs that hit no seed and were not already present
                for pi in seeded_paras:
                    pre_spans = {(m["start"], m["end"]) for m in pre[tool].get(pi, [])}
                    for m in marks[pi]:
                        st["marks"] += 1
                        if not any(overlap((m["start"], m["end"]), s["span"]) for s in seeds if s["para"] == pi) \
                                and (m["start"], m["end"]) not in pre_spans:
                            st["fp"] += 1
    return stats, clean_words, clean_marks, len(docs)


# ----------------------------------------------------------------------------- adversarial
def adversarial_cases(rng):
    amounts = ["₹ 5,00,000/-", "Rs. 12,450.00", "Rs.50,000", "₹1,25,00,000", "INR 7,500", "Rs. 3.5 lakh",
               "₹ 99,999", "Rs 1,000/-", "₹ 2,40,000", "Rs. 18,00,000/-", "₹ 600", "Rs. 4,32,100", "₹ 10,000", "Rs. 25,000/-",
               "₹ 1,50,000", "Rs. 8,000"]
    dates = ["01-04-2027", "31.03.2028", "13/10/2023", "2026-11-04", "4-11-2026", "29/02/2024", "15.08.1947",
             "30-06-2027", "1/1/2027", "12-12-2026", "05.09.2026", "31/12/2026", "10-10-2025", "07.07.2027",
             "26-01-2027", "02/10/2026"]
    refs = ["No. SMP.45/2026/12", "No.AAP. 37/2023/393", "No. E- Comp. No.: 800346/2026/12", "ECF No. 123456",
            "No. TAD.12/2026/45", "No. PWD(B)123/2025/7", "Memo No. FIN(B)45/2026/3", "No. HPL.88/2024/201",
            "No. RGP.19/2026/56", "No. GAD(A)7/2026/112", "No. ELE.70/2025/9", "No. HE.33/2026/14",
            "No. DPS.4/2026/88", "No. TRP.21/2026/30", "No. AGR.9/2026/17", "No. WR.110/2026/5"]
    sections = ["Rule 7 (vii)", "Section 52(1)(q)", "Article 309", "Rule 15", "Section 3", "Clause 4(b)",
                "Para 12", "Schedule 2", "Section 144", "Rule 10(2)(a)", "Article 16(4)", "Section 21", "Rule 3",
                "Chapter 5", "Section 7(1)", "Rule 9"]
    acts = ["Gauhati Municipal Corporation Act, 1969", "Assam Services (Discipline & Appeal) Rules, 1964",
            "Assam Panchayat Act, 1994", "Right to Information Act, 2005", "Assam Land and Revenue Regulation, 1886",
            "Gauhati High Court", "Gauhati University", "Assam Public Service Commission"]
    misspelt = ["Commitee", "recieved", "goverment", "seperate", "occured", "untill"]
    bengali = ["পরীক্ষার ফলাফল প্রকাশ করা হবে এবং প্রার্থীদের জানানো হবে।", "এই বিজ্ঞপ্তি অবিলম্বে কার্যকর হবে।",
               "সরকার এই প্রকল্পের জন্য অর্থ বরাদ্দ করেছে।", "আবেদনপত্র জমা দেওয়ার শেষ তারিখ পরে জানানো হবে।"]
    redup = ["এই কাম লাহে লাহে আগবাঢ়িব আৰু সকলো বিভাগক জনোৱা হ'ব।", "यह काम धीरे धीरे आगे बढ़ेगा।",
             "সময়ে সময়ে সকলো বিভাগক জনোৱা হ'ব আৰু কাম চলি থাকিব।", "बार बार आवेदन करने की आवश्यकता नहीं है।"]
    cases = []

    def add(kind, text, must_keep, ai=None, declared=None):
        cases.append({"kind": kind, "text": text, "must_keep": must_keep, "ai": ai or [], "declared": declared})

    for i in range(16):
        a = amounts[i]
        add("amount", f"A sum of {a}  is sanctioned for the year 2026-27 .", [a])
        add("date", f"with effect from {dates[i]} till further orders ,the Committee shall meet.", [dates[i]])
        add("reference", f"Order issued vide {refs[i]}  dated {dates[(i + 3) % 16]} is hereby cancelled .", [refs[i]])
        add("section", f"under {sections[i]}  of the said Rules , the officer is posted.", [sections[i]])
    for i in range(16):
        w = misspelt[i % len(misspelt)]
        add("corrigendum", f"In the notification cited above, for '{w}' read '{MISSPELL[w.lower()].title() if w[0].isupper() else MISSPELL[w.lower()]}'.", [f"'{w}'"])
        add("quotation", f"The applicant wrote \"{w}\" in column {i + 2} of the form.", [f"\"{w}\""])
    for i in range(16):
        act = acts[i % len(acts)]
        add("citation", f"as provided under the {act}  and orders issued thereunder .", [act])
    for i in range(16):
        add("bengali", bengali[i % 4], [bengali[i % 4]], declared=("bn" if i % 2 else None))
        add("indic-reduplication", redup[i % 4], [redup[i % 4]])
    for i in range(16):
        n = 10 + i
        add("indic-digits", f"২০২৬ চনৰ {n} নং জাননী অনুসৰি আৰু সকলো বিভাগক জনোৱা হ'ব।", [str(n), "২০২৬"])
    # mock AI suggestions that try to rewrite a protected value (the guard must block or query them)
    for i in range(16):
        a, a2 = amounts[i], amounts[(i + 1) % 16]
        text = f"A sum of {a} is sanctioned under {sections[i]}."
        s = text.index(a)
        add("ai-amount-rewrite", text, [a], ai=[{"start": s, "end": s + len(a), "to": a2, "rule": "AI", "why": "mock AI",
                                                  "kind": "fix", "bulk": False, "lane": "one", "source": "ai"}])
        d, d2 = dates[i], dates[(i + 5) % 16]
        text = f"The meeting held on {d} approved the proposal."
        s = text.index(d)
        add("ai-date-rewrite", text, [d], ai=[{"start": s, "end": s + len(d), "to": d2, "rule": "AI", "why": "mock AI",
                                                "kind": "fix", "bulk": False, "lane": "one", "source": "ai"}])
        act = acts[i % len(acts)]
        text = f"The matter is pending before the {act} for decision."
        s = text.index(act)
        add("ai-name-rewrite", text, [act], ai=[{"start": s, "end": s + len(act), "to": act.replace("Gauhati", "Guwahati").replace("Assam", "Asom"),
                                                  "rule": "AI", "why": "mock AI", "kind": "fix", "bulk": False, "lane": "one", "source": "ai"}])
    return cases


def load_old_rules():
    """The rules of the earlier prototype (bench/legacy/shuddhi_docx_v1.py), for comparison."""
    p = os.path.join(HERE, "legacy", "shuddhi_docx_v1.py")
    if not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("old_shuddhi", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def old_apply(mod, text):
    lang = mod.detect_lang(text, "as")
    marks = mod.find_marks(text, lang)
    out, cur = [], 0
    for m in marks:
        out.append(text[cur:m["start"]]); out.append(m["to"]); cur = m["end"]
    out.append(text[cur:])
    return "".join(out)


def run_adversarial(spell, rng):
    cases = adversarial_cases(rng)
    old = load_old_rules()
    res = {"cases": len(cases), "by_kind": Counter(c["kind"] for c in cases), "shuddhi_violations": 0,
           "shuddhi_changed_must_keep": 0, "old_violations": 0, "old_changed_must_keep": 0, "ai_blocked": 0,
           "ai_queried": 0, "ai_superseded": 0, "ai_applied": 0, "examples_old": []}
    for c in cases:
        _, kept, blocked = check_text(c["text"], c["declared"], spell, extra_findings=c["ai"])
        res["ai_blocked"] += sum(1 for b in blocked if b["rule"] == "AI")
        res["ai_queried"] += sum(1 for k in kept if k["rule"] == "AI" and k["kind"] == "query")
        n_ai = len(c["ai"])
        n_seen = sum(1 for b in blocked if b["rule"] == "AI") + sum(1 for k in kept if k["rule"] == "AI")
        res["ai_superseded"] += n_ai - n_seen     # a rule mark already covers that span; the AI mark is dropped
        if c["ai"]:
            trial = apply_fixes(c["text"], kept, accept=lambda f: f["rule"] == "AI")
            if trial != c["text"]:
                res["ai_applied"] += 1
        try:
            after = apply_fixes(c["text"], kept, accept=lambda f: True)     # worst-case reviewer accepts everything
            ok = check_invariant(c["text"], after)
        except AssertionError:
            after, ok = None, False
        if not ok:
            res["shuddhi_violations"] += 1
        if after is None or any(k not in after for k in c["must_keep"]):
            res["shuddhi_changed_must_keep"] += 1
        if old is not None and not c["ai"]:
            o = old_apply(old, c["text"])
            bad = (not check_invariant(c["text"], o)) or any(k not in o for k in c["must_keep"])
            if bad:
                res["old_violations"] += 1
                if len(res["examples_old"]) < 8:
                    res["examples_old"].append({"kind": c["kind"], "before": c["text"], "after_old_rules": o})
    res["old_cases"] = sum(1 for c in cases if not c["ai"])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gazette", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--variants", type=int, default=10)
    ap.add_argument("--doc-size", type=int, default=8)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    spell = default_speller()
    manifest, lines = build_corpus(a.gazette)
    corpus_sha = hashlib.sha256("\n".join(l["text"] for l in lines).encode("utf-8")).hexdigest()
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"corpus_sha256": corpus_sha, "lines": len(lines), "pages": manifest}, f, indent=1)
    stats, clean_words, clean_marks, ndocs = run_seeded(lines, spell, a.seed, a.variants, a.doc_size, 0.2)
    adv = run_adversarial(spell, random.Random(a.seed))

    R = {"seed": a.seed, "corpus_sha256": corpus_sha, "corpus_lines": len(lines), "documents": ndocs,
         "clean_words": clean_words, "seeded": {}, "adversarial": {k: (dict(v) if isinstance(v, Counter) else v) for k, v in adv.items()}}
    for tool, st in stats.items():
        per = {}
        for k in SEED_TYPES:
            p, lo, hi = wilson(st["tp"][k], st["n"][k])
            per[k] = {"seeded": st["n"][k], "found": st["tp"][k], "recall": round(p, 3), "ci95": [round(lo, 3), round(hi, 3)]}
        n, tp = sum(st["n"].values()), sum(st["tp"].values())
        p, lo, hi = wilson(tp, n)
        prec = (st["marks"] - st["fp"]) / st["marks"] if st["marks"] else 0.0
        R["seeded"][tool] = {"per_type": per, "total_seeded": n, "total_found": tp, "recall": round(p, 3),
                             "recall_ci95": [round(lo, 3), round(hi, 3)], "marks_in_seeded_paragraphs": st["marks"],
                             "false_alarms": st["fp"], "precision": round(prec, 3),
                             "marks_per_1000_unseeded_words": round(1000.0 * clean_marks[tool] / max(1, clean_words), 1),
                             "spelling_fix_correct": f"{st['fixed_right']}/{st['fix_tp']}"}
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(R, f, indent=1, ensure_ascii=False)
    write_report(R, os.path.join(a.out, "report.md"))
    print(open(os.path.join(a.out, "report.md"), encoding="utf-8").read())


def write_report(R, path):
    S, B = R["seeded"]["shuddhi"], R["seeded"]["baseline"]
    A = R["adversarial"]
    L = ["# Shuddhi benchmark report", "",
         f"- Random seed: {R['seed']}; corpus SHA-256: `{R['corpus_sha256'][:16]}…`",
         f"- Corpus: {R['corpus_lines']} lines of public Assam Gazette English text in {R['documents']} documents "
         f"({R['clean_words']} words); pages with personal data, scanned pages and legacy-font text excluded (see manifest.json)",
         "", "## Part 1: seeded errors", "",
         "Dictionary only = a plain Hunspell spell-checker (en_GB + en_US dictionaries), as most office tools provide.", "",
         "| Error type | Seeded | Shuddhi found | Shuddhi recall (95% CI) | Dictionary-only found | Dictionary-only recall |",
         "|---|---|---|---|---|---|"]
    for k in SEED_TYPES:
        s, b = S["per_type"][k], B["per_type"][k]
        L.append(f"| {k} | {s['seeded']} | {s['found']} | {s['recall']:.0%} ({s['ci95'][0]:.0%}–{s['ci95'][1]:.0%}) | {b['found']} | {b['recall']:.0%} |")
    L.append(f"| **All** | **{S['total_seeded']}** | **{S['total_found']}** | **{S['recall']:.0%} ({S['recall_ci95'][0]:.0%}–{S['recall_ci95'][1]:.0%})** | **{B['total_found']}** | **{B['recall']:.0%}** |")
    L += ["", "| Measure | Shuddhi | Dictionary only |", "|---|---|---|",
          f"| Precision of marks in seeded paragraphs | {S['precision']:.0%} | {B['precision']:.0%} |",
          f"| Marks per 1,000 words of unseeded Gazette text | {S['marks_per_1000_unseeded_words']} | {B['marks_per_1000_unseeded_words']} |",
          f"| First suggestion restores the original word (spelling seeds) | {S['spelling_fix_correct']} | {B['spelling_fix_correct']} |",
          "", "Marks on unseeded text include genuine errors in the published Gazette as well as false alarms.",
          "", "## Part 2: adversarial protected-token test", "",
          f"- Cases: {A['cases']} (" + ", ".join(f"{k} {v}" for k, v in A["by_kind"].items()) + ")",
          "- A worst-case reviewer accepts every fix Shuddhi offers.",
          f"- **Protected-token edits by Shuddhi: {A['shuddhi_violations']} of {A['cases']}**; protected text altered: {A['shuddhi_changed_must_keep']}",
          f"- Mock AI rewrites of a protected value ({A['by_kind'].get('ai-amount-rewrite', 0) + A['by_kind'].get('ai-date-rewrite', 0) + A['by_kind'].get('ai-name-rewrite', 0)}): "
          f"{A['ai_blocked']} blocked, {A['ai_queried']} turned into queries, {A['ai_superseded']} dropped because a rule query already covered the span; **applied: {A['ai_applied']}**",
          f"- Earlier prototype rules on the same {A['old_cases']} non-AI cases: **{A['old_violations']} changed protected text**",
          ""]
    if A["examples_old"]:
        L += ["Examples of what the earlier rules did:", ""]
        for e in A["examples_old"][:6]:
            L.append(f"- *{e['kind']}*: `{e['before']}` → `{e['after_old_rules']}`")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
