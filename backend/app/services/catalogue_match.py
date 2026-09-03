"""
Matching a line of prescription text against the 246k-product brand catalogue.

Fuzzy-matching one line against a quarter of a million names has two problems
that a plain `process.extractOne` does not solve:

  * Speed. Scoring every product for every line took ~2.7 seconds per line.
  * Precision. token_set_ratio scores 100 whenever the line's tokens are a
    subset of the candidate's, so the bare word "Rx" at the top of a
    prescription matched "Rx Cort 6mg Tablet" perfectly and invented a
    steroid the patient was never prescribed. Worse, "Zerodol SP" matched
    plain "Zerodol Tablet", quietly dropping two of the three ingredients.

Both are fixed by narrowing before scoring. Products are bucketed by the first
four letters of each word in their name, so a line is only ever compared
against products that share a real word-stem with it. That turns thousands of
comparisons into dozens, and it means a two-letter token like "Rx" reaches no
bucket at all.

Ranking then prefers the candidate that accounts for the most of the line:
"Zerodol SP Tablet" beats "Zerodol Tablet" because it explains the "SP", and
that is the difference between a two-drug combination and a one-drug tablet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

# Below this a token is too generic to identify a brand ("of", "mg", "Rx").
MIN_TOKEN_LEN = 4
STEM_LEN = 4

# Words that appear in thousands of product names and in every prescription;
# bucketing on them would defeat the whole point of narrowing.
STOP_TOKENS = {
    "tablet", "tablets", "capsule", "capsules", "syrup", "injection", "suspension",
    "cream", "drops", "solution", "ointment", "sachet", "powder", "spray", "gel",
    "daily", "twice", "thrice", "once", "before", "after", "food", "days", "day",
    "morning", "night", "evening", "with", "water", "milk", "dose", "take", "oral",
    "mg", "ml", "gm", "mcg", "tab", "cap",
    # Prescription-form boilerplate. Some of these are also real Indian brand
    # prefixes -- there is a product called "Signature Cefyxim CV Tablet" --
    # so the signature line at the foot of a form was matching a cephalosporin
    # and inventing a medicine nobody was prescribed.
    "signature", "signed", "patient", "name", "date", "clinic", "hospital",
    "doctor", "diagnosis", "advice", "review", "consultation", "address",
    "phone", "mobile", "regd", "reg", "mbbs", "md", "ms", "sex", "age",
    "weight", "height", "follow", "next", "visit", "sign", "seal", "stamp",
    "prescription", "case", "opd", "ward", "bed", "the", "and", "for", "from",
}

# Decimals stay whole: splitting "2.5" into "2" and "5" made a line reading
# "Ramistar-AM 5" match "Ramistar-AM 2.5", i.e. half the prescribed dose.
TOKEN_RE = re.compile(r"[a-z]+|[0-9]+(?:\.[0-9]+)?")


def tokens(text: str) -> list[str]:
    """
    Letter- and digit-runs. Hyphens and dots split words, so 'Zerodol-SP' and
    'Zerodol SP' produce the same tokens and match each other.

    Short tokens are kept here on purpose: Indian brand suffixes carry the
    whole difference in composition. "Zerodol" is aceclofenac, "Zerodol SP"
    adds paracetamol, "Zerodol MR" adds tizanidine instead. Dropping a
    two-letter token silently turns one medicine into another.
    """
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP_TOKENS]


def normalise(text: str) -> str:
    """
    Space-separated tokens. Fuzzy scorers treat "Zerodol-SP" as one word, so a
    line reading "Zerodol SP" scored 52 against it while plain "Zerodol
    Tablet" scored 100 -- picking the wrong medicine on punctuation alone.
    Scoring normalised forms removes that.
    """
    return " ".join(TOKEN_RE.findall((text or "").lower()))


def stems(text: str) -> set[str]:
    """Bucketing keys. Unlike coverage tokens these need to be long enough to
    be distinctive, or every prescription would land in the "sp" bucket."""
    return {
        t[:STEM_LEN]
        for t in TOKEN_RE.findall((text or "").lower())
        if len(t) >= MIN_TOKEN_LEN and t not in STOP_TOKENS and not t.isdigit()
    }


@dataclass
class CatalogueMatch:
    index: int
    name: str
    score: float


class CatalogueIndex:
    """
    Inverted index from word-stem to product row numbers. Built once per
    process (~246k rows, a few seconds); prescriptions arrive far more often
    than the catalogue changes.
    """

    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.norm_names = [normalise(n) for n in names]
        self.name_tokens = [set(tokens(n)) for n in names]
        self.by_stem: dict[str, list[int]] = {}
        for i, name in enumerate(names):
            for stem in stems(name):
                self.by_stem.setdefault(stem, []).append(i)

    def candidates(self, line: str, cap: int = 400) -> list[int]:
        """
        Row numbers worth scoring for this line. Rare stems are searched first
        so a line mentioning both a distinctive brand and a common word does
        not blow the cap on the common word's bucket.
        """
        buckets = [
            self.by_stem[s] for s in stems(line) if s in self.by_stem
        ]
        buckets.sort(key=len)
        seen: list[int] = []
        seen_set: set[int] = set()
        for bucket in buckets:
            if len(bucket) > cap and seen:
                # A huge bucket adds noise once we already have candidates from
                # a more distinctive stem.
                continue
            for i in bucket:
                if i not in seen_set:
                    seen_set.add(i)
                    seen.append(i)
            if len(seen) >= cap * 4:
                break
        return seen

    def best(self, line: str, cutoff: float = 82.0) -> CatalogueMatch | None:
        line_tokens = set(tokens(line))
        if not line_tokens:
            return None
        norm_line = normalise(line)

        best: CatalogueMatch | None = None
        best_rank: tuple[float, int, int, int] = (0.0, 0, 0, 0)

        for i in self.candidates(line):
            score = fuzz.token_set_ratio(self.norm_names[i], norm_line)
            if score < cutoff:
                continue

            name_tokens = self.name_tokens[i]
            # How much of the product's own name the line actually accounts
            # for. This is what stops "Zerodol Tablet" (fully contained in the
            # line, so a perfect token_set_ratio) from beating "Zerodol-SP
            # Tablet", which explains one more word of it.
            covered = len(name_tokens & line_tokens)
            # Words in the product name that the line does NOT contain. This is
            # the guard against picking a neighbouring strength: "Ramistar-AM
            # 2.5" and "Ramistar-AM 5" cover the line equally well, but only
            # the first leaves a number unaccounted for.
            uncovered = len(name_tokens - line_tokens)
            rank = (score, covered, -uncovered, -len(name_tokens))
            if rank > best_rank:
                best_rank = rank
                best = CatalogueMatch(index=i, name=self.names[i], score=score)

        return best
