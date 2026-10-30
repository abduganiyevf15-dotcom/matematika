import re
from fractions import Fraction


def parse_key_string(s: str):
    """'abcd' yoki '1a2b3c' -> [{'type':'choice','value':'a'}, ...]
    Raqam-harf juftliklari ('1a2b3c') ham, ketma-ket harflar ('abcd') ham qabul qilinadi."""
    s = s.strip().lower().replace(" ", "")
    if not s:
        return []
    if re.fullmatch(r"(\d+[a-e])+", s):
        pairs = re.findall(r"(\d+)([a-e])", s)
        pairs.sort(key=lambda p: int(p[0]))
        return [{"type": "choice", "value": p[1]} for p in pairs]
    if re.fullmatch(r"[a-e]+", s):
        return [{"type": "choice", "value": ch} for ch in s]
    return []


def _to_number(text: str):
    """'1/2', '0.5', '0,5', '-3' -> Fraction; aks holda None."""
    t = text.strip().replace(",", ".").replace(" ", "")
    if not t:
        return None
    try:
        if "/" in t:
            a, b = t.split("/", 1)
            return Fraction(Fraction(a), Fraction(b))
        return Fraction(t)
    except (ValueError, ZeroDivisionError):
        return None


def open_equal(given: str, expected: str) -> bool:
    g, e = given.strip().lower(), expected.strip().lower()
    if g == e:
        return True
    gn, en = _to_number(g), _to_number(e)
    return gn is not None and en is not None and gn == en


def check_one(key: dict, given: str) -> bool:
    if given is None or str(given).strip() == "":
        return False
    given = str(given).strip()
    if key["type"] == "choice":
        return given.lower() == key["value"].lower()
    return any(open_equal(given, v) for v in key.get("values", []))


def grade(keys: list, given: list):
    """given: har bir savol uchun javob (str yoki None). Qaytaradi: (to'g'ri soni, tafsilot)."""
    details, correct = [], 0
    for i, key in enumerate(keys):
        g = given[i] if i < len(given) else None
        ok = check_one(key, g)
        correct += ok
        shown = key["value"].upper() if key["type"] == "choice" else " | ".join(key.get("values", []))
        details.append({"n": i + 1, "given": g, "expected": shown, "ok": ok})
    return correct, details
