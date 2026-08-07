"""Хранение паролей, учётные записи и первый запуск (SEC-1, SEC-2, BUG-28).

Главное, что здесь проверяется, — что в базу не попадает сам пароль и что уже
накопленные открытые пароли переводятся в хеши миграцией, а не остаются лежать
как есть. Отдельно сторожится отсутствие засева `admin/123`: прежний init_db()
создавал эту учётку заново при каждом запуске.
"""

import unittest
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import db.database
from db.database import init_db
from db.migrator import upgrade_to_head
from db.models.enums import UserPosition
from services.auth_service import auth_service
from tests.support import MigratedDbCase, TempDbCase, make_legacy_db, scalar
from utils.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    is_hashed,
    validate_password,
    verify_password,
)

# Параметры scrypt по умолчанию считают ~16 МБ на вызов; в тестах хеш берётся
# десятками раз, поэтому там, где проверяется не стойкость, а поведение, работа
# идёт на облегчённых параметрах.
FAST = {"n": 2 ** 8, "r": 8, "p": 1}


def insert_user(engine, username: str, stored: str, user_id: int = 1) -> None:
    """Пользователь в схеме baseline: колонки must_change_password там ещё нет."""
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, username, email, position, password_hash) "
                 "VALUES (:id, :username, :email, 'admin', :stored)"),
            {"id": user_id, "username": username,
             "email": f"{username}@localhost", "stored": stored},
        )


class PasswordHashingTest(unittest.TestCase):
    """utils/passwords.py — единственное место, где пароль превращается в хеш."""

    def test_password_is_not_stored_as_is(self):
        stored = hash_password("Пароль12345", **FAST)
        self.assertNotIn("Пароль12345", stored)
        self.assertTrue(stored.startswith("scrypt$"))

    def test_same_password_gives_different_hashes(self):
        """Соль у каждой записи своя: одинаковые пароли не видны по совпадению хешей."""
        first = hash_password("Пароль12345", **FAST)
        second = hash_password("Пароль12345", **FAST)
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("Пароль12345", first))
        self.assertTrue(verify_password("Пароль12345", second))

    def test_wrong_password_rejected(self):
        stored = hash_password("Пароль12345", **FAST)
        self.assertFalse(verify_password("Пароль1234", stored))
        self.assertFalse(verify_password("", stored))

    def test_plaintext_stored_value_never_passes(self):
        """Непереведённая база не должна продолжать работать по-старому и молча."""
        self.assertFalse(verify_password("123", "123"))
        self.assertFalse(is_hashed("123"))

    def test_spaces_in_password_are_significant(self):
        """BUG-28: пароль не обрезается по краям ни при записи, ни при проверке."""
        stored = hash_password("  пароль с пробелами  ", **FAST)
        self.assertTrue(verify_password("  пароль с пробелами  ", stored))
        self.assertFalse(verify_password("пароль с пробелами", stored))

    def test_damaged_stored_value_rejected(self):
        for broken in ("", "scrypt$", "scrypt$a$b$c$d$e", "scrypt$256$8$1$**$**",
                       "argon2$1$2$3$c2FsdA==$aGFzaA=="):
            self.assertFalse(verify_password("Пароль12345", broken), broken)
            self.assertFalse(is_hashed(broken), broken)

    def test_parameters_are_read_from_the_stored_value(self):
        """Смена параметров по умолчанию не должна ломать проверку старых записей."""
        stored = hash_password("Пароль12345", n=2 ** 9, r=8, p=1)
        self.assertIn("$512$8$1$", stored)
        self.assertTrue(verify_password("Пароль12345", stored))


class PasswordPolicyTest(unittest.TestCase):

    def test_short_password_rejected(self):
        with self.assertRaises(PasswordPolicyError):
            validate_password("a" * (MIN_PASSWORD_LENGTH - 1))

    def test_empty_password_rejected(self):
        with self.assertRaises(PasswordPolicyError):
            validate_password("")

    def test_long_enough_password_accepted(self):
        self.assertIsNone(validate_password("a" * MIN_PASSWORD_LENGTH))


class PasswordMigrationTest(TempDbCase):
    """Ревизия b7a4c9f21e05 переводит накопленные открытые пароли в хеши."""

    def test_plaintext_password_converted(self):
        make_legacy_db(self.engine)
        insert_user(self.engine, "admin", "123")

        upgrade_to_head(self.engine)

        stored = scalar(self.engine, "SELECT password_hash FROM users WHERE id = 1")
        self.assertNotEqual("123", stored)
        self.assertTrue(is_hashed(stored))

    def test_old_password_still_opens_the_account(self):
        """Перевод не должен запирать пользователя: вход по прежнему паролю работает."""
        make_legacy_db(self.engine)
        insert_user(self.engine, "admin", "123")

        upgrade_to_head(self.engine)

        stored = scalar(self.engine, "SELECT password_hash FROM users WHERE id = 1")
        self.assertTrue(verify_password("123", stored))

    def test_converted_account_must_change_password(self):
        make_legacy_db(self.engine)
        insert_user(self.engine, "admin", "123")

        upgrade_to_head(self.engine)

        self.assertEqual(
            1, scalar(self.engine, "SELECT must_change_password FROM users WHERE id = 1")
        )

    def test_already_hashed_password_left_alone(self):
        """Повторный прогон не перехеширует и не требует смены пароля без причины."""
        stored = hash_password("Пароль12345", **FAST)
        make_legacy_db(self.engine)
        insert_user(self.engine, "user", stored)

        upgrade_to_head(self.engine)

        self.assertEqual(
            stored, scalar(self.engine, "SELECT password_hash FROM users WHERE id = 1")
        )
        self.assertEqual(
            0, scalar(self.engine, "SELECT must_change_password FROM users WHERE id = 1")
        )

    def test_fresh_database_has_no_accounts(self):
        """SEC-2: учётной записи по умолчанию в новой базе нет."""
        upgrade_to_head(self.engine)
        self.assertEqual(0, scalar(self.engine, "SELECT count(*) FROM users"))

    def test_init_db_does_not_seed_admin(self):
        """Прежний init_db() создавал admin/123 при каждом запуске."""
        with patch.object(db.database, "engine", self.engine):
            init_db()
            init_db()
        self.assertEqual(0, scalar(self.engine, "SELECT count(*) FROM users"))


