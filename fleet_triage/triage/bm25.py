"""A small BM25 (Okapi) index with a farm-support-friendly tokenizer."""

from __future__ import annotations

import math
import re
from collections import Counter

STOP = set(
    """a an the and or but if of to in on at by for with from up down out over under is are was were be
    been being am it its it's this that these those i me my we our us you your he she him her they them
    their what which who whom do does did doing have has had having just so than too very can will would
    should could there here when where why how all any both each few more most other some such no nor
    not only own same again then once about into through during before after above below off further s t
    don now get got go going one ones""".split()
)
SUFFIXES = ("ing", "ed", "es", "s", "ly")
SYNONYMS = {
    "flat": "battery",
    "charge": "battery",
    "charging": "battery",
    "quiet": "silent",
    "offline": "silent",
    "dropped": "silent",
    "stopped": "silent",
    "dead": "silent",
    "location": "gps",
    "position": "gps",
    "map": "gps",
    "update": "firmware",
    "updated": "firmware",
    "software": "firmware",
    "bill": "invoice",
    "charged": "invoice",
    "login": "log",
    "password": "log",
    "notification": "alert",
    "text": "alert",
    "texts": "alert",
    "message": "alert",
}


def stem(w: str) -> str:
    for suf in SUFFIXES:
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", text.lower())
    out = []
    for w in words:
        if w in STOP or len(w) < 2:
            continue
        out.append(stem(w))
        if w in SYNONYMS:
            out.append(SYNONYMS[w])
    return out


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.6):
        self.k1, self.b = k1, b
        self.docs = [tokenize(d) for d in docs]
        self.tf = [Counter(d) for d in self.docs]
        self.avgdl = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, doc in zip(self.tf, self.docs, strict=True):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * len(doc) / self.avgdl)
            for t in q:
                if t in tf:
                    s += self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm)
            out.append(s)
        return out
