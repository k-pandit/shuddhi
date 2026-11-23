"""Fixed, explainable rules ("red pencil").

Each rule declares:
  langs  - languages it runs on (after language confirmation; 'as' rules never run on 'uncertain')
  kind   - 'fix' (a correction the reviewer may accept) or 'query' (asks the reviewer to look; never applied)
  bulk   - True only for danda, nukta, spacing and encoding fixes (safe classes that may be accepted per rule)
"""
import re

INDIC = "ऀ-ॣ०-ॿঀ-৿"      # Devanagari and Bengali-Assamese blocks (no dandas)
WORD = r"(?:[^\W\d_]|[%s])+" % INDIC
BN_DIG, DV_DIG = "০১২৩৪৫৬৭৮৯", "०१२३४५६७८९"

# Common misspellings in official English (small curated list; the dictionary does the rest).
MISSPELL = {"commitee": "committee", "comittee": "committee", "committe": "committee", "recieve": "receive",
            "recieved": "received", "reciept": "receipt", "seperate": "separate", "occured": "occurred",
            "occurence": "occurrence", "accomodation": "accommodation", "goverment": "government",
            "govenment": "government", "alloted": "allotted", "untill": "until", "sucessful": "successful",
            "neccessary": "necessary", "begining": "beginning", "priviledge": "privilege",
            "maintainance": "maintenance", "recomend": "recommend", "thier": "their", "wich": "which",
            "adress": "address", "notifiction": "notification", "secratary": "secretary",
            "secetary": "secretary", "departmnet": "department", "deparment": "department",
            "comissioner": "commissioner", "commisioner": "commissioner", "goverrnor": "governor",
            "officier": "officer", "eligable": "eligible", "immediatly": "immediately",
            "apointment": "appointment", "appointmnet": "appointment", "persuant": "pursuant"}
# Indian and official English words a general (British) dictionary does not know.
ALLOW = {"lakh", "lakhs", "crore", "crores", "tehsil", "mouza", "mauza", "gaon", "panchayat", "panchayats",
         "zilla", "parishad", "katha", "kotha", "lecha", "bigha", "mahkuma", "mauzadar", "gaonburah", "gaonbura", "sabha", "samiti", "patta", "dag", "pattadar", "circle", "anchalik",
         "gazetted", "nodal", "dispur", "ex-officio", "vide", "inter-alia", "w.e.f", "sanctioned", "honourable",
         "aforesaid", "hereinafter", "thereof", "therein", "herein", "whereof", "undersigned", "deputationist",
         "officiating", "superannuation", "incumbency", "notified", "notifying", "empanelled", "empanelment",
         "programme", "programmes", "infructuous", "adjudicating", "suo", "motu", "mutatis", "mutandis", "tribals", "sl", "smti", "shri", "sri", "dtd", "govt", "deptt", "addl"}
TERMS = [(re.compile(r"\bKamrup Metro\b"), "Kamrup (Metro)", "Official district name"),
         (re.compile(r"\bGauhati\b"), "Guwahati", "City name is Guwahati (institution names keep 'Gauhati')")]
DESIGNATIONS = ["Additional Chief Secretary", "Additional Deputy Commissioner", "Deputy Commissioner",
                "District Treasury Officer", "Member Secretary", "Chief Secretary", "Principal Secretary",
                "Commissioner & Secretary", "Joint Secretary", "Deputy Secretary", "Under Secretary"]


class Rule:
    def __init__(self, rid, langs, kind, bulk, fn, lane):
        self.rid, self.langs, self.kind, self.bulk, self.fn, self.lane = rid, langs, kind, bulk, fn, lane


def r_danda(t, ctx):
    for m in re.finditer(r"([%s])(\s*)\|" % INDIC, t):
        yield m.start(2), m.end(), "।", "Pipe typed instead of danda"


def r_as_ra(t, ctx):
    for m in re.finditer(r"[ঀ-৿]*[রব][ঀ-৿]*", t):
        w = m.group()
        if "র" in w:
            yield m.start(), m.end(), w.replace("র", "ৰ"), "Bengali letter র in Assamese text (Assamese uses ৰ)"


