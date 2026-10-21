"""Language-neutral N-gram preprocessing for SQLite FTS5 retrieval."""

import unicodedata

# Cover the largest supported result page: offset 10000 plus 50 records.
MAX_CANDIDATES = 10050
FTS_COLUMNS = ("w", "g1", "g2", "g3")


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


def index_columns(text: str) -> tuple[str, ...]:
    """Encode complete tokens so FTS cannot split grams or alter Unicode distinctions."""
    columns = {name: [] for name in FTS_COLUMNS}
    for term in _tokens(text):
        name, value = term.split(":", 1)
        columns[name].append(value.encode("utf-8").hex())
    return tuple(" ".join(columns[name]) for name in FTS_COLUMNS)


def match_query(text: str) -> str:
    """Build an OR query from every distinct gram, without accepting FTS operators."""
    return " OR ".join(
        f'{name}:"{value.encode("utf-8").hex()}"'
        for name, value in (
            term.split(":", 1) for term in dict.fromkeys(_tokens(text, query=True))
        )
    )


def indexed_term_count(text: str) -> int:
    """Count distinct terms for the administrative detail view."""
    return len(set(_tokens(text)))


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
