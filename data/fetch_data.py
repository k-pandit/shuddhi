"""Download the public data the Shuddhi evidence uses.

* Three public issues of the Assam Gazette from dpns.assam.gov.in, saved to data/gazette/
* The open Hunspell English dictionaries (en_GB, en_US) from LibreOffice, saved to data/dict/

Nothing here is committed to the repository: some Gazette pages carry personal data, and the
checker excludes those pages by code before checking or measuring anything.
"""
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {
    "gazette/weekly_45_2026-11-11.pdf": "https://dpns.assam.gov.in/sites/default/files/public_utility/No.%2045%20dated%2011-11-26.pdf",
    "gazette/weekly_44_2026-11-04.pdf": "https://dpns.assam.gov.in/sites/default/files/public_utility/No.%2044%20dated%2004-11-26.pdf",
    "gazette/extraordinary_582.pdf": "https://dpns.assam.gov.in/sites/default/files/swf1/dms7_no._582_e-_513778-999_dated_31-08-26.pdf",
    "dict/en_GB.aff": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/en_GB.aff",
    "dict/en_GB.dic": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/en_GB.dic",
    "dict/en_US.aff": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/en_US.aff",
    "dict/en_US.dic": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/en_US.dic",
}

for rel, url in FILES.items():
    dst = os.path.join(HERE, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        print("already present:", rel)
        continue
    print("downloading", rel)
    req = urllib.request.Request(url, headers={"User-Agent": "shuddhi-evidence/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        f.write(r.read())
print("done")
