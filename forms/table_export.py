# forms/table_export.py
"""Выгрузка того, что на экране: чтение модели Qt и разговор с пользователем (ARCH-2).

Обе эти обязанности жили в `controllers/export_controller.py`: он сам обходил
`QTableView` и сам показывал `QMessageBox`. Слой, который по замыслу интерфейса
не касается, оказывался кодом интерфейса — позвать его из теста или из
командной строки было нельзя, модальное окно остановило бы и то и другое.

Здесь осталось только то, что и правда про интерфейс. Сборка книги — в
[controllers/export_controller.py](controllers/export_controller.py), и ей
приходят готовые заголовки и строки значений.
"""
import logging
from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QTableView

from controllers.export_controller import ExportController
from controllers.export_header import ExportHeader
from forms.models.roles import RAW_VALUE_ROLE

log = logging.getLogger(__name__)


def cell_value(model, index) -> Any:
    """Значение ячейки для файла: сырое, если модель его отдаёт.

    `DisplayRole` — это готовая строка для экрана («1 234,57»), и запись её в
    книгу давала текстовые ячейки: Excel помечал их «Число сохранено как текст»,
    и по такому файлу нельзя было ни суммировать, ни строить диаграммы (FUNC-2).
    Модели без роли сырого значения по-прежнему выгружаются как показываются.
    """
    value = model.data(index, RAW_VALUE_ROLE)
    if value is None:
        value = model.data(index, Qt.ItemDataRole.DisplayRole)
    return value


def read_table(table_view: QTableView) -> Tuple[List[str], List[List[Any]]]:
    """Снимает с таблицы заголовки и значения — всё, что нужно книге."""
    model = table_view.model()
    if model is None:
        return [], []

    ncols = model.columnCount()
    headers = []
    for col in range(ncols):
        caption = model.headerData(col, Qt.Orientation.Horizontal,
                                   Qt.ItemDataRole.DisplayRole)
        headers.append("" if caption is None else str(caption))

    rows = [
        [cell_value(model, model.index(row, col)) for col in range(ncols)]
        for row in range(model.rowCount())
    ]
    return headers, rows


def export_table_to_excel(
    table_view: QTableView,
    file_path: str,
    parent=None,
    header_groups: Optional[List[Tuple[int, int, str]]] = None,
    header: Optional[ExportHeader] = None,
) -> bool:
    """Выгружает таблицу и сообщает пользователю, чем дело кончилось."""
    headers, rows = read_table(table_view)
    if not headers:
        return False

    try:
        ExportController.write_workbook(
            file_path, headers, rows, header_groups=header_groups, header=header
        )
    except Exception as error:
        log.exception("Выгрузка в XLSX не выполнена: %s", file_path)
        if parent:
            QMessageBox.critical(parent, "Ошибка экспорта", str(error))
        return False

    if parent:
        QMessageBox.information(parent, "Успех", f"Данные экспортированы в {file_path}")
    return True
