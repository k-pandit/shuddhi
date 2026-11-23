#!/usr/bin/env python3
"""
Shuddhi PDF checker: works on the Press's own PDF proof, never on the DTP file.

Commands
  triage  PDF --out DIR        classify every page (TEXT, LEGACY, MIXED, SCANNED) and list its fonts
  check   PDF --out DIR        triage + English rules + consistency check, annotate a copy of the PDF,
                               prove the page content is unchanged (SHA-256), write a coverage report
  diff    A.pdf B.pdf --accepted accepted.json --out DIR
                               revise-proof check: corrections made, missed and unasked (numbers first)
  survey  DIR --out fonts.csv  font and coverage survey across many Gazette PDFs

Runs on Windows or Linux, CPU only: pdfplumber, pypdf, rapidfuzz, spylls.
"""
import argparse
import csv
import difflib
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText, Highlight, Rectangle, Text
from pypdf.generic import ArrayObject, FloatObject
from rapidfuzz.distance import Levenshtein

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shuddhi_core import check_text, default_speller, protected_spans  # noqa: E402

LEGACY_FONT = re.compile(r"geetanjali|kalidas|ramdhenu|gist|luit|asamiya|bhabani|sutonny", re.I)
UNICODE_AS = re.compile(r"[ঀ-৿]")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def file_sha(path):
    with open(path, "rb") as f:
        return sha(f.read())


# ----------------------------------------------------------------------------- triage
def classify_page(pg):
    area = float(pg.width * pg.height) or 1.0
    img_area = 0.0
    for im in pg.images:
        w = max(0.0, min(im["x1"], pg.width) - max(im["x0"], 0))
        h = max(0.0, min(im["bottom"], pg.height) - max(im["top"], 0))
        img_area += w * h
    img_cov = min(1.0, img_area / area)
    chars = pg.chars
    legacy = [c for c in chars if LEGACY_FONT.search(c.get("fontname", ""))]
    text_chars = [c for c in chars if not LEGACY_FONT.search(c.get("fontname", "")) and c["text"].strip()]
    fonts = Counter(c.get("fontname", "").split("+")[-1] for c in chars)
    uni_as = sum(1 for c in chars if UNICODE_AS.match(c["text"]))
    if img_cov > 0.5 and len(text_chars) < 600:
        cls = "SCANNED"
    elif legacy and len(legacy) >= 0.6 * max(1, len(chars)):
        cls = "LEGACY"
    elif legacy:
        cls = "MIXED"
    elif text_chars:
        cls = "TEXT"
    else:
        cls = "EMPTY"
    return {"class": cls, "chars": len(chars), "legacy_chars": len(legacy), "text_chars": len(text_chars),
            "image_cover": round(img_cov, 3), "unicode_assamese_chars": uni_as,
            "fonts": dict(fonts.most_common(6))}


def triage(path):
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, pg in enumerate(pdf.pages, 1):
            info = classify_page(pg)
            info["page"] = i
            pages.append(info)
    return pages


# ----------------------------------------------------------------------------- privacy filter
EXCLUDE = [
    ("name change", re.compile(r"change (?:of|in) (?:my )?name|name change|hereby declare that|affidavit", re.I)),
    ("disciplinary", re.compile(r"disciplinary|departmental proceeding|inquiry report|show cause|dismiss(?:al|ed) from service|penalty of", re.I)),
    ("vigilance", re.compile(r"vigilance|anti[- ]corruption|disproportionate assets|forged|forgery|embezzle|misappropriat|defalcation|(?<![A-Za-z])F\.?I\.?R\.?(?![A-Za-z])|criminal case|charge ?sheet|recovery of", re.I)),
    ("arrest or suspension", re.compile(r"\barrest(?:ed)?\b|placed under suspension|is suspended|judicial custody", re.I)),
    ("private person", re.compile(r"\b(?:S/o|D/o|W/o|son of|daughter of|wife of)\b", re.I)),
]


def privacy_reason(text):
    for reason, rx in EXCLUDE:
        if rx.search(text):
            return reason
    return None


