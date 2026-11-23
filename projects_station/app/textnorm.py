import re

_DIACRITICS = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})


def normalize(text: str) -> str:
    if not text:
        return ""
    t = _DIACRITICS.sub("", text).translate(_MAP).lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t
