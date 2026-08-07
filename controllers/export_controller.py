# controllers/export_controller.py
from decimal import Decimal
from typing import List, Tuple, Optional, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QTableView
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from db.models.roles import RAW_VALUE_ROLE


class ExportController:
    """Экспорт таблицы главного окна в XLSX: числа числами, разметка — как на экране."""

    # Формат разрядности. Запятая и точка в коде формата — не символы, а
    # обозначения разделителей: Excel подставляет принятые в своей локали,
    # то есть в русской покажет «1 234,57».
    INT_FORMAT = "#,##0"
    DECIMAL_FORMAT = "#,##0.00"

    # Ведущие символы, с которых Excel начинает разбор ячейки как формулы.
    FORMULA_STARTERS = ("=", "+", "-", "@")

    @staticmethod
    def _cell_value(model, idx) -> Any:
        """Значение ячейки для файла: сырое, если модель его отдаёт.

        `DisplayRole` — это готовая строка для экрана («1 234,57»), и запись её в
        книгу давала текстовые ячейки: Excel помечал их «Число сохранено как
        текст», и по такому файлу нельзя было ни суммировать, ни строить
        диаграммы (FUNC-2). Модели без роли сырого значения (например, чужие)
        по-прежнему выгружаются как показываются.
        """
        val = model.data(idx, RAW_VALUE_ROLE)
        if val is None:
            val = model.data(idx, Qt.ItemDataRole.DisplayRole)
        return val

    @staticmethod
    def _write_cell(ws, row: int, column: int, val: Any):
        """Пишет значение, сохраняя его тип: число — числом, текст — текстом."""
        if isinstance(val, Decimal):
            val = float(val)

        if isinstance(val, bool) or val is None:
            # bool — подкласс int, но в отчётности его нет; None — пустая ячейка.
            cell = ws.cell(row=row, column=column, value="" if val is None else str(val))
            cell.data_type = "s"
            return cell

        if isinstance(val, (int, float)):
            cell = ws.cell(row=row, column=column, value=val)
            cell.number_format = (
                ExportController.INT_FORMAT if float(val).is_integer()
                else ExportController.DECIMAL_FORMAT
            )
            cell.alignment = Alignment(horizontal="right", vertical="center")
            return cell

        text = str(val)
        cell = ws.cell(row=row, column=column, value=text)
        if text.startswith(ExportController.FORMULA_STARTERS):
            # openpyxl определяет формулу по ведущему символу строки. В ячейки
            # попадают названия из присланных файлов, то есть текст внешнего
            # происхождения: «=1+1» стало бы вычисляемой формулой, а «=cmd|…» —
            # приёмом внедрения формул на машине получателя (FUNC-9).
            cell.data_type = "s"
        return cell

    @staticmethod
    def export_to_excel(
        table_view: QTableView,
        file_path: str,
        parent=None,
        header_groups: Optional[List[Tuple[int, int, str]]] = None,
    ) -> bool:
        try:
            model = table_view.model()
            if not model:
                return False

            nrows = model.rowCount()
            ncols = model.columnCount()
            groups = header_groups or []

            wb = Workbook()
            ws = wb.active
            ws.title = "Данные"

            center = Alignment(horizontal="center", vertical="center", wrap_text=True)
            hdr_font = Font(bold=True)

            data_start_row: int

            if groups:
                in_group = set()
                for first, last, _ in groups:
                    for c in range(first, last + 1):
                        in_group.add(c)

                # Верхний ряд: объединённые подписи месяцев / групп
                for first, last, label in groups:
                    if first > last:
                        continue
                    c1, c2 = first + 1, last + 1
                    if c1 == c2:
                        cell = ws.cell(row=1, column=c1, value=label or "")
                    else:
                        ws.merge_cells(
                            start_row=1, start_column=c1, end_row=1, end_column=c2
                        )
                        cell = ws.cell(row=1, column=c1, value=label or "")
                    cell.alignment = center
                    cell.font = hdr_font

                # Колонки без группы (напр. Показатель, Ед. изм., Код): заголовок на двух рядах
                for c in range(ncols):
                    if c in in_group:
                        continue
                    c1 = c + 1
                    ws.merge_cells(start_row=1, start_column=c1, end_row=2, end_column=c1)
                    h = model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
                    cell = ws.cell(row=1, column=c1, value="" if h is None else str(h))
                    cell.alignment = center
                    cell.font = hdr_font

                # Нижний ряд заголовков для колонок внутри групп
                for c in range(ncols):
                    if c not in in_group:
                        continue
                    h = model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
                    cell = ws.cell(row=2, column=c + 1, value="" if h is None else str(h))
                    cell.alignment = center
                    cell.font = hdr_font

                data_start_row = 3
            else:
                for c in range(ncols):
                    h = model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
                    cell = ws.cell(row=1, column=c + 1, value="" if h is None else str(h))
                    cell.alignment = center
                    cell.font = hdr_font
                data_start_row = 2

            for r in range(nrows):
                excel_row = data_start_row + r
                for c in range(ncols):
                    idx = model.index(r, c)
                    ExportController._write_cell(ws, excel_row, c + 1, ExportController._cell_value(model, idx))

            # Ширина колонок — грубая оценка по тексту заголовка и первым строкам
            for c in range(ncols):
                letter = get_column_letter(c + 1)
                max_len = 10
                for check_row in (1, 2) if groups else (1,):
                    v = ws.cell(row=check_row, column=c + 1).value
                    if v is not None:
                        max_len = max(max_len, min(60, len(str(v))))
                for rr in range(data_start_row, min(data_start_row + 50, data_start_row + nrows)):
                    v = ws.cell(row=rr, column=c + 1).value
                    if v is not None:
                        max_len = max(max_len, min(60, len(str(v))))
                ws.column_dimensions[letter].width = max_len + 2

            wb.save(file_path)

            if parent:
                QMessageBox.information(parent, "Успех", f"Данные экспортированы в {file_path}")
            return True

        except Exception as e:
            if parent:
                QMessageBox.critical(parent, "Ошибка экспорта", str(e))
            return False
