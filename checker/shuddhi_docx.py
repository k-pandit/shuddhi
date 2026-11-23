#!/usr/bin/env python3
"""
Shuddhi: check a Word (.docx) file and write the results into the SAME document.

* Fixes become native Word tracked changes, made inside the original run so formatting is kept.
* Queries (anything touching a number, date, reference, quotation, citation or name, and any rule
  that only asks) become Word comments. They never change the text.
* Every mark passes the shared protected-token guard (shuddhi_core), so no number, amount, date,
  reference or section number can be changed by this tool.
* Runs set in a legacy (non-Unicode) font such as Geetanjali or Ramdhenu are skipped and logged.

Usage:
    python shuddhi_docx.py input.docx output.docx [--lang as|bn|en|hi] [--author NAME] [--log changes.csv]
"""
import argparse
import copy
import csv
import datetime as dt
import io
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

import defusedxml.ElementTree as DET  # hardened parser: no external entities, no entity expansion

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shuddhi_core import check_invariant, check_text, default_speller  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML = "http://www.w3.org/XML/1998/namespace"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
COMMENTS_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENTS_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
LEGACY_FONT = re.compile(r"geetanjali|kalidas|ramdhenu|gist|luit|asamiya|bhabani|sutonny", re.I)
LANG_NAME = {"en": "English", "as": "Assamese", "bn": "Bengali", "hi": "Hindi", "uncertain": "Uncertain"}


def q(tag):
    return "{%s}%s" % (W, tag)


def safe_parse(data, name):
    text = data.decode("utf-8")
    # Word never writes a DTD. Refusing any DOCTYPE/ENTITY blocks XXE and entity-expansion attacks.
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise ValueError(f"Refusing {name}: it declares a DTD or entities (not produced by Word).")
    return text


def run_text(r):
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


def run_is_legacy(r):
    rpr = r.find(q("rPr"))
    fonts = rpr.find(q("rFonts")) if rpr is not None else None
    if fonts is None:
        return False
    return any(LEGACY_FONT.search(v or "") for v in fonts.attrib.values())


def merge_identical_runs(p):
    """Join neighbouring plain runs with identical formatting, so a word split across runs
    by Word's editing history can still be corrected in one place."""
    kids = list(p)
    i = 0
    while i < len(kids) - 1:
        a, b = kids[i], kids[i + 1]
        if a.tag == q("r") and b.tag == q("r"):
            ta, sa = run_text(a)
            tb, sb = run_text(b)
            ra, rb = a.find(q("rPr")), b.find(q("rPr"))
            same = (ET.tostring(ra) if ra is not None else b"") == (ET.tostring(rb) if rb is not None else b"")
            if sa and sb and same and a.find(q("t")) is not None and b.find(q("t")) is not None:
                t = a.find(q("t"))
                t.text = ta + tb
                t.set("{%s}space" % XML, "preserve")
                p.remove(b)
                kids.pop(i + 1)
                continue
        i += 1


