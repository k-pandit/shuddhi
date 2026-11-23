"""Language identification: declared per document, confirmed per paragraph, otherwise abstain.

Assamese and Bengali share one script. The commonest Assamese typing error is the Bengali
letter র (U+09B0) or ব (U+09AC) in place of Assamese ৰ (U+09F0) or ৱ (U+09F1). So the letters
the error removes cannot be the only evidence of Assamese. We also look for function words
that differ between the two languages (compared after mapping র→ৰ, so a mistyped Assamese
word still counts). If the evidence does not confirm the language, Shuddhi abstains: the
Assamese-only rules do not run, and Bengali text is never "corrected" into Assamese.
"""
import re

# Only words that do not also occur in standard Bengali (after mapping র to ৰ).
AS_WORDS = {"আৰু", "হৈছে", "তেওঁ", "তেওঁলোক", "বাবে", "লৈ", "কাৰণে", "অনুসৰি", "নহয়", "নহয়",
            "আছিল", "হ'ব", "হ’ব", "কৰিছে", "এখন", "সকলো", "জনোৱা", "জনোৱা", "ক্ষেত্ৰত",
            "সন্দৰ্ভত", "মাজত", "সৈতে", "যোৱা", "যোৱা", "কৰিবলৈ", "হোৱা", "হোৱা"}
BN_WORDS = {"এবং", "হবে", "থেকে", "জন্য", "সঙ্গে", "হয়েছে", "হয়েছে", "করেছে", "কৰেছে", "তাঁর",
            "তাদের", "দ্বারা", "দ্বাৰা", "কোনো", "এখানে", "যাবে", "পারে", "পাৰে", "দেওয়া", "দেওয়া", "হলো", "হল"}
# Words that exist in both languages are not evidence; remove any overlap after normalisation.


def _norm(w):
    return w.replace("র", "ৰ")


AS_NORM = {_norm(w) for w in AS_WORDS}
BN_NORM = {_norm(w) for w in BN_WORDS} - AS_NORM


def script_of(text):
    beng = len(re.findall(r"[ঀ-৿]", text))
    deva = len(re.findall(r"[ऀ-ॿ]", text))
    latn = len(re.findall(r"[A-Za-z]", text))
    if not (beng or deva or latn):
        return None
    return max((beng, "beng"), (deva, "deva"), (latn, "latn"))[1]


def confirm_language(text, declared=None):
    """Return (lang, confirmed) where lang is 'en', 'hi', 'as', 'bn' or 'uncertain'.

    declared: the document's declared language ('as', 'bn', 'en', 'hi' or None).
    """
    sc = script_of(text)
    if sc is None:
        return "uncertain", False
    if sc == "latn":
        return "en", True
    if sc == "deva":
        return "hi", True
    words = [_norm(w) for w in re.findall(r"[ঀ-৿'’]+", text)]
    as_hits = sum(1 for w in words if w in AS_NORM)
    bn_hits = sum(1 for w in words if w in BN_NORM)
    has_as_letters = bool(re.search(r"[ৰৱ]", text))
    if declared == "bn":
        return ("bn", True) if not has_as_letters else ("uncertain", False)
    if bn_hits and not (as_hits or has_as_letters):
        return "bn", True
    if (as_hits or has_as_letters) and not bn_hits:
        return "as", True
    return "uncertain", False