# ----------------------------------------------------------------------------- text lines with positions
def page_lines(pg):
    """Lines of non-legacy words, each with its words' bounding boxes (PDF top-based coordinates)."""
    words = pg.extract_words(extra_attrs=["fontname"], keep_blank_chars=False, use_text_flow=True)
    words = [w for w in words if not LEGACY_FONT.search(w.get("fontname", ""))]
    lines = []
    for w in sorted(words, key=lambda w: (round(w["top"] / 3), w["x0"])):
        if lines and abs(lines[-1]["top"] - w["top"]) < 3 and w["x0"] >= lines[-1]["words"][-1]["x1"] - 1:
            lines[-1]["words"].append(w)
        else:
            lines.append({"top": w["top"], "words": [w]})
    out = []
    for ln in lines:
        text, spans, pos = "", [], 0
        for k, w in enumerate(ln["words"]):
            if k:              # one space between words: gaps in a justified PDF line are layout, not typing
                text += " "
                pos += 1
            spans.append((pos, pos + len(w["text"]), w))
            text += w["text"]
            pos += len(w["text"])
        out.append({"text": text, "spans": spans})
    return out


def bbox_for(spans, s, e):
    ws = [w for a, b, w in spans if a < e and s < b] or [min(spans, key=lambda t: abs(t[0] - s))[2]]
    return (min(w["x0"] for w in ws), min(w["top"] for w in ws), max(w["x1"] for w in ws), max(w["bottom"] for w in ws))


# ----------------------------------------------------------------------------- consistency check
PAREN = re.compile(r"\(([A-Za-z][A-Za-z .&-]{2,30})\)")
TITLE = re.compile(r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:of|and|&|the)?\s*(?:[A-Z][a-z]+|[A-Z]{2,})){1,4}\b")


def consistency_pairs(items):
    """items: list of (page, line_index, start, end, phrase). Pairs of phrases in one document that
    differ by at most 2 letters (ignoring case) but are not identical: likely inconsistent spellings."""
    by_norm = defaultdict(list)
    for it in items:
        by_norm[it[4].casefold()].append(it)
    keys = list(by_norm)
    pairs = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            if abs(len(a) - len(b)) > 2 or min(len(a), len(b)) < 4:
                continue
            if re.sub(r"[^a-z]", "", a) == re.sub(r"[^a-z]", "", b):
                continue
            if re.search(r"\d", a + b):
                continue
            roman = r"(?<![a-z])[ivxlc]+(?![a-z])"
            if re.sub(roman, "", a) == re.sub(roman, "", b):     # PART II vs PART IX: different numbers, not a typo
                continue
            pa = {it[0] for it in by_norm[a]}
            pb = {it[0] for it in by_norm[b]}
            if not any(abs(x - y) <= 1 for x in pa for y in pb):  # compare within one notice (same or next page)
                continue
            d = Levenshtein.distance(a, b)
            if 0 < d <= (1 if min(len(a), len(b)) < 7 else 2):
                sing = lambda x: " ".join(w.rstrip("s") for w in x.split())
                if sing(a) == sing(b):                    # plural forms are not inconsistencies
                    continue
                if a.endswith(b) or b.endswith(a):        # Movable / Immovable: a prefix changes the meaning
                    continue
                pairs.append((by_norm[a], by_norm[b], d))
    return pairs


