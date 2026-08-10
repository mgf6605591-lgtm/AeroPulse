# services/auth_service.py
"""Вход в систему и учётные записи (SEC-1, SEC-2).

Раньше здесь было сравнение строк: `user.password_hash == pwd`, где в поле с таким
именем лежал сам пароль. Теперь пароль проверяется через `utils.passwords`, а сам
модуль отвечает и за создание учёток — засев `admin/123` при каждом запуске убран
(SEC-2), первого администратора заводит пользователь.

Наружу отдаётся `Account`, а не объект ORM: за пределами сессии тот отсоединён, и
обращение к его полям падает (BUG-14). Проверки роли (SEC-3) опираются на
`Account.position`, поэтому поле входит в снимок.
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.database import get_session
from db.models.entities import User
from db.models.enums import UserPosition
from utils.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    validate_password,
    verify_password,
)

EMAIL_MAX_LENGTH = 25
USERNAME_MAX_LENGTH = 50

WRONG_CREDENTIALS = "Неверный логин или пароль!\nПроверьте введенные данные."


@dataclass(frozen=True)
class Account:
    """Снимок учётной записи, безопасный для передачи между окнами."""

    id: int
    username: str
    email: str
    position: UserPosition
    must_change_password: bool

    @property
    def is_admin(self) -> bool:
        return self.position is UserPosition.admin


def _snapshot(user: User) -> Account:
    return Account(
        id=user.id,
        username=user.username,
        email=user.email,
        position=user.position,
        must_change_password=bool(user.must_change_password),
    )


def ok(message: str = "", **extra) -> dict:
    return {"success": True, "message": message, **extra}


def fail(message: str) -> dict:
    return {"success": False, "message": message, "account": None}


class AuthService:

    def has_users(self) -> bool:
        """Пустая таблица пользователей — признак первого запуска (SEC-2)."""
        with get_session() as session:
            return session.execute(select(User.id).limit(1)).first() is not None

    def sign_in(self, username: str, password: str) -> dict:
        """Проверяет пару логин/пароль. При успехе в ответе — `account`."""
        if not username:
            return fail("Введите логин!")
        if not password:
            return fail("Введите пароль!")

        with get_session() as session:
            user = session.execute(
                select(User).where(User.username == username)
            ).scalar_one_or_none()
            if user is None or not verify_password(password, user.password_hash):
                return fail(WRONG_CREDENTIALS)
            return ok(account=_snapshot(user))

    def create_account(self, username: str, email: str, password: str,
                       position: UserPosition = UserPosition.admin,
                       must_change_password: bool = False) -> dict:
        """Заводит учётную запись. Пароль попадает в базу уже хешированным."""
        username = (username or "").strip()
        email = (email or "").strip()

        error = self._validate_account(username, email, password)
        if error:
            return fail(error)

        try:
            with get_session() as session:
                session.add(
                    User(
                        username=username,
                        email=email,
                        position=position,
                        password_hash=hash_password(password),
                        must_change_password=must_change_password,
                    )
                )
                session.commit()
        except IntegrityError as exc:
            return fail(self._humanize(exc))

        with get_session() as session:
            user = session.execute(
                select(User).where(User.username == username)
            ).scalar_one()
            return ok("Учётная запись создана.", account=_snapshot(user))

    def change_password(self, user_id: int, new_password: str,
                        current_password: str | None = None) -> dict:
        """Меняет пароль. `current_password` проверяется, если передан."""
        try:
            validate_password(new_password)
        except PasswordPolicyError as exc:
            return fail(str(exc))

        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                return fail("Учётная запись не найдена.")
            if current_password is not None and not verify_password(
                current_password, user.password_hash
            ):
                return fail("Текущий пароль указан неверно.")
            # Смена на тот же пароль оставила бы учётку с прежним значением, но уже
            # без признака обязательной смены — то есть отменяла бы саму смену.
            if verify_password(new_password, user.password_hash):
                return fail("Новый пароль совпадает с прежним.")

            user.password_hash = hash_password(new_password)
            user.must_change_password = False
            session.commit()
            return ok("Пароль изменён.", account=_snapshot(user))

    def _validate_account(self, username: str, email: str, password: str) -> str:
        if not username:
            return "Введите логин."
        if len(username) > USERNAME_MAX_LENGTH:
            return f"Логин длиннее {USERNAME_MAX_LENGTH} символов."
        if not email:
            return "Введите адрес электронной почты."
        if len(email) > EMAIL_MAX_LENGTH:
            # Ограничение колонки: без проверки здесь SQLite молча обрежет значение.
            return f"Адрес электронной почты длиннее {EMAIL_MAX_LENGTH} символов."
        if "@" not in email:
            return "Адрес электронной почты указан неверно."
        try:
            validate_password(password)
        except PasswordPolicyError as exc:
            return str(exc)
        return ""

    @staticmethod
    def _humanize(exc: IntegrityError) -> str:
        """Нарушение уникальности — по-человечески, а не текстом SQLAlchemy (BUG-31)."""
        text = str(getattr(exc, "orig", exc)).lower()
        if "users.username" in text:
            return "Такой логин уже занят."
        if "users.email" in text:
            return "Такой адрес электронной почты уже используется."
        return "Не удалось создать учётную запись: значения не уникальны."


auth_service = AuthService()

__all__ = ["Account", "AuthService", "auth_service", "MIN_PASSWORD_LENGTH"]
