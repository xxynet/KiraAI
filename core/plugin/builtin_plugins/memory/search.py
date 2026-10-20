"""Language-neutral lexical indexing for the built-in memory store."""

from collections import Counter
import math
import unicodedata

# Cover the largest supported result page: offset 10000 plus 50 records.
MAX_CANDIDATES = 10050


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _tokens(text: str, *, query: bool = False):
    """Preserve whole-word and character-gram matching, including repeated occurrences."""
    words = []
    current = []
    for char in normalize(text):
        if unicodedata.category(char)[0] in {"L", "N", "M"}:
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    for word in words:
        if len(word) <= 128:
            yield "w:" + word
        for size in (2, 3):
            for i in range(len(word) - size + 1):
                yield f"g{size}:" + word[i:i + size]
        if not query or len(word) == 1:
            for char in word:
                yield "g1:" + char


def terms(text: str, *, query: bool = False) -> dict[str, float]:
    """Keep the existing weights and deduplicate query terms."""
    weights = {"w": 3.0, "g2": 1.0, "g3": 1.5, "g1": 0.25}
    return {term: weights[term.split(":", 1)[0]] for term in _tokens(text, query=query)}


def term_frequencies(text: str) -> dict[str, int]:
    return dict(Counter(_tokens(text)))


def bm25(frequency, length, average_length, documents, document_frequency):
    """Score one term with positive Robertson IDF, k1=1.2 and b=0.75."""
    idf = math.log1p((documents - document_frequency + 0.5) / (document_frequency + 0.5))
    norm = 1.2 * (0.25 + 0.75 * length / average_length)
    return idf * frequency * 2.2 / (frequency + norm)


def fuse(lexical, semantic):
    """Fuse incomparable lexical and cosine scores by reciprocal rank."""
    records, scores = {}, {}
    for channel in (lexical, semantic):
        for rank, row in enumerate(channel):
            records.setdefault(row["id"], row)
            scores[row["id"]] = scores.get(row["id"], 0.0) + 1.0 / (60 + rank + 1)
    return sorted(records.values(), key=lambda row: (
        scores[row["id"]], row["importance"], row["updated_at"], row["id"],
    ), reverse=True)
