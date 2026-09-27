"""String canonicalization shared by every matching rule. Pure: stdlib only.

It lives apart from ``google_books`` so the identity rules can be imported
without the app's settings: the offline catalog pipeline imports them with no
database or secrets configured.
"""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str | None) -> str:
    """Canonicalize a string for duplicate matching.

    NFKD-strip accents, lowercase, drop punctuation, collapse whitespace.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = no_accents.lower()
    no_punct = re.sub(r"[^\w\s]", " ", lowered)
    return re.sub(r"\s+", " ", no_punct).strip()
