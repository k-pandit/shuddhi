# Shuddhi benchmark report

- Random seed: 42; corpus SHA-256: `c94b9bf84ed4426f…`
- Corpus: 373 lines of public Assam Gazette English text in 46 documents (4257 words); pages with personal data, scanned pages and legacy-font text excluded (see manifest.json)

## Part 1: seeded errors

Dictionary only = a plain Hunspell spell-checker (en_GB + en_US dictionaries), as most office tools provide.

| Error type | Seeded | Shuddhi found | Shuddhi recall (95% CI) | Dictionary-only found | Dictionary-only recall |
|---|---|---|---|---|---|
| swap | 53 | 53 | 100% (93%–100%) | 53 | 100% |
| drop | 72 | 70 | 97% (90%–99%) | 72 | 100% |
| double-letter | 67 | 66 | 98% (92%–100%) | 67 | 100% |
| known-misspelling | 25 | 25 | 100% (87%–100%) | 25 | 100% |
| doubled-word | 89 | 89 | 100% (96%–100%) | 0 | 0% |
| space-before-punct | 38 | 38 | 100% (91%–100%) | 0 | 0% |
| double-space | 86 | 86 | 100% (96%–100%) | 0 | 0% |
| name-variant | 33 | 19 | 58% (41%–73%) | 33 | 100% |
| **All** | **463** | **446** | **96% (94%–98%)** | **250** | **54%** |

| Measure | Shuddhi | Dictionary only |
|---|---|---|
| Precision of marks in seeded paragraphs | 100% | 74% |
| Marks per 1,000 words of unseeded Gazette text | 2.1 | 46.3 |
| First suggestion restores the original word (spelling seeds) | 177/213 | 172/217 |

Marks on unseeded text include genuine errors in the published Gazette as well as false alarms.

## Part 2: adversarial protected-token test

- Cases: 208 (amount 16, date 16, reference 16, section 16, corrigendum 16, quotation 16, citation 16, bengali 16, indic-reduplication 16, indic-digits 16, ai-amount-rewrite 16, ai-date-rewrite 16, ai-name-rewrite 16)
- A worst-case reviewer accepts every fix Shuddhi offers.
- **Protected-token edits by Shuddhi: 0 of 208**; protected text altered: 0
- Mock AI rewrites of a protected value (48): 17 blocked, 10 turned into queries, 21 dropped because a rule query already covered the span; **applied: 0**
- Earlier prototype rules on the same 160 non-AI cases: **112 changed protected text**

Examples of what the earlier rules did:

- *date*: `with effect from 01-04-2027 till further orders ,the Committee shall meet.` → `with effect from 1st April, 2027 till further orders,the Committee shall meet.`
- *date*: `with effect from 31.03.2028 till further orders ,the Committee shall meet.` → `with effect from 31st March, 2028 till further orders,the Committee shall meet.`
- *reference*: `Order issued vide No.AAP. 37/2023/393  dated 4-11-2026 is hereby cancelled .` → `Order issued vide No.AAP. 37/2023/393 dated 4th November, 2026 is hereby cancelled.`
- *date*: `with effect from 13/10/2023 till further orders ,the Committee shall meet.` → `with effect from 13th October, 2023 till further orders,the Committee shall meet.`
- *reference*: `Order issued vide No. E- Comp. No.: 800346/2026/12  dated 29/02/2024 is hereby cancelled .` → `Order issued vide No. E- Comp. No.: 800346/2026/12 dated 29th February, 2024 is hereby cancelled.`
- *reference*: `Order issued vide ECF No. 123456  dated 15.08.1947 is hereby cancelled .` → `Order issued vide ECF No. 123456 dated 15th August, 1947 is hereby cancelled.`