class AuthServiceCase(MigratedDbCase):
    """Служба учётных записей поверх временной БД: она работает через get_session."""

    def setUp(self):
        super().setUp()
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        patcher = patch("services.auth_service.get_session", self.Session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def create_admin(self, password: str = "Пароль12345"):
        return auth_service.create_account("admin", "admin@localhost", password)


class FirstRunTest(AuthServiceCase):

    def test_empty_database_is_first_run(self):
        self.assertFalse(auth_service.has_users())

    def test_account_created_by_user_ends_first_run(self):
        self.assertTrue(self.create_admin()["success"])
        self.assertTrue(auth_service.has_users())

    def test_created_account_is_administrator(self):
        account = self.create_admin()["account"]
        self.assertIs(UserPosition.admin, account.position)
        self.assertTrue(account.is_admin)
        self.assertFalse(account.must_change_password)


class AccountCreationTest(AuthServiceCase):

    def test_password_is_hashed_before_writing(self):
        self.create_admin("Пароль12345")
        stored = scalar(self.engine, "SELECT password_hash FROM users WHERE username = 'admin'")
        self.assertNotEqual("Пароль12345", stored)
        self.assertTrue(is_hashed(stored))

    def test_short_password_rejected(self):
        result = self.create_admin("1234567")
        self.assertFalse(result["success"])
        self.assertIn(str(MIN_PASSWORD_LENGTH), result["message"])
        self.assertFalse(auth_service.has_users())

    def test_duplicate_username_explained_in_words(self):
        self.create_admin()
        result = auth_service.create_account("admin", "other@localhost", "Пароль12345")
        self.assertFalse(result["success"])
        self.assertEqual("Такой логин уже занят.", result["message"])

    def test_duplicate_email_explained_in_words(self):
        self.create_admin()
        result = auth_service.create_account("user", "admin@localhost", "Пароль12345")
        self.assertFalse(result["success"])
        self.assertIn("почты", result["message"])

    def test_too_long_email_rejected_before_the_database(self):
        """Колонка — VARCHAR(25); SQLite длину не проверяет и записал бы что угодно."""
        result = auth_service.create_account(
            "user", "very.long.address.for.column@example.com", "Пароль12345"
        )
        self.assertFalse(result["success"])
        self.assertIn("25", result["message"])


class SignInTest(AuthServiceCase):

    def setUp(self):
        super().setUp()
        self.create_admin("Пароль12345")

    def test_correct_password_opens_the_account(self):
        result = auth_service.sign_in("admin", "Пароль12345")
        self.assertTrue(result["success"])
        self.assertEqual("admin", result["account"].username)

    def test_wrong_password_rejected(self):
        self.assertFalse(auth_service.sign_in("admin", "Пароль1234")["success"])

    def test_unknown_user_gets_the_same_answer(self):
        """Ответ не должен подсказывать, какой логин существует."""
        wrong_password = auth_service.sign_in("admin", "нетакой12345")
        unknown_user = auth_service.sign_in("нетакого", "нетакой12345")
        self.assertEqual(wrong_password["message"], unknown_user["message"])

    def test_password_is_not_trimmed(self):
        """BUG-28: с обрезкой пробелов пароль с пробелом на конце не подошёл бы."""
        auth_service.create_account("user", "user@localhost", "пароль с концом ")
        self.assertTrue(auth_service.sign_in("user", "пароль с концом ")["success"])
        self.assertFalse(auth_service.sign_in("user", "пароль с концом")["success"])


class PasswordChangeTest(AuthServiceCase):

    def setUp(self):
        super().setUp()
        self.account = self.create_admin("Пароль12345")["account"]

    def test_new_password_replaces_the_old_one(self):
        self.assertTrue(
            auth_service.change_password(self.account.id, "Новый пароль123")["success"]
        )
        self.assertTrue(auth_service.sign_in("admin", "Новый пароль123")["success"])
        self.assertFalse(auth_service.sign_in("admin", "Пароль12345")["success"])

    def test_same_password_rejected(self):
        """Иначе обязательная смена снималась бы, не меняя самого пароля."""
        result = auth_service.change_password(self.account.id, "Пароль12345")
        self.assertFalse(result["success"])
        self.assertIn("совпадает", result["message"])

    def test_short_password_rejected(self):
        self.assertFalse(auth_service.change_password(self.account.id, "1234567")["success"])
        self.assertTrue(auth_service.sign_in("admin", "Пароль12345")["success"])

    def test_wrong_current_password_rejected(self):
        result = auth_service.change_password(
            self.account.id, "Новый пароль123", current_password="Пароль1234"
        )
        self.assertFalse(result["success"])
        self.assertTrue(auth_service.sign_in("admin", "Пароль12345")["success"])

    def test_change_clears_the_forced_flag(self):
        with self.Session() as session:
            session.execute(text("UPDATE users SET must_change_password = 1"))
            session.commit()

        result = auth_service.change_password(self.account.id, "Новый пароль123")

        self.assertTrue(result["success"])
        self.assertFalse(result["account"].must_change_password)
        self.assertFalse(auth_service.sign_in("admin", "Новый пароль123")["account"]
                         .must_change_password)


if __name__ == "__main__":
    unittest.main()
