"""Quote normalisation for the eval collection.

Mirrors ``normalize_quote`` in db/init.sql. The server checks a link quote with that
SQL function; the eval collection checks the same way so a quote the eval accepts is a
quote the server would accept. If the SQL changes, update this port and its tests.
"""
from __future__ import annotations

import re

# PostgreSQL translate() drops a source character that has no partner in the
# destination. U+00AD (soft hyphen) is that last character in the SQL.
_TRANSLATE = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2013": "-", "\u2014": "-", "\u2010": "-", "\u2011": "-", "\u2212": "-",
    "\u00a0": " ",
    "\u00ad": None,
})


def normalize_quote(text: str) -> str:
    """Case, whitespace, curly quotes, dashes, soft hyphens, and fi/fl ligatures folded."""
    folded = text.translate(_TRANSLATE).replace("\ufb01", "fi").replace("\ufb02", "fl").lower()
    folded = re.sub(r"\s+", " ", folded)
    folded = re.sub(r"\s*-\s*", "-", folded)
    return folded.strip()


def quote_in_evidence(quote: str, evidence: str) -> bool:
    """True when the normalised quote is a non-empty substring of the normalised evidence."""
    needle = normalize_quote(quote)
    return needle != "" and needle in normalize_quote(evidence)