def segments(p):
    segs = []
    for ch in list(p):
        if ch.tag == q("r"):
            t, simple = run_text(ch)
            legacy = run_is_legacy(ch)
            segs.append((ch, t, simple and not legacy, legacy))
        elif ch.tag in (q("pPr"), q("del"), q("moveFrom")):
            continue
        else:
            t = "".join(x.text or "" for x in ch.iter(q("t")))
            if t:
                segs.append((ch, t, False, False))
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
    def __init__(self, root, author, declared, spell):
        self.author, self.declared, self.spell = author, declared, spell
        self.date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ids = [int(v) for el in root.iter() for k, v in el.attrib.items() if k == q("id") and v.lstrip("-").isdigit()]
        self.next_id = max(ids + [0]) + 1
        self.log, self.para_no, self.prev_num = [], 0, None
        self.comments = []          # (id, text)
        self.next_cid = 0
        self.seen_digits = False

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

    def add_comment(self, p, anchor_run, text):
        cid = self.next_cid
        self.next_cid += 1
        self.comments.append((cid, text))
        start = ET.Element(q("commentRangeStart"), {q("id"): str(cid)})
        end = ET.Element(q("commentRangeEnd"), {q("id"): str(cid)})
        ref = ET.Element(q("r"))
        rpr = ET.SubElement(ref, q("rPr"))
        ET.SubElement(rpr, q("rStyle"), {q("val"): "CommentReference"})
        ET.SubElement(ref, q("commentReference"), {q("id"): str(cid)})
        kids = list(p)
        if anchor_run is not None and anchor_run in kids:
            idx = kids.index(anchor_run)
            p.insert(idx, start)
            p.insert(idx + 2, end)
            p.insert(idx + 3, ref)
        else:
            first = 1 if kids and kids[0].tag == q("pPr") else 0
            p.insert(first, start)
            p.append(end)
            p.append(ref)

    def paragraph(self, p):
        self.para_no += 1
        merge_identical_runs(p)
        segs = segments(p)
        # Legacy-font text is blanked for checking (same length), so no mark can land inside it.
        check_src = "".join((" " * len(t)) if legacy else t for _, t, _, legacy in segs)
        text = "".join(t for _, t, _, _ in segs)
        if not text.strip():
            self.prev_num = None
            return
        for _, t, _, legacy in segs:
            if legacy and t.strip():
                self.log.append([self.para_no, "Legacy font", "LEGACY-FONT", t[:40], "", "Text in a legacy font: not checked", "not checked"])
        lang, kept, blocked = check_text(check_src, self.declared, self.spell)
        if self.seen_digits:
            kept = [f for f in kept if f["rule"] != "DIGITS"]
        elif any(f["rule"] == "DIGITS" for f in kept):
            self.seen_digits = True
        m = re.match(r"^([0-9]+)[.)]\s", text)
        queries_extra = []
        if m:
            n = int(m.group(1))
            if self.prev_num is not None and n != self.prev_num + 1:
                queries_extra.append(f"Numbering jumps from {self.prev_num} to {n}")
            self.prev_num = n
        else:
            self.prev_num = None
        for b in blocked:
            self.log.append([self.para_no, LANG_NAME[lang], b["rule"], text[b["start"]:b["end"]], b.get("to") or "",
                             b["why"], b["status"]])
        offsets, pos = [], 0
        for el, t, ok, _ in segs:
            offsets.append((pos, pos + len(t), el, t, ok)); pos += len(t)
        per_run, comments = {}, []
        for mk in kept:
            frm = text[mk["start"]:mk["end"]]
            home = next((o for o in offsets if o[0] <= mk["start"] and mk["end"] <= o[1]), None)
            if mk["kind"] == "query":
                comments.append((home[2] if home else None, f"Shuddhi query [{mk['rule']}]: {mk['why']} — '{frm}'"))
                self.log.append([self.para_no, LANG_NAME[lang], mk["rule"], frm, "", mk["why"], "query (Word comment)"])
                continue
            status = "tracked change"
            if home is None:
                status = "not applied: crosses a formatting boundary"
            elif not home[4]:
                status = "not applied: inside a field, link or special run"
            else:
                per_run.setdefault(id(home[2]), (home, []))[1].append(mk)
            self.log.append([self.para_no, LANG_NAME[lang], mk["rule"], frm, mk["to"], mk["why"], status])
        for qtext in queries_extra:
            comments.append((None, "Shuddhi query [NUMBERING]: " + qtext))
            self.log.append([self.para_no, LANG_NAME[lang], "NUMBERING", "", "", qtext, "query (Word comment)"])
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
            # re-anchor comments that pointed at the replaced run
            comments = [(new[0] if a is run else a, c) for a, c in comments]
        for anchor, ctext in comments:
            self.add_comment(p, anchor, ctext)


def comments_xml(comments, author, date):
    root = ET.Element(q("comments"))
    for cid, text in comments:
        c = ET.SubElement(root, q("comment"), {q("id"): str(cid), q("author"): author, q("date"): date, q("initials"): "SH"})
        p = ET.SubElement(c, q("p"))
        r = ET.SubElement(p, q("r"))
        t = ET.SubElement(r, q("t"))
        t.text = text
        t.set("{%s}space" % XML, "preserve")
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + ET.tostring(root, encoding="unicode")


