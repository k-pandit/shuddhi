#!/usr/bin/env python3
"""
Shuddhi proof of concept: check a Word (.docx) file with the red-pencil rules and
write every correction back into the SAME document as native Word tracked changes.

Formatting is preserved because each edit is made inside the original run (a stretch
of text with one set of formatting) and copies that run's formatting.

Standard library only (Python 3.9+). Usage:
    python shuddhi_docx.py input.docx output.docx [--bengali-script-lang as|bn]
                                                  [--author "Shuddhi"] [--log changes.csv]

Proof-of-concept limits (handled in the full system):
  * A correction that crosses a formatting boundary is listed in the log, not applied.
  * Queries (for example, numbering gaps) are listed in the log only.
  * Text in text boxes and in existing tracked changes is not edited.
  * AI (blue-pencil) suggestions are not part of this script.
"""
import argparse
import copy
import csv
import datetime as dt
import io
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML = "http://www.w3.org/XML/1998/namespace"


def q(tag):
    return "{%s}%s" % (W, tag)


# ----------------------------------------------------------------------------- rules
LANG_NAME = {"en": "English", "as": "Assamese", "bn": "Bengali", "hi": "Hindi"}
INDIC = "ऀ-ॣ०-ॿঀ-৿"          # Devanagari + Bengali blocks minus dandas
WORD = r"(?:[^\W\d_]|[%s])+" % INDIC
BN_DIG, DV_DIG = "০১২৩৪৫৬৭৮৯", "०१२३४५६७८९"
SPELL = {"commitee": "committee", "comittee": "committee", "committe": "committee", "recieve": "receive",
         "recieved": "received", "reciept": "receipt", "seperate": "separate", "occured": "occurred",
         "occurence": "occurrence", "accomodation": "accommodation", "goverment": "government",
         "alloted": "allotted", "upto": "up to", "inspite": "in spite", "untill": "until",
         "sucessful": "successful", "neccessary": "necessary", "begining": "beginning",
         "priviledge": "privilege", "maintainance": "maintenance", "recomend": "recommend",
         "thier": "their", "wich": "which", "adress": "address"}
TERMS = [(re.compile(r"\bKamrup Metro\b"), "Kamrup (Metro)", "Official district name"),
         (re.compile(r"\bGauhati\b(?! High Court| University)"), "Guwahati", "Use the city name Guwahati")]
