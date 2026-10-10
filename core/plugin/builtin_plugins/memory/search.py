"""Language-neutral lexical indexing for the built-in memory store."""

import unicodedata


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def terms(text: str, *, query: bool = False) -> dict[str, float]:
    """Combine whole words and character grams without language packages."""
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
    result = {}
    for word in words:
        if len(word) <= 128:
            result["w:" + word] = 3.0
        for size, weight in ((2, 1.0), (3, 1.5)):
            for i in range(len(word) - size + 1):
                result[f"g{size}:" + word[i:i + size]] = weight
        if not query or len(word) == 1:
            for char in word:
                result["g1:" + char] = 0.25
    return result
