"""Хеширование паролей (SEC-1).

До этого модуля поле `users.password_hash` хранило сам пароль, а проверка входа
была сравнением строк. Взято `hashlib.scrypt` из стандартной библиотеки: сборка
приложения идёт в один exe через PyInstaller, и нативная зависимость (argon2-cffi,
bcrypt) потребовала бы отдельной возни со спекой ради того же результата.

Формат хранения — одна строка, все параметры внутри неё:

    scrypt$n$r$p$<соль base64>$<хеш base64>

Параметры записаны рядом с хешем, а не зашиты в код проверки: если завтра их
поднять, старые записи продолжат проверяться своими значениями, а не новыми.
"""

import base64
import hashlib
import hmac
import os

ALGORITHM = "scrypt"

# Параметры по умолчанию: ~16 МБ памяти на проверку. Верхний предел задаёт сам
# hashlib — при n*r*p выше maxmem вызов падает, поэтому maxmem считается от n и r.
DEFAULT_N = 2 ** 14
DEFAULT_R = 8
DEFAULT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32

# Минимальная длина: единственное ограничение, которое проверяется. Требования
# «цифра, заглавная, спецсимвол» на практике дают предсказуемые пароли вида
# «Parol123!», поэтому не вводятся.
MIN_PASSWORD_LENGTH = 8


class PasswordPolicyError(ValueError):
    """Пароль не удовлетворяет требованиям; текст сообщения показывается пользователю."""


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=KEY_BYTES,
        # Запас втрое: hashlib считает лимит по своей формуле, и ровно 128*n*r
        # ему уже мало.
        maxmem=128 * n * r * 3,
    )


def hash_password(password: str, *, n: int = DEFAULT_N, r: int = DEFAULT_R,
                  p: int = DEFAULT_P) -> str:
    """Возвращает строку для записи в `users.password_hash`. Соль у каждой своя.

    Требования к паролю здесь не проверяются: их применяет служба учётных записей
    через `validate_password`. Миграция переводит в хеши уже существующие пароли —
    в том числе `123`, который нынешним требованиям не удовлетворяет.
    """
    salt = os.urandom(SALT_BYTES)
    digest = _derive(password, salt, n, r, p)
    return f"{ALGORITHM}${n}${r}${p}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Проверяет пароль против сохранённого значения.

    Значение в старом формате (сам пароль открытым текстом) проверку не проходит
    никогда: миграция переводит такие записи в хеши, и отдельная ветка сравнения
    открытых паролей означала бы, что незамеченная непереведённая база продолжает
    работать как раньше — молча и без признаков.
    """
    if not password or not stored:
        return False

    parsed = _parse(stored)
    if parsed is None:
        return False

    n, r, p, salt, expected = parsed
    try:
        actual = _derive(password, salt, n, r, p)
    except (ValueError, MemoryError):
        # Параметры из строки не приняты этой сборкой Python — вход не разрешаем.
        return False
    return hmac.compare_digest(actual, expected)


def is_hashed(stored: str) -> bool:
    """Отличает хеш от пароля, сохранённого открытым текстом до SEC-1."""
    return _parse(stored) is not None


def validate_password(password: str) -> None:
    """Бросает `PasswordPolicyError` с готовым для показа текстом."""
    if password is None or password == "":
        raise PasswordPolicyError("Введите пароль.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Пароль короче {MIN_PASSWORD_LENGTH} символов."
        )


def _parse(stored: str):
    """Разбирает строку хранения; None — если это не наш формат."""
    if not isinstance(stored, str):
        return None
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != ALGORITHM:
        return None
    try:
        n, r, p = (int(value) for value in parts[1:4])
        salt = base64.b64decode(parts[4], validate=True)
        digest = base64.b64decode(parts[5], validate=True)
    except (ValueError, TypeError):
        return None
    if not salt or not digest:
        return None
    return n, r, p, salt, digest
