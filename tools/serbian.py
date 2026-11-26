"""Serbian Cyrillic to Latin transliteration and the search normalisation the MyNav app uses."""
import unicodedata

# Serbian Cyrillic → Serbian Latin (gajica), lower case; upper case is derived.
_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž", "з": "z", "и": "i",
    "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "ћ": "ć", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
}


def has_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text or "")


def to_latin(text: str) -> str:
    """"Булевар ослобођења" → "Bulevar oslobođenja"; Latin text is returned unchanged."""
    if not has_cyrillic(text):
        return text
    out = []
    for index, ch in enumerate(text):
        lower = ch.lower()
        latin = _CYRILLIC_TO_LATIN.get(lower)
        if latin is None:
            out.append(ch)
        elif ch == lower:
            out.append(latin)
        else:
            # "Љубљана" → "Ljubljana", but "ЉУБЉАНА" → "LJUBLJANA".
            following = text[index + 1] if index + 1 < len(text) else ""
            whole_word_upper = following.isupper()
            out.append(latin.upper() if whole_word_upper else latin.capitalize())
    return "".join(out)


def normalize(text: str) -> str:
    """Search key: Latin, lower case, without diacritics (đ → dj), punctuation as spaces.

    The app normalises queries the same way, so "bulevar oslobodjenja" finds "Булевар ослобођења".
    """
    if not text:
        return ""
    latin = to_latin(text).lower().replace("đ", "dj")
    decomposed = unicodedata.normalize("NFKD", latin)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join("".join(ch if ch.isalnum() else " " for ch in stripped).split())


def display_name(tags) -> str | None:
    """Name shown in the app: the mapped Latin name when there is one, otherwise the name transliterated."""
    latin = tags.get("name:sr-Latn")
    if latin:
        return latin
    name = tags.get("name")
    return to_latin(name) if name else None
