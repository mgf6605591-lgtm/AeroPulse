# services/reference_service.py
"""Ведение справочников: населённые пункты, аэропорты, авиакомпании, показатели.

Все четыре справочника устроены одинаково — таблица, редактор, удаление, — поэтому
описаны данными, а не четырьмя копиями одного кода: `KINDS` задаёт поля и колонки,
операции общие.

Удаление различает два случая (SCH-10). Запись, на которую ещё ничего не ссылается,
удаляется — это «ошибочно завёл». Запись с накопленной отчётностью удалить нельзя:
её выводят из работы флагом `is_active`, история при этом сохраняется. Прежде здесь
стоял каскад, и одна строка справочника уносила с собой отчёты за все периоды.

Наружу отдаются словари, а не объекты ORM: за пределами сессии они уже отсоединены,
и обращение к их полям падает (BUG-14).
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from db.database import get_session
from db.models.entities import (
    Airline,
    AirlineIndicators,
    Airport,
    AirportIndicators,
    Indicator,
    Locality,
    Shipping,
)


@dataclass(frozen=True)
class Field:
    """Поле редактора справочника."""

    name: str
    label: str
    kind: str = "text"          # text | ref
    required: bool = True
    max_length: Optional[int] = None
    ref: Optional[str] = None   # ключ справочника, если kind == "ref"
    allow_empty: bool = False   # для необязательной ссылки


@dataclass(frozen=True)
class Column:
    """Колонка таблицы справочника."""

    key: str
    label: str


@dataclass(frozen=True)
class Kind:
    key: str
    title: str
    model: type
    columns: Tuple[Column, ...]
    fields: Tuple[Field, ...]
    order_by: str
    has_active: bool = False
    # Сколько записей ссылается на строку справочника. Ноль означает, что удалить
    # её безопасно; всё остальное — что за ней стоят данные.
    usage: Optional[Callable[[Any, int], int]] = None
    # Три формы для согласования с числом: 1 строка, 2 строки, 5 строк.
    usage_forms: Tuple[str, str, str] = ("связанная запись", "связанные записи", "связанных записей")


def plural(count: int, forms: Tuple[str, str, str]) -> str:
    """Существительное в форме, согласованной с числом."""
    tail_100 = abs(count) % 100
    tail_10 = abs(count) % 10
    if 11 <= tail_100 <= 14:
        return forms[2]
    if tail_10 == 1:
        return forms[0]
    if 2 <= tail_10 <= 4:
        return forms[1]
    return forms[2]


def _airport_usage(session, airport_id: int) -> int:
    return session.query(func.count(AirportIndicators.id)).filter(
        AirportIndicators.airport_id == airport_id
    ).scalar() or 0


def _airline_usage(session, airline_id: int) -> int:
    """Отчётные строки авиакомпании — через её рейсы."""
    return session.query(func.count(AirlineIndicators.id)).join(
        Shipping, AirlineIndicators.shipping_id == Shipping.id
    ).filter(Shipping.airline_id == airline_id).scalar() or 0


def _locality_usage(session, locality_id: int) -> int:
    return session.query(func.count(Airport.id)).filter(
        Airport.locality_id == locality_id
    ).scalar() or 0


def _indicator_usage(session, indicator_id: int) -> int:
    airline = session.query(func.count(AirlineIndicators.id)).filter(
        AirlineIndicators.indicator_id == indicator_id
    ).scalar() or 0
    airport = session.query(func.count(AirportIndicators.id)).filter(
        AirportIndicators.indicator_id == indicator_id
    ).scalar() or 0
    return airline + airport


KINDS: Dict[str, Kind] = {
    "locality": Kind(
        key="locality",
        title="Населённые пункты",
        model=Locality,
        columns=(Column("name", "Название"),),
        fields=(Field("name", "Название", max_length=50),),
        order_by="name",
        usage=_locality_usage,
        usage_forms=("аэропорт", "аэропорта", "аэропортов"),
    ),
    "airport": Kind(
        key="airport",
        title="Аэропорты",
        model=Airport,
        columns=(
            Column("code", "Код"),
            Column("name", "Название"),
            Column("locality_id", "Населённый пункт"),
        ),
        fields=(
            Field("code", "Код", max_length=5),
            Field("name", "Название", max_length=25),
            Field("locality_id", "Населённый пункт", kind="ref", ref="locality"),
        ),
        order_by="name",
        has_active=True,
        usage=_airport_usage,
        usage_forms=("отчётная строка", "отчётные строки", "отчётных строк"),
    ),
    "airline": Kind(
        key="airline",
        title="Авиакомпании",
        model=Airline,
        columns=(Column("code", "Код"), Column("name", "Название")),
        fields=(
            Field("code", "Код", max_length=5),
            Field("name", "Название", max_length=50),
        ),
        order_by="name",
        has_active=True,
        usage=_airline_usage,
        usage_forms=("отчётная строка", "отчётные строки", "отчётных строк"),
    ),
    "indicator": Kind(
        key="indicator",
        title="Показатели",
        model=Indicator,
        columns=(
            Column("code", "Код"),
            Column("name", "Название"),
            Column("measure", "Ед. изм."),
            Column("parent_id", "Родитель"),
        ),
        fields=(
            Field("code", "Код", max_length=20),
            Field("name", "Название", max_length=50),
            Field("measure", "Ед. изм.", max_length=20),
            Field(
                "parent_id",
                "Родитель («в том числе»)",
                kind="ref",
                ref="indicator",
                required=False,
                allow_empty=True,
            ),
        ),
        order_by="code",
        usage=_indicator_usage,
        usage_forms=("отчётная строка", "отчётные строки", "отчётных строк"),
    ),
}


def ok(message: str = "") -> dict:
    return {"success": True, "message": message}


def fail(message: str) -> dict:
    return {"success": False, "message": message}


class ReferenceService:
    """Операции над справочниками. Наружу — словари, внутрь — только простые значения."""

    @classmethod
    def kind(cls, key: str) -> Kind:
        return KINDS[key]

    @classmethod
    def list_rows(cls, key: str) -> List[dict]:
        """Строки справочника вместе с числом ссылающихся записей."""
        kind = KINDS[key]
        with get_session() as session:
            rows = session.query(kind.model).order_by(getattr(kind.model, kind.order_by)).all()
            labels = cls._ref_labels(session)
            out: List[dict] = []
            for row in rows:
                item: dict = {"id": row.id}
                for column in kind.columns:
                    value = getattr(row, column.key, None)
                    item[column.key] = cls._display(column.key, value, labels)
                item["is_active"] = bool(getattr(row, "is_active", True))
                item["usage"] = kind.usage(session, row.id) if kind.usage else 0
                out.append(item)
            return out

    @classmethod
    def raw_values(cls, key: str, row_id: int) -> Optional[dict]:
        """Значения полей как они лежат в базе — для редактора.

        В отличие от list_rows, ссылки отдаются идентификаторами: редактору нужно
        выбрать элемент в списке, а не показать подпись.
        """
        kind = KINDS[key]
        with get_session() as session:
            row = session.get(kind.model, row_id)
            if row is None:
                return None
            return {field.name: getattr(row, field.name, None) for field in kind.fields}

    @classmethod
    def choices(cls, key: str, exclude_id: Optional[int] = None) -> List[Tuple[int, str]]:
        """Варианты для поля-ссылки. exclude_id не даёт показателю стать себе родителем."""
        kind = KINDS[key]
        label_attr = "name" if key != "indicator" else None
        with get_session() as session:
            rows = session.query(kind.model).order_by(getattr(kind.model, kind.order_by)).all()
            out = []
            for row in rows:
                if exclude_id is not None and row.id == exclude_id:
                    continue
                if label_attr:
                    label = (getattr(row, label_attr) or "").strip()
                else:
                    label = f"{(row.code or '').strip()} — {(row.name or '').strip()}"
                out.append((row.id, label))
            return out

    @classmethod
    def create(cls, key: str, values: dict) -> dict:
        kind = KINDS[key]
        error = cls._validate(kind, values)
        if error:
            return fail(error)
        try:
            with get_session() as session:
                session.add(kind.model(**cls._clean(kind, values)))
                session.commit()
            return ok("Запись добавлена.")
        except IntegrityError as exc:
            return fail(cls._humanize(exc, kind, "добавить"))

    @classmethod
    def update(cls, key: str, row_id: int, values: dict) -> dict:
        kind = KINDS[key]
        error = cls._validate(kind, values)
        if error:
            return fail(error)
        try:
            with get_session() as session:
                row = session.get(kind.model, row_id)
                if row is None:
                    return fail("Запись не найдена — возможно, её удалили в другом окне.")
                for name, value in cls._clean(kind, values).items():
                    setattr(row, name, value)
                session.commit()
            return ok("Изменения сохранены.")
        except IntegrityError as exc:
            return fail(cls._humanize(exc, kind, "сохранить"))

    @classmethod
    def delete(cls, key: str, row_id: int) -> dict:
        """Удаляет запись, если на неё никто не ссылается.

        Проверка выполняется до попытки удаления, чтобы объяснить отказ по-человечески,
        а не выводить нарушение внешнего ключа (BUG-31). Сам запрет при этом остаётся
        в базе: прикладная проверка — объяснение, а не защита.
        """
        kind = KINDS[key]
        with get_session() as session:
            row = session.get(kind.model, row_id)
            if row is None:
                return fail("Запись не найдена.")
            used = kind.usage(session, row_id) if kind.usage else 0

        if used:
            if kind.has_active:
                return fail(
                    f"Удалить нельзя: с записью связано {used} {plural(used, kind.usage_forms)}. "
                    "Чтобы убрать её из списков выбора, не теряя отчётность, "
                    "пометьте запись недействующей."
                )
            return fail(
                f"Удалить нельзя: с записью связано {used} {plural(used, kind.usage_forms)}. "
                "Сначала удалите или перенесите их."
            )

        try:
            with get_session() as session:
                row = session.get(kind.model, row_id)
                if row is None:
                    return fail("Запись не найдена.")
                session.delete(row)
                session.commit()
            return ok("Запись удалена.")
        except IntegrityError as exc:
            return fail(cls._humanize(exc, kind, "удалить"))

    @classmethod
    def set_active(cls, key: str, row_id: int, active: bool) -> dict:
        """Вывод записи из работы и возврат обратно."""
        kind = KINDS[key]
        if not kind.has_active:
            return fail("Для этого справочника признак действующей записи не предусмотрен.")
        with get_session() as session:
            row = session.get(kind.model, row_id)
            if row is None:
                return fail("Запись не найдена.")
            row.is_active = active
            session.commit()
        return ok("Запись снова действует." if active else "Запись помечена недействующей.")

    # --- вспомогательное ---

    @classmethod
    def _ref_labels(cls, session) -> Dict[str, Dict[int, str]]:
        """Подписи для колонок-ссылок: показывать id пользователю бессмысленно."""
        return {
            "locality_id": {
                row.id: (row.name or "").strip()
                for row in session.query(Locality).all()
            },
            "parent_id": {
                row.id: (row.code or "").strip()
                for row in session.query(Indicator).all()
            },
        }

    @staticmethod
    def _display(column_key: str, value, labels: Dict[str, Dict[int, str]]):
        if value is None:
            return ""
        mapping = labels.get(column_key)
        if mapping is not None:
            return mapping.get(value, f"#{value}")
        return value

    @staticmethod
    def _clean(kind: Kind, values: dict) -> dict:
        out: dict = {}
        for field in kind.fields:
            value = values.get(field.name)
            if field.kind == "ref":
                out[field.name] = int(value) if value else None
            else:
                out[field.name] = (value or "").strip()
        return out

    @staticmethod
    def _validate(kind: Kind, values: dict) -> Optional[str]:
        for field in kind.fields:
            value = values.get(field.name)
            if field.kind == "ref":
                if field.required and not value:
                    return f"Не заполнено поле «{field.label}»."
                continue
            text = (value or "").strip()
            if field.required and not text:
                return f"Не заполнено поле «{field.label}»."
            if field.max_length and len(text) > field.max_length:
                return (
                    f"«{field.label}»: не больше {field.max_length} символов, "
                    f"сейчас {len(text)}."
                )
        return None

    @staticmethod
    def _humanize(exc: IntegrityError, kind: Kind, action: str) -> str:
        """Нарушение ограничения — на русском, а не текстом SQLAlchemy (BUG-31)."""
        text = str(getattr(exc, "orig", exc))
        low = text.lower()
        if "unique" in low:
            return (
                f"Не удалось {action}: запись с такими значениями уже есть в справочнике "
                f"«{kind.title}». Код и название должны быть уникальными."
            )
        if "foreign key" in low:
            return (
                f"Не удалось {action}: на запись ссылаются другие данные. "
                "Если предприятие больше не работает, пометьте его недействующим."
            )
        if "not null" in low:
            return f"Не удалось {action}: заполнены не все обязательные поля."
        return f"Не удалось {action}: {text}"