def r_nukta(t, ctx):
    fix = {"ড়": "ড়", "ঢ়": "ঢ়", "য়": "য়"}
    for m in re.finditer("ড়|ঢ়|য়", t):
        yield m.start(), m.end(), fix[m.group()], "Non-standard encoding of a nukta letter (invisible difference)"


def r_digits(t, ctx):
    dig = DV_DIG if ctx["lang"] == "hi" else BN_DIG
    if any(d in t for d in dig):
        for m in re.finditer(r"[0-9]+", t):
            yield m.start(), m.end(), None, "Latin digits mixed with Indic digits: confirm the intended style"
            return


def r_space_punct(t, ctx):
    for m in re.finditer(r"(\S)( +)([,;!?।]|\.(?=\s|$))", t):
        yield m.start(2), m.end(2), "", f"Space before '{m.group(3)}'"


def r_double_space(t, ctx):
    for m in re.finditer(r"(\S)( {2,})(?=\S)", t):
        yield m.start(2), m.end(2), " ", "Extra spaces"


def r_repeat(t, ctx):
    pat = r"(?<![\w%s])(%s)(\s+)(\1)(?![\w%s])" % (INDIC, WORD, INDIC)
    for m in re.finditer(pat, t, re.IGNORECASE):
        if ctx["lang"] == "en":
            yield m.start(2), m.end(3), "", f"Repeated word '{m.group(1)}'"
        else:   # reduplication is normal in Indic languages (লাহে লাহে, धीरे धीरे): ask, never fix
            yield m.start(1), m.end(3), None, f"Repeated word '{m.group(1)}': check whether intended"


def r_spell(t, ctx):
    spell = ctx.get("spell")
    for m in re.finditer(r"(?<![\w@/.-])[A-Za-z][a-z]+(?![\w@/-])(?!\.[a-z])", t):   # skip web addresses
        if ctx.get("skip_spell") and m.start() in ctx["skip_spell"]:
            continue
        w = m.group()
        low = w.lower()
        if low in MISSPELL:
            fix = MISSPELL[low]
            yield m.start(), m.end(), (fix[0].upper() + fix[1:] if w[0].isupper() else fix), "Spelling"
            continue
        # Dictionary check only for lower-case words of 4+ letters: capitalised words are often
        # names of people and places, which a general dictionary does not know.
        if spell is not None and w.islower() and len(w) >= 4 and low not in ALLOW and not spell.known(w):
            sug = spell.suggest(w)
            yield m.start(), m.end(), sug, "Not in the dictionary" + ("" if sug else ": no suggestion")


def r_term(t, ctx):
    for rx, to, why in TERMS:
        for m in rx.finditer(t):
            yield m.start(), m.end(), to, "Term list: " + why


def r_case(t, ctx):
    for d in DESIGNATIONS:
        for m in re.finditer(r"\b" + re.escape(d) + r"\b", t, re.IGNORECASE):
            if m.group() != d and m.group() != d.upper():
                yield m.start(), m.end(), d, "Designation capitalisation"


def r_date(t, ctx):
    for m in re.finditer(r"\b[0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{4}\b", t):
        yield m.start(), m.end(), None, "Numeric date: confirm day-month order and house style"


RULES = [
    Rule("DANDA", ("as", "bn", "hi"), "fix", True, r_danda, "bulk"),
    Rule("AS-RA", ("as",), "fix", False, r_as_ra, "group"),
    Rule("NUKTA", ("as", "bn"), "fix", True, r_nukta, "bulk"),
    Rule("DIGITS", ("as", "bn", "hi"), "query", False, r_digits, "note"),
    Rule("SPACE-PUNCT", ("en", "as", "bn", "hi"), "fix", True, r_space_punct, "bulk"),
    Rule("DOUBLE-SPACE", ("en", "as", "bn", "hi"), "fix", True, r_double_space, "bulk"),
    Rule("REPEAT", ("en", "as", "bn", "hi"), "fix", False, r_repeat, "one"),
    Rule("SPELL", ("en",), "fix", False, r_spell, "group"),
    Rule("TERM", ("en",), "fix", False, r_term, "group"),
    Rule("CASE", ("en",), "fix", False, r_case, "group"),
    Rule("DATE", ("en",), "query", False, r_date, "one"),
]
RULE_BY_ID = {r.rid: r for r in RULES}
