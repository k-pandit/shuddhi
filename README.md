# Shuddhi (শুদ্ধি): Proof Checking for the Assam Gazette

Proposal for the **North-East Seva First Innovation Challenge 2026**, Stream 1.

- **Challenge:** Faster, More Consistent Multilingual Proofreading of Government Documents.
- **Challenge owner:** Directorate of Printing & Stationery, Government of Assam.
- **Applicant:** Jorhat Institute of Science and Technology (JIST), Jorhat, Assam.

> **The Gazette is law. Shuddhi proves the print matches the copy, and never changes a number, name or date on its own.**

## Try the prototype

**Live demo:** https://k-pandit.github.io/shuddhi/

It runs entirely in your browser:
- proof review with four review lanes;
- copy-versus-proof comparison;
- a revise-proof check showing which corrections were made, missed or not asked for;
- approval with a SHA-256 fingerprint.

The sample notification is synthetic. You can also paste your own text.

## Evidence (all re-runnable on an ordinary computer, CPU only)

| Result | Details |
|---|---|
| **0** protected numbers, dates or names changed in **208** adversarial tests | Even when every suggested fix is accepted |
| **11** genuine errors found in three published Assam Gazette issues | No false alarms; every page's content shown unchanged by SHA-256 |
| **96%** of 463 seeded errors found | Against 54% for a plain spell-checker |

The full report is [`docs/Annex_A_Evidence_Report.md`](docs/Annex_A_Evidence_Report.md). The generated outputs are in [`checker/out/`](checker/out/).

## Run it yourself

The commands below use the Windows form of the paths; on Linux or macOS, use `/` instead of `\`.

```bash
pip install -r checker/requirements.txt
```

```bash
python data/fetch_data.py
```

```bash
cd checker
```

```bash
python -m pytest -q tests
```

```bash
python shuddhi_pdf.py check ..\data\gazette\extraordinary_582.pdf --out out\pdf
```

```bash
python bench\run_bench.py --gazette ..\data\gazette --seed 42 --out out\bench
```

On Windows, set `PYTHONIOENCODING=utf-8` first so that Assamese text prints correctly.

## Data and privacy

`data/fetch_data.py` downloads three public Gazette issues from dpns.assam.gov.in, and the open Hunspell English dictionaries from LibreOffice. The Gazette PDFs are not stored in this repository, because some of their pages (name-change, disciplinary and similar notices) carry personal data. The checker excludes those pages by code before checking or measuring anything.

## Licence

[AGPL-3.0](LICENSE).
