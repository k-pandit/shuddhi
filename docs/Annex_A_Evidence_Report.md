# Annex A: Shuddhi Evidence Report

*Proposal: Shuddhi (শুদ্ধি), proof checking for the Assam Gazette. NESFIC 2026, Stream 1. Applicant: Jorhat Institute of Science and Technology. All results were produced on 20 November 2026 on an ordinary laptop (CPU only, no GPU), using public data, and every test can be rerun from the repository.*

## A.1 Summary

| Evidence | Result |
|---|---|
| **Safety: protected-token test** (208 adversarial cases, worst-case reviewer accepts every fix) | **0 protected-token edits.** The rules of our own earlier prototype changed protected text in **112 of 160** of the same cases. |
| **Unsafe AI suggestions** (48 mock AI rewrites of an amount, a date or an official name) | **0 applied:** 17 blocked by the guard, 10 turned into queries, 21 dropped because a query already covered the text |
| **Trap file** (20 valid official texts: file numbers, amounts, dates, a corrigendum, Act citations, Bengali text, doubled Indic words) | **0 changes**, even when every fix is accepted. 24 of 24 automated safety tests pass. |
| **Seeded-error benchmark** on public Gazette English (463 errors of 8 types) | Shuddhi found **96%** (95% CI 94–98%). A plain dictionary spell-checker found **54%**. |
| **False alarms** on unseeded Gazette text | **2.1 marks per 1,000 words**, against **46.3** for the plain spell-checker |
| **Real published Gazette issues** (3 issues, 107 pages) | **11 genuine published errors found, 0 false alarms**, including "(PLAIN)" vs "(Plan)" in Extraordinary No. 582 |
| **Layout preserved** | Page content of every annotated PDF is **byte-identical** to the original (SHA-256 per page). Word output opens in Microsoft Word with native tracked changes and comments. |
| **Revise-proof check** (synthetic pair) | Found exactly what was seeded: **4 made, 1 missed, 2 not asked for**, with the changed amount listed first |
| **Font survey** | **0 Unicode Assamese characters** in all three issues. Assamese is set in **Geetanjali** (5 variants) and **Kalidas**. 11 of 107 pages are scanned images. |

## A.2 What the published Gazette is made of

`shuddhi_pdf.py triage` classifies each page by its fonts and images.

| Issue | Pages | Text | Mixed (text + legacy font) | Scanned | Unicode Assamese characters | Legacy fonts found |
|---|---|---|---|---|---|---|
| Weekly No. 45, 11 Nov 2026 | 52 | 39 | 3 | 10 | 0 | Geetanjali (light, bold, plight, pbold), Kalidas Bold |
| Weekly No. 44, 4 Nov 2026 | 53 | 48 | 4 | 1 | 0 | Geetanjali (5 variants), Kalidas Bold |
| Extraordinary No. 582 | 2 | 2 | 0 | 0 | 0 | none (Assamese header drawn as images) |

**Consequence for the design:** a tool that reads only Unicode cannot check a single Assamese word of the published Gazette. Shuddhi therefore reports coverage honestly on every page. Legacy-font and scanned regions are boxed "not checked", and mapping Geetanjali to Unicode is a Must in the build.

## A.3 Real errors found in the published Gazette

Pages with personal data were excluded by code before checking: 30 pages of No. 45 and 40 of No. 44, mostly Part IX notices. The remaining text pages were checked, and every mark was reviewed by hand against the page.

| Issue, page | Shuddhi's mark | Verdict |
|---|---|---|
| Extraordinary No. 582, p 1 and p 2 | Query: "DEPARTMENT OF TRIBAL AFFAIRS (**PLAIN**)" in the heading vs "Department of Tribal Affairs (**Plan**)" in the signature | Genuine inconsistency. Both are real words, so no spell-checker can see it. |
| Weekly No. 45, p 9 | "is **granated** earned leave" → granted | Genuine typing error |
| Weekly No. 45, p 9 | "is **gramated** earned leave" | Genuine typing error. The first suggestion ("gradated") is wrong, so the reviewer types "granted". |
| Weekly No. 44, p 3 | "Quality Control **,**" and "Secretary **,**": space before a comma | Genuine (2) |
| Weekly No. 44, p 5 | "Assam **,**": space before a comma | Genuine |
| Weekly No. 44, p 16 | Space before a comma or full stop in signature blocks | Genuine (4) |
| Weekly No. 44, p 21 | "Offices **financialy** independent of Government" → financially | Genuine typing error |
| Weekly No. 44, p 53 | Query: numeric date "4-11-2026" | A style question, not an error claim. Shuddhi never rewrites a date. |

**Total:** 11 genuine published errors found, 1 style query, and no false alarms on the checked pages. Every page's content stream is unchanged after annotation, so the printed page cannot have been altered.

## A.4 Seeded-error benchmark (`bench/run_bench.py`, seed 42)

**Corpus:**
- 373 lines (4,257 words) of English from the text pages of the three issues, in 46 documents.
- Pages with personal data, scanned pages and legacy-font text are excluded.
- The corpus SHA-256 and every page used or excluded are recorded in `manifest.json`.

**Seeding:**
- Errors of 8 types are seeded with a fixed random seed.
- 20% of documents are left clean.

**Baseline:** a plain Hunspell spell-checker with the en_GB and en_US dictionaries, which is what most office tools offer.

| Error type | Seeded | Shuddhi recall (95% CI) | Plain spell-checker |
|---|---|---|---|
| Letters swapped | 53 | 100% (93–100%) | 100% |
| Letter dropped | 72 | 97% (90–99%) | 100% |
| Letter doubled | 67 | 98% (92–100%) | 100% |
| Common official misspelling | 25 | 100% (87–100%) | 100% |
| Word repeated | 89 | 100% (96–100%) | 0% |
| Space before punctuation | 38 | 100% (91–100%) | 0% |
| Double space | 86 | 100% (96–100%) | 0% |
| Name spelled differently within a notice | 33 | 58% (41–73%) | 100% |
| **All** | **463** | **96% (94–98%)** | **54%** |