DESIGNATIONS = ["Additional Deputy Commissioner", "Deputy Commissioner", "District Treasury Officer",
                "Member Secretary", "Chief Secretary", "Principal Secretary"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def ordinal(d):
    return f"{d}{'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')}"


def detect_lang(t, beng_lang):
    beng = len(re.findall(r"[ঀ-৿]", t))
    deva = len(re.findall(r"[ऀ-ॿ]", t))
    latn = len(re.findall(r"[A-Za-z]", t))
    if beng and beng >= deva and beng >= latn:
        return "as" if re.search(r"[ৰৱ]", t) else beng_lang
    if deva and deva >= latn:
        return "hi"
    return "en"


def r_danda(t, lang):
    for m in re.finditer(r"([ঀ-৿ऀ-ॿ])(\s*)\|", t):
        s = m.start() + 1
        yield s, m.end(), "।", "Pipe typed instead of danda"


def r_as_ra(t, lang):
    for m in re.finditer(r"[ঀ-৿]*র[ঀ-৿]*", t):
        yield m.start(), m.end(), m.group().replace("র", "ৰ"), "Bengali RA in Assamese text"


def r_nukta(t, lang):
    fix = {"ড়": "ড়", "ঢ়": "ঢ়", "য়": "য়"}
    for m in re.finditer(r"[ড়ঢ়য়]", t):
        yield m.start(), m.end(), fix[m.group()], "Non-standard encoding of a nukta letter (invisible)"


def r_digits(t, lang):
    dig = DV_DIG if lang == "hi" else BN_DIG
    if not any(d in t for d in dig):
        return
    for m in re.finditer(r"[0-9]+", t):
        yield m.start(), m.end(), "".join(dig[int(c)] for c in m.group()), "Latin digits mixed with Indic digits"


def r_space_punct(t, lang):
    for m in re.finditer(r"(\S)( +)([,;:!?।]|\.(?=\s|$))", t):
        yield m.start(2), m.end(2), "", f"Space before '{m.group(3)}'"


def r_double_space(t, lang):
    for m in re.finditer(r"(\S)( {2,})(?=\S)", t):
        yield m.start(2), m.end(2), " ", "Extra spaces"


def r_repeat(t, lang):
    pat = r"(?<![\w%s])(%s)(\s+)(\1)(?![\w%s])" % (INDIC, WORD, INDIC)
    for m in re.finditer(pat, t, re.IGNORECASE):
        yield m.start(2), m.end(3), "", f"Repeated word '{m.group(1)}'"


def r_spell(t, lang):
    for m in re.finditer(r"\b[A-Za-z]+\b", t):
        fix = SPELL.get(m.group().lower())
        if fix:
            to = fix[0].upper() + fix[1:] if m.group()[0].isupper() else fix
            yield m.start(), m.end(), to, "Spelling"


def r_term(t, lang):
    for rx, to, why in TERMS:
        for m in rx.finditer(t):
            yield m.start(), m.end(), to, "Term bank: " + why


def r_case(t, lang):
    for d in DESIGNATIONS:
        for m in re.finditer(r"\b" + re.escape(d) + r"\b", t, re.IGNORECASE):
            if m.group() != d:
                yield m.start(), m.end(), d, "Designation capitalisation"


def r_date(t, lang):
    for m in re.finditer(r"\b([0-9]{1,2})[-/.]([0-9]{1,2})[-/.]([0-9]{4})\b", t):
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            yield m.start(), m.end(), f"{ordinal(d)} {MONTHS[mo - 1]}, {m.group(3)}", "House date style"


RULES = [("DANDA", ("as", "bn", "hi"), r_danda), ("AS-RA", ("as",), r_as_ra), ("NUKTA", ("as", "bn"), r_nukta),
         ("DIGITS", ("as", "bn", "hi"), r_digits), ("SPACE-PUNCT", ("en", "as", "bn", "hi"), r_space_punct),
         ("DOUBLE-SPACE", ("en", "as", "bn", "hi"), r_double_space), ("REPEAT", ("en", "as", "bn", "hi"), r_repeat),
         ("SPELL", ("en",), r_spell), ("TERM", ("en",), r_term), ("CASE", ("en",), r_case), ("DATE", ("en",), r_date)]


def find_marks(text, lang):
    found = []
    for prio, (rid, langs, fn) in enumerate(RULES):
        if lang in langs:
            for s, e, to, why in fn(text, lang):
                found.append((s, prio, e, to, rid, why))
    found.sort()
    marks, last = [], -1
    for s, _, e, to, rid, why in found:
        if s >= last:
            marks.append({"start": s, "end": e, "to": to, "rule": rid, "why": why, "from": text[s:e]})
            last = e
    return marks


# ----------------------------------------------------------------------------- docx
def run_text(r):
    """Text of a run, and whether it is 'simple' (only rPr and w:t children), so it can be edited."""
    parts, simple = [], True
    for ch in r:
        if ch.tag == q("rPr"):
            continue
        if ch.tag == q("t"):
            parts.append(ch.text or "")
        elif ch.tag == q("tab"):
            parts.append("\t"); simple = False
        elif ch.tag in (q("br"), q("cr")):
            parts.append("\n"); simple = False
        else:
            simple = False
    return "".join(parts), simple


def segments(p):
    """Split a paragraph into ordered segments: (element, text, editable)."""
    segs = []
    for ch in list(p):
        if ch.tag == q("r"):
            t, simple = run_text(ch)
            segs.append((ch, t, simple))
        elif ch.tag in (q("pPr"), q("del"), q("moveFrom")):
            continue
        else:   # hyperlinks, smart tags, existing insertions, fields: counted, never edited
            t = "".join(x.text or "" for x in ch.iter(q("t")))
            if t:
                segs.append((ch, t, False))
    return segs


def make_run(rpr, text, deleted=False):
    r = ET.Element(q("r"))
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = ET.SubElement(r, q("delText") if deleted else q("t"))
    t.text = text
    t.set("{%s}space" % XML, "preserve")
    return r


class Reviser:
    def __init__(self, root, author, beng_lang):
        self.author, self.beng_lang = author, beng_lang
        self.date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids = [int(v) for el in root.iter() for k, v in el.attrib.items() if k == q("id") and v.lstrip("-").isdigit()]
        self.next_id = max(ids + [0]) + 1
        self.log, self.para_no, self.prev_num = [], 0, None

    def rev(self, kind):
        el = ET.Element(q(kind), {q("id"): str(self.next_id), q("author"): self.author, q("date"): self.date})
        self.next_id += 1
        return el

    def walk(self, el):
        for ch in list(el):
            if ch.tag == "{%s}AlternateContent" % MC or ch.tag == q("txbxContent"):
                continue
            if ch.tag == q("p"):
                self.paragraph(ch)
            else:
                self.walk(ch)

    def paragraph(self, p):
        self.para_no += 1
        segs = segments(p)
        text = "".join(t for _, t, _ in segs)
        if not text.strip():
            self.prev_num = None
            return
        lang = detect_lang(text, self.beng_lang)
        # Numbering query (typed numbers only)
        m = re.match(r"^([0-9]+)[.)]\s", text)
        if m:
            n = int(m.group(1))
            if self.prev_num is not None and n != self.prev_num + 1:
                self.log.append([self.para_no, LANG_NAME[lang], "NUMBERING", m.group(1), "",
                                 f"Numbering jumps from {self.prev_num} to {n}", "query (not changed)"])
            self.prev_num = n
        else:
            self.prev_num = None
        marks = find_marks(text, lang)
        if not marks:
            return
        # Map each mark to the segment that fully contains it
        offsets, pos = [], 0
        for el, t, ok in segs:
            offsets.append((pos, pos + len(t), el, t, ok)); pos += len(t)
        per_run = {}
        for mk in marks:
            home = next((o for o in offsets if o[0] <= mk["start"] and mk["end"] <= o[1]), None)
            status = "applied"
            if home is None:
                status = "not applied: crosses a formatting boundary"
            elif not home[4]:
                status = "not applied: inside a field, link or special run"
            else:
                per_run.setdefault(id(home[2]), (home, []))[1].append(mk)
            self.log.append([self.para_no, LANG_NAME[lang], mk["rule"], mk["from"], mk["to"], mk["why"], status])
        for (s0, _, run, t, _), mks in per_run.values():
            rpr = run.find(q("rPr"))
            new, cur = [], 0
            for mk in sorted(mks, key=lambda x: x["start"]):
                a, b = mk["start"] - s0, mk["end"] - s0
                if a > cur:
                    new.append(make_run(rpr, t[cur:a]))
                d = self.rev("del"); d.append(make_run(rpr, t[a:b], deleted=True)); new.append(d)
                if mk["to"]:
                    i = self.rev("ins"); i.append(make_run(rpr, mk["to"])); new.append(i)
                cur = b
            if cur < len(t):
                new.append(make_run(rpr, t[cur:]))
            idx = list(p).index(run)
            p.remove(run)
            for k, el in enumerate(new):
                p.insert(idx + k, el)


def process(src, dst, author, beng_lang):
    with zipfile.ZipFile(src) as z:
        xml = z.read("word/document.xml")
        entries = [(i, z.read(i.filename)) for i in z.infolist()]
    original = xml.decode("utf-8")
    # Word never writes a DTD. Refusing any DOCTYPE/ENTITY blocks XXE and entity-expansion attacks
    # with the standard-library parser. (The production service uses defusedxml/lxml with entities off.)
    if re.search(r"<!(DOCTYPE|ENTITY)", original, re.IGNORECASE):
        raise ValueError("Refusing document.xml that declares a DTD or entities (not produced by Word).")
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(xml), events=["start-ns"]):
        if prefix and not re.match(r"ns\d+$", prefix):
            ET.register_namespace(prefix, uri)
    root = ET.fromstring(xml)
    rv = Reviser(root, author, beng_lang)
    rv.walk(root.find(q("body")))

    out = ET.tostring(root, encoding="unicode")
    # Keep the original root tag (it carries mc:Ignorable and all namespace declarations),
    # adding any declaration ElementTree needed that the original did not have.
    orig_tag = re.search(r"<w:document\b[^>]*>", original).group()
    new_tag = re.search(r"<w:document\b[^>]*>", out).group()
    extra = [d for d in re.findall(r'xmlns:\w+="[^"]*"', new_tag) if d.split("=")[0] not in orig_tag]
    if extra:
        orig_tag = orig_tag[:-1] + " " + " ".join(extra) + ">"
    out = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + out.replace(new_tag, orig_tag, 1)

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in entries:
            z.writestr(info, out.encode("utf-8") if info.filename == "word/document.xml" else data)
    return rv.log


def main():
    ap = argparse.ArgumentParser(description="Write Shuddhi red-pencil corrections into a .docx as tracked changes.")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--bengali-script-lang", choices=["as", "bn"], default="as",
                    help="treat Bengali-script paragraphs as Assamese (as) or Bengali (bn); default as")
    ap.add_argument("--author", default="Shuddhi (red pencil)")
    ap.add_argument("--log", help="write the change log to this CSV file")
    a = ap.parse_args()
    log = process(a.input, a.output, a.author, a.bengali_script_lang)
    applied = sum(1 for r in log if r[-1] == "applied")
    print(f"{applied} corrections written as tracked changes; {len(log) - applied} listed for manual review.")
    for row in log:
        print(f"  para {row[0]:>2} {row[1]:<8} {row[2]:<12} {row[3]!r} -> {row[4]!r}  [{row[6]}]")
    if a.log:
        with open(a.log, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Paragraph", "Language", "Rule", "Before", "After", "Reason", "Status"])
            w.writerows(log)


if __name__ == "__main__":
    sys.exit(main())
