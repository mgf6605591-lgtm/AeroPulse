# utils/entity_codes.py
"""Код предприятия для записи, заводимой импортом.

Сводный бланк 15-ГА называет свои аэропорты словами и никаких кодов не содержит,
а `airports.code` — обязательное и уникальное поле длиной пять символов. Взять
настоящий код (ИКАО, ИАТА) неоткуда, поэтому он собирается из названия: так в
справочнике видно, к какому аэропорту относится строка, а не «AP0007».

У авиакомпаний то же поле и то же затруднение, но отчёт 12-ГА свой код всё-таки
называет — `okpo` в титуле, четыре цифры. Он и берётся, когда есть: это код из
той же выгрузки, а не выдумка импорта.

Код здесь служебный. Настоящий проставляется в «Справочниках» — это правка
одного поля, а не перезаведение записи с отчётностью.
"""
from collections.abc import Container

# Длина колонки `code` в справочниках предприятий.
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
    out: list[str] = []
    for char in str(name or "").lower():
        replacement = CYRILLIC_TO_LATIN.get(char, char)
        out.extend(c for c in replacement.upper() if c.isascii() and c.isalnum())
    return "".join(out)


def unique_entity_code(name: str, taken: Container[str], preferred: str | None = None) -> str:
    """Код длиной не больше пяти символов, которого ещё нет в `taken`.

    `preferred` — код, названный самим отчётом. Он берётся первым, но только если
    свободен и целиком помещается в колонку: занятый код означает, что так уже
    названо другое предприятие, а обрезанный — это не код из отчёта, а другое
    число, и выдавать его за настоящий нельзя.

    Совпадения разводятся числом в хвосте, а не наращиванием длины: пять
    символов — предел колонки, и удлинить код нельзя. «Алдан» и «Алданский» дали
    бы один и тот же ALDAN, второй станет ALDA2.
    """
    from_file = transliterate(preferred) if preferred else ""
    if from_file and len(from_file) <= CODE_LENGTH and from_file not in taken:
        return from_file

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
                f"Не удалось подобрать свободный код предприятия для «{name}»: "
                f"варианты вида {base} заняты."
            )
        if candidate not in taken:
            return candidate
        number += 1