def process(src, dst, author, declared, spell):
    with zipfile.ZipFile(src) as z:
        entries = [(i, z.read(i.filename)) for i in z.infolist()]
    files = {i.filename: d for i, d in entries}
    original = safe_parse(files["word/document.xml"], "document.xml")
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(files["word/document.xml"]), events=["start-ns"]):
        if prefix and not re.match(r"ns\d+$", prefix):
            ET.register_namespace(prefix, uri)
    ET.register_namespace("w", W)
    root = DET.fromstring(files["word/document.xml"])
    before_text = "".join(t.text or "" for t in root.iter(q("t")))
    rv = Reviser(root, author, declared, spell)
    rv.walk(root.find(q("body")))

    out = ET.tostring(root, encoding="unicode")
    orig_tag = re.search(r"<w:document\b[^>]*>", original).group()
    new_tag = re.search(r"<w:document\b[^>]*>", out).group()
    extra = [d for d in re.findall(r'xmlns:\w+="[^"]*"', new_tag) if d.split("=")[0] not in orig_tag]
    if extra:
        orig_tag = orig_tag[:-1] + " " + " ".join(extra) + ">"
    out = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + out.replace(new_tag, orig_tag, 1)
    files["word/document.xml"] = out.encode("utf-8")

    if rv.comments:
        if "word/comments.xml" in files:
            raise ValueError("The input already has Word comments; this proof of concept does not merge them.")
        files["word/comments.xml"] = comments_xml(rv.comments, author, rv.date).encode("utf-8")
        rels = safe_parse(files["word/_rels/document.xml.rels"], "document.xml.rels")
        if COMMENTS_TYPE not in rels:
            rels = rels.replace("</Relationships>",
                                f'<Relationship Id="rIdShuddhiComments" Type="{COMMENTS_TYPE}" Target="comments.xml"/></Relationships>')
        files["word/_rels/document.xml.rels"] = rels.encode("utf-8")
        ct = safe_parse(files["[Content_Types].xml"], "[Content_Types].xml")
        if "/word/comments.xml" not in ct:
            ct = ct.replace("</Types>", f'<Override PartName="/word/comments.xml" ContentType="{COMMENTS_CT}"/></Types>')
        files["[Content_Types].xml"] = ct.encode("utf-8")

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        names = [i.filename for i, _ in entries]
        for n in names + [n for n in files if n not in names]:
            z.writestr(n, files[n])

    # Invariant on the whole document: accepted text (insertions kept, deletions dropped)
    # must contain exactly the same protected tokens as the original.
    r2 = DET.fromstring(files["word/document.xml"])
    after_parts = []
    for el in r2.iter():
        if el.tag == q("t"):
            after_parts.append(el.text or "")
    after_text = "".join(after_parts)
    rv.invariant_ok = check_invariant(before_text, after_text)
    return rv


def main():
    ap = argparse.ArgumentParser(description="Write Shuddhi fixes as tracked changes and queries as comments.")
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--lang", choices=["as", "bn", "en", "hi"], default=None,
                    help="declared language of the document (Bengali-script text is confirmed per paragraph)")
    ap.add_argument("--author", default="Shuddhi")
    ap.add_argument("--log", help="write the change log to this CSV file")
    ap.add_argument("--no-dictionary", action="store_true", help="skip the English dictionary check")
    a = ap.parse_args()
    spell = None if a.no_dictionary else default_speller()
    rv = process(a.input, a.output, a.author, a.lang, spell)
    log = rv.log
    n_fix = sum(1 for r in log if r[-1] == "tracked change")
    n_q = sum(1 for r in log if r[-1].startswith("query"))
    print(f"{n_fix} fixes written as tracked changes; {n_q} queries written as Word comments; "
          f"{sum(1 for r in log if r[-1].startswith('blocked'))} blocked by the guard; "
          f"protected-token invariant: {'PASS' if rv.invariant_ok else 'FAIL'}")
    for row in log:
        print(f"  para {row[0]:>2} {row[1]:<9} {row[2]:<12} {row[3]!r} -> {row[4]!r}  [{row[6]}]")
    if a.log:
        with open(a.log, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Paragraph", "Language", "Rule", "Before", "After", "Reason", "Status"])
            w.writerows(log)
    return 0 if rv.invariant_ok else 1


if __name__ == "__main__":
    sys.exit(main())
