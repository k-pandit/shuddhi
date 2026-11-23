"""Protected zones: stretches of official text that must never be edited automatically.

* Quotations (a corrigendum or order quoting other text must quote it exactly).
* Corrigenda: "for 'X' read 'Y'" — the wrong form X is deliberate.
* Citations of Acts, Rules, Orders and notifications ("Gauhati Municipal Corporation Act, 1969").
* Names of institutions (Courts, Universities, Corporations, Commissions, Boards).
"""
import re

ZONE_PATTERNS = [
    ("quotation", re.compile(r"[\"“‘'][^\"”’'\n]{1,200}[\"”’']")),
    ("corrigendum", re.compile(r"\b[Ff]or\s+[\"“‘']?[^\n]{1,80}?[\"”’']?\s+read\s+[\"“‘']?[^\n]{1,80}?[\"”’']?(?=[.;,]|\s*$)")),
    ("corrigendum", re.compile(r"\b(?:CORRIGENDUM|Corrigendum|ERRATUM|Erratum)\b[^\n]*")),
    ("citation", re.compile(r"\b(?:[A-Z][\w()&'-]*\s+){1,9}(?:Act|Rules|Regulations|Order|Ordinance|Code)(?:,?\s*\d{4})?")),
    ("institution", re.compile(r"\b(?:[A-Z][\w&'-]*\s+){0,6}(?:High Court|Supreme Court|University|Municipal Corporation|Corporation|Commission|Board|Council|Tribunal|Authority|Samiti)\b")),
]


def protected_zones(text):
    zones = []
    for kind, rx in ZONE_PATTERNS:
        for m in rx.finditer(text):
            zones.append((m.start(), m.end(), kind))
    zones.sort()
    return zones