# ----------------------------------------------------------------------------- check + annotate
def check_pdf(path, outdir, spell, max_pages=None):
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    pages = triage(path)
    findings, excluded, phrases = [], [], []
    words_checked = words_total = legacy_words = 0
    line_store = {}
    with pdfplumber.open(path) as pdf:
        for info in pages:
            i = info["page"]
            if max_pages and i > max_pages:
                break
            pg = pdf.pages[i - 1]
            all_words = pg.extract_words()
            words_total += len(all_words)
            lw = sum(1 for w in pg.extract_words(extra_attrs=["fontname"]) if LEGACY_FONT.search(w.get("fontname", "")))
            legacy_words += lw
            if info["class"] in ("SCANNED", "EMPTY"):
                continue
            lines = page_lines(pg)
            page_text = "\n".join(l["text"] for l in lines)
            reason = privacy_reason(page_text)
            info["privacy_flag"] = reason
            if reason:             # personal data: not checked, not stored, not used in any benchmark
                info["class_note"] = "excluded: " + reason
                continue
            for li, ln in enumerate(lines):
                line_store[(i, li)] = ln
                words_checked += len(ln["spans"])
                skip = set()
                if li and lines[li - 1]["text"].endswith(("-", "‐", "­", "‑")) and ln["spans"]:
                    skip.add(ln["spans"][0][0])          # second half of a word hyphenated at the line end
                if li <= 1 and ln["spans"] and ln["text"][:1].islower():
                    skip.add(ln["spans"][0][0])          # a page may begin with the end of a word hyphenated on the previous page
                if ln["text"].endswith(("-", "‐", "­", "‑")) and ln["spans"]:
                    skip.add(ln["spans"][-1][0])         # first half
                _, kept, blocked = check_text(ln["text"], "en", spell, skip_spell=skip)
                for f in kept:
                    f.update(page=i, line=li, bbox=bbox_for(ln["spans"], f["start"], f["end"]))
                    findings.append(f)
                for m in PAREN.finditer(ln["text"]):
                    phrases.append((i, li, m.start(1), m.end(1), m.group(1).strip()))
                for m in TITLE.finditer(ln["text"]):
                    phrases.append((i, li, m.start(), m.end(), m.group()))
    # consistency within the document
    for group_a, group_b, d in consistency_pairs(phrases):
        a, b = group_a[0], group_b[0]
        for (pg_i, li, s, e, ph), other in ((a, b), (b, a)):
            ln = line_store[(pg_i, li)]
            findings.append({"rule": "CONSISTENCY", "kind": "query", "bulk": False, "lane": "one", "source": "consistency",
                             "page": pg_i, "line": li, "start": s, "end": e, "from": ph, "to": None,
                             "why": f"'{ph}' (p{pg_i}) vs '{other[4]}' (p{other[0]}): same name spelled differently?",
                             "bbox": bbox_for(ln["spans"], s, e), "id": hashlib.sha256(f"C|{ph}|{other[4]}".encode()).hexdigest()[:12]})

    # annotate a copy; prove the page content did not change
    reader = PdfReader(path)
    writer = PdfWriter()
    writer.append(reader)
    before = [sha(p.get_contents().get_data()) if p.get_contents() is not None else "" for p in reader.pages]
    for f in findings:
        pno = f["page"] - 1
        page = writer.pages[pno]
        H = float(page.mediabox.height)
        x0, top, x1, bottom = f["bbox"]
        rect = (x0 - 1, H - bottom - 1, x1 + 1, H - top + 1)
        quad = ArrayObject([FloatObject(v) for v in (rect[0], rect[3], rect[2], rect[3], rect[0], rect[1], rect[2], rect[1])])
        color = "ffb000" if f["kind"] == "query" else "ff6b6b"
        writer.add_annotation(pno, Highlight(rect=rect, quad_points=quad, highlight_color=color))
        note = f"[{f['rule']}] {f['why']}" + (f" -> '{f['to']}'" if f.get("to") else "")
        writer.add_annotation(pno, Text(rect=(rect[2] + 2, rect[1], rect[2] + 18, rect[1] + 16), text=note[:500], open=False))
    for info in pages:
        if max_pages and info["page"] > max_pages:
            break
        pno = info["page"] - 1
        page = writer.pages[pno]
        W, H = float(page.mediabox.width), float(page.mediabox.height)
        if info["class"] in ("SCANNED", "LEGACY"):
            writer.add_annotation(pno, Rectangle(rect=(8, 8, W - 8, H - 8), interior_color=None))
            writer.add_annotation(pno, FreeText(text=f"Shuddhi: NOT CHECKED ({info['class'].lower()} page)",
                                                rect=(12, H - 30, 300, H - 12), font_size="10pt", font_color="555555",
                                                border_color="999999", background_color="eeeeee"))
        elif info["class"] == "MIXED":
            writer.add_annotation(pno, FreeText(text="Shuddhi: legacy-font text on this page NOT CHECKED",
                                                rect=(12, H - 30, 330, H - 12), font_size="10pt", font_color="555555",
                                                border_color="999999", background_color="eeeeee"))
    out_pdf = os.path.join(outdir, base + "_shuddhi.pdf")
    with open(out_pdf, "wb") as fh:
        writer.write(fh)
    after_reader = PdfReader(out_pdf)
    after = [sha(p.get_contents().get_data()) if p.get_contents() is not None else "" for p in after_reader.pages]
    unchanged = before == after

    classes = Counter(p["class"] for p in pages if not max_pages or p["page"] <= max_pages)
    by_rule = Counter(f["rule"] for f in findings)
    by_kind = Counter(f["kind"] for f in findings)
    coverage = {
        "file": os.path.basename(path), "file_sha256": file_sha(path), "output_sha256": file_sha(out_pdf),
        "pages": len(pages), "pages_by_class": dict(classes),
        "words_total": words_total, "words_checked": words_checked, "legacy_font_words_not_checked": legacy_words,
        "percent_words_checked": round(100.0 * words_checked / max(1, words_total), 1),
        "unicode_assamese_chars": sum(p["unicode_assamese_chars"] for p in pages),
        "findings_total": len(findings), "findings_by_kind": dict(by_kind), "findings_by_rule": dict(by_rule),
        "page_content_unchanged": unchanged,
        "pages_excluded_personal_data": [p["page"] for p in pages if p.get("privacy_flag")],
        "words_excluded_personal_data": 0,
        "page_detail": pages,
    }
    with open(os.path.join(outdir, base + "_coverage.json"), "w", encoding="utf-8") as fh:
        json.dump(coverage, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(outdir, base + "_findings.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "page", "rule", "kind", "bulk", "protected", "from", "to", "why"])
        for f in sorted(findings, key=lambda f: (f["page"], f["line"], f["start"])):
            # personal names are not written out for pages carrying a privacy flag
            hide = any(p["page"] == f["page"] and p.get("privacy_flag") for p in pages)
            w.writerow([f["id"], f["page"], f["rule"], f["kind"], f.get("bulk"), f.get("protected"),
                        "[withheld]" if hide else f["from"], "" if hide else (f.get("to") or ""), f["why"] if not hide else f["rule"]])
    write_coverage_md(coverage, findings, os.path.join(outdir, base + "_coverage.md"))
    return coverage, findings


def write_coverage_md(cov, findings, path):
    L = [f"# Coverage report: {cov['file']}", "",
         f"- File SHA-256: `{cov['file_sha256']}`",
         f"- Annotated copy SHA-256: `{cov['output_sha256']}`",
         f"- **Page content unchanged after annotation: {'YES' if cov['page_content_unchanged'] else 'NO'}** (SHA-256 of every page's content stream, before and after)",
         f"- Pages: {cov['pages']}; by class: " + ", ".join(f"{k} {v}" for k, v in sorted(cov['pages_by_class'].items())),
         f"- Words checked: {cov['words_checked']} of {cov['words_total']} ({cov['percent_words_checked']}%); legacy-font words not checked: {cov['legacy_font_words_not_checked']}",
         f"- Unicode Assamese characters in the file: {cov['unicode_assamese_chars']}",
         f"- Findings: {cov['findings_total']} (" + ", ".join(f"{k} {v}" for k, v in cov['findings_by_kind'].items()) + ")",
         "", "| Page | Class | Characters | Legacy-font characters | Image cover | Main fonts |", "|---|---|---|---|---|---|"]
    for p in cov["page_detail"]:
        L.append(f"| {p['page']} | {p['class']} | {p['chars']} | {p['legacy_chars']} | {p['image_cover']} | "
                 + ", ".join(list(p["fonts"])[:3]) + " |")
    cons = [f for f in findings if f["rule"] == "CONSISTENCY"]
    if cons:
        L += ["", "## Consistency queries", ""]
        seen = set()
        for f in cons:
            if f["why"] not in seen:
                seen.add(f["why"])
                L.append(f"- {f['why']}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


# ----------------------------------------------------------------------------- revise-proof diff
TOKEN = re.compile(r"\S+")


def pdf_text(path):
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def diff_rounds(a_pdf, b_pdf, accepted):
    """Compare the revise proof B with (proof A + accepted corrections).
    accepted: list of {"from": str, "to": str} corrections the reviewer accepted on proof A."""
    a = pdf_text(a_pdf)
    expected = a
    for c in accepted:
        expected = expected.replace(c["from"], c["to"], 1)
    b = pdf_text(b_pdf)
    results = []
    for c in accepted:
        if c["to"] in b and (c["from"] not in b or c["from"] in c["to"]):
            results.append({"type": "made", "detail": f"'{c['from']}' -> '{c['to']}'"})
        else:
            results.append({"type": "missed", "detail": f"'{c['from']}' should read '{c['to']}'", "high_risk": bool(re.search(r"\d", c["from"] + c["to"]))})
    et, bt = TOKEN.findall(expected), TOKEN.findall(b)
    sm = difflib.SequenceMatcher(a=et, b=bt, autojunk=False)
    missed = [c for c, r in zip(accepted, results) if r["type"] == "missed"]
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        exp, got = " ".join(et[i1:i2]), " ".join(bt[j1:j2])
        if any((exp and exp in c["to"]) or (got and got in c["from"]) for c in missed):
            continue            # already reported as a missed correction
        results.append({"type": "unasked", "detail": f"expected '{exp}' but proof has '{got}'",
                        "high_risk": bool(re.search(r"\d", exp + got))})
    order = {"unasked": 0, "missed": 1, "made": 2}
    results.sort(key=lambda r: (not r.get("high_risk", False), order[r["type"]]))
    return results


# ----------------------------------------------------------------------------- survey
def survey(folder, out_csv):
    rows = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(".pdf"):
            continue
        pages = triage(os.path.join(folder, name))
        cls = Counter(p["class"] for p in pages)
        fonts = Counter()
        for p in pages:
            fonts.update(p["fonts"])
        legacy = sorted({f for f in fonts if LEGACY_FONT.search(f)})
        rows.append({"file": name, "pages": len(pages), **{k: cls.get(k, 0) for k in ("TEXT", "MIXED", "LEGACY", "SCANNED", "EMPTY")},
                     "legacy_fonts": "; ".join(legacy), "unicode_assamese_chars": sum(p["unicode_assamese_chars"] for p in pages)})
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("triage"); t.add_argument("pdf"); t.add_argument("--out", required=True)
    c = sub.add_parser("check"); c.add_argument("pdf"); c.add_argument("--out", required=True)
    c.add_argument("--no-dictionary", action="store_true")
    d = sub.add_parser("diff"); d.add_argument("a"); d.add_argument("b"); d.add_argument("--accepted", required=True); d.add_argument("--out", required=True)
    s = sub.add_parser("survey"); s.add_argument("folder"); s.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "triage":
        os.makedirs(a.out, exist_ok=True)
        pages = triage(a.pdf)
        p = os.path.join(a.out, os.path.splitext(os.path.basename(a.pdf))[0] + "_triage.json")
        json.dump(pages, open(p, "w", encoding="utf-8"), indent=1)
        print(Counter(x["class"] for x in pages), "->", p)
    elif a.cmd == "check":
        cov, findings = check_pdf(a.pdf, a.out, None if a.no_dictionary else default_speller())
        print(json.dumps({k: v for k, v in cov.items() if k != "page_detail"}, indent=1, ensure_ascii=False))
    elif a.cmd == "diff":
        res = diff_rounds(a.a, a.b, json.load(open(a.accepted, encoding="utf-8")))
        os.makedirs(a.out, exist_ok=True)
        L = ["# Revise-proof check (SYNTHETIC test pair)", "", "| # | Result | High risk | Detail |", "|---|---|---|---|"]
        for i, r in enumerate(res, 1):
            L.append(f"| {i} | {r['type']} | {'YES' if r.get('high_risk') else ''} | {r['detail']} |")
        cnt = Counter(r["type"] for r in res)
        L += ["", f"Made: {cnt['made']}  Missed: {cnt['missed']}  Unasked: {cnt['unasked']}"]
        open(os.path.join(a.out, "round_report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
        print("\n".join(L))
    elif a.cmd == "survey":
        rows = survey(a.folder, a.out)
        for r in rows:
            print(r)


if __name__ == "__main__":
    main()
