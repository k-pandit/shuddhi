"""Build a SYNTHETIC pair of proofs (round 1 and its revise) to test the revise-proof check.
Round 1 contains 5 errors that the reviewer marks for correction (accepted.json).
The compositor's revise makes 4 of them, misses 1, and introduces 2 changes nobody asked for
(one of them an amount). The text is invented and labelled SYNTHETIC."""
import json, os, sys
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "pair")
os.makedirs(OUT, exist_ok=True)
A = [
    "SYNTHETIC TEST NOTICE - NOT A REAL NOTIFICATION",
    "GOVERNMENT OF ASSAM",
    "DEPARTMENT OF TRIBAL AFFAIRS (PLAN)",
    "No. TAD.12/2026/45 Dated Dispur, the 3rd November, 2026",
    "The Governor of Assam is pleased to constitute a District Level Monitoring Commitee",
    "for the scheme in the district of Kamrup Metro with immediate effect.",
    "The the Committee shall meet once in every quarter and shall recieve no remuneration.",
    "A sum of Rs. 5,00,000 is sanctioned for the year 2026-27 for the purpose.",
    "Sd/- Secretary to the Government of Assam, Department of Tribal Affairs (Plain), Dispur.",
]
accepted = [
    {"from": "Monitoring Commitee", "to": "Monitoring Committee"},
    {"from": "Kamrup Metro", "to": "Kamrup (Metro)"},
    {"from": "The the Committee", "to": "The Committee"},
    {"from": "shall recieve", "to": "shall receive"},
    {"from": "Tribal Affairs (Plain)", "to": "Tribal Affairs (Plan)"},
]
B = list(A)
B[4] = B[4].replace("Monitoring Commitee", "Monitoring Committee")
# Kamrup Metro: MISSED (not corrected)
B[6] = B[6].replace("The the Committee", "The Committee").replace("shall recieve", "shall receive")
B[6] = B[6].replace("shall meet once", "may meet once")           # UNASKED change of wording
B[7] = B[7].replace("Rs. 5,00,000", "Rs. 50,000")                  # UNASKED change of an amount
B[8] = B[8].replace("Tribal Affairs (Plain)", "Tribal Affairs (Plan)")


def render(lines, path):
    c = canvas.Canvas(path, pagesize=A4)
    y = 800
    for ln in lines:
        c.setFont("Helvetica-Bold" if ln.isupper() else "Helvetica", 10)
        c.drawString(50, y, ln)
        y -= 18
    c.save()


render(A, os.path.join(OUT, "proof_round1.pdf"))
render(B, os.path.join(OUT, "proof_round2.pdf"))
json.dump(accepted, open(os.path.join(OUT, "accepted.json"), "w"), indent=1)
print("written", OUT)
