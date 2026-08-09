# utils/airport_codes.py
"""Код аэропорта для записи, заводимой импортом.

Сводный бланк 15-ГА называет свои аэропорты словами и никаких кодов не содержит,
а `airports.code` — обязательное и уникальное поле длиной пять символов. Взять
настоящий код (ИКАО, ИАТА) неоткуда, поэтому он собирается из названия: так в
справочнике видно, к какому аэропорту относится строка, а не «AP0007».

Код здесь служебный. Настоящий проставляется в «Справочниках» — это правка
одного поля, а не перезаведение записи с отчётностью.
"""
from typing import Container

# Длина колонки `airports.code`.
CODE_LENGTH = 5

# Замена по буквам; многобуквенные сочетания заданы явно, потому что «щ» и «ю»
# в один символ не переводятся.
CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# Название, из которого не осталось ни одной буквы: код всё равно обязателен.
FALLBACK = "AP"


def transliterate(name: str) -> str:
    """Латинские буквы и цифры названия заглавными; всё прочее отбрасывается."""
    out = []
    for char in str(name or "").lower():
        replacement = CYRILLIC_TO_LATIN.get(char, char)
        out.extend(c for c in replacement.upper() if c.isascii() and c.isalnum())
    return "".join(out)


def unique_airport_code(name: str, taken: Container[str]) -> str:
    """Код длиной не больше пяти символов, которого ещё нет в `taken`.

    Совпадения разводятся числом в хвосте, а не наращиванием длины: пять
    символов — предел колонки, и удлинить код нельзя. «Алдан» и «Алданский» дали
    бы один и тот же ALDAN, второй станет ALDA2.
    """
    base = transliterate(name)[:CODE_LENGTH] or FALLBACK
    if base not in taken:
        return base

    number = 2
    while True:
        suffix = str(number)
        head = base[: CODE_LENGTH - len(suffix)] or FALLBACK[: CODE_LENGTH - len(suffix)]
        candidate = f"{head}{suffix}"
        if len(candidate) > CODE_LENGTH:
            # Хвост перерос колонку: дальше нумеровать нечем.
            raise ValueError(
                f"Не удалось подобрать свободный код аэропорта для «{name}»: "
                f"варианты вида {base} заняты."
            )
        if candidate not in taken:
            return candidate
        number += 1