| Measure | Shuddhi | Plain spell-checker |
|---|---|---|
| Precision of marks in seeded paragraphs | 100% | 74% |
| Marks per 1,000 words of unseeded Gazette text | 2.1 | 46.3 |
| First suggestion restores the original word | 177 of 213 | 172 of 217 |

**Reading these numbers honestly:**
- **Rule-friendly errors.** Seven of the eight error types are ones that rules detect well. Real-word errors ("form" for "from") and grammar errors are not measured here. They need the linguist-labelled test set planned for phase P0.
- **Names.** Shuddhi does not dictionary-check capitalised words, because they are usually names of people and places. A plain spell-checker flags every unknown name. That is why it catches more misspelt names (100% against 58%) but raises 22 times as many marks on clean text.
- **Assamese, Hindi and Bengali.** These benchmarks cover English only, because the published Gazette contains no Unicode Indic text. The Assamese, Hindi and Bengali rules are covered by the trap file and the adversarial test. They have **not yet been validated by a native-speaker linguist**, and the proposal makes no accuracy claim for them.

## A.5 Safety: the protected-token guard

**What the guard enforces.** Every mark from every source passes one guard: rules, the consistency check and mock AI suggestions alike.
- If a mark touches a number, amount, date, reference number or section number, or falls inside a protected zone, it becomes a query.
- Protected zones are quotations, corrigenda, citations of Acts or Rules, and names of institutions.
- If a replacement would change the value of a number, the mark is blocked.

| Test | Cases | Result |
|---|---|---|
| Amounts, numeric dates, file numbers, section numbers next to real spacing errors | 64 | 0 edits |
| Corrigenda and quotations that deliberately contain a misspelling | 32 | 0 edits |
| Act and institution citations ("Gauhati Municipal Corporation Act, 1969") | 16 | 0 edits |
| Bengali paragraphs (declared and undeclared) | 16 | 0 converted to Assamese |
| Doubled Indic words (লাহে লাহে, धीरे धीरे) | 16 | 0 deleted (query only) |
| Assamese text with Latin digits | 16 | 0 digits rewritten (query only) |
| Mock AI rewrites of amounts, dates and official names | 48 | 0 applied |
| **Total** | **208** | **0 protected-token edits** |

**Comparison with our earlier prototype.** Its rules changed protected text in 112 of the 160 non-AI cases. For example, they rewrote "01-04-2027" as "1st April, 2027", assuming day-month order. Our own review found this. Fixing it is why the guard exists, and why DIGITS and DATE now only ask.

## A.6 Layout preservation

| Route | Evidence |
|---|---|
| **PDF** (the Press's own proof) | `shuddhi_pdf.py check` adds highlights, notes and "not checked" boxes as annotations only. For all 107 pages, the SHA-256 of each page's content stream is identical before and after annotation, as recorded in the coverage reports. |
| **Word** | `shuddhi_docx.py` wrote 13 fixes as native tracked changes and 5 queries as Word comments into the sample notification. Microsoft Word opened the file without a repair prompt and listed 23 revision marks and the comments. The protected-token check on the accepted text passed. Runs set in a legacy font are skipped and logged. |

## A.7 Revise-proof check (`shuddhi_pdf.py diff`, SYNTHETIC pair)

**Setup.** A synthetic notice was rendered twice as PDF. Five corrections were accepted on round 1. The revise makes four of them, misses one, and introduces two changes nobody asked for.

| # | Result | High risk | Detail |
|---|---|---|---|
| 1 | Not asked for | **Yes** | expected "5,00,000" but the proof has "50,000" |
| 2 | Not asked for | | expected "shall" but the proof has "may" |
| 3 | Missed | | "Kamrup Metro" should read "Kamrup (Metro)" |
| 4–7 | Made | | the four other corrections |

**Result.** The reader checks 3 places instead of re-reading the page, and the changed amount is at the top of the list.

## A.8 Prototype

**Rebuilt to the final design.** The clickable prototype (`prototype/index.html`) now runs the same safety logic in the browser:
- **Guard:** the guard and protected zones work as in the engine. An unsafe AI rewrite of "₹ 50,000" to "₹ 5,000" in the sample is shown as blocked.
- **Language check:**
  - Assamese and Bengali are told apart per paragraph.
  - Where the language is uncertain, the Assamese-only rules do not run.
  - The Bengali sample paragraph is left untouched.
- **Consistency check:** it flags "(PLAIN)/(Plan)".
- **Bulk accept:** only per rule, and only for spacing, danda and encoding fixes. Every other fix is accepted one at a time.
- **Locked queries:** marks that touch numbers, dates and names are shown with a lock.
- **Revise-proof check tab:** the new tab added for this design.
- **Approval:** approval is fingerprinted with SHA-256, checked against Python's reference implementation.

## A.9 Limits stated plainly

- No native-speaker linguist has yet validated the Assamese, Hindi or Bengali rules or labels. The rules ask rather than change wherever they are unsure.
- The legacy-font (Geetanjali) mapping is not built yet. It is scheduled for P0 and build weeks 1–4, with a native reader.
- Scanned pages are not checked; OCR is a later phase.
- The benchmark measures rule-friendly error types on English. Real-word and grammar errors need the linguist-labelled set.
- The revise-proof check was tested on a synthetic pair. Real proof pairs from the Press are needed in the pilot.
- Speed was not formally measured. Checking a 52-page issue took about 6 seconds on a laptop.
