# controllers/export_controller.py
"""Сборка книги XLSX: числа числами, разметка — как на экране.

Слой не знает ни о Qt, ни о том, откуда взялись значения (ARCH-2). Прежде
экспортёр сам читал `QTableView` и сам показывал `QMessageBox` — то есть был
кодом интерфейса, живущим в слое, который по замыслу интерфейса не касается.
Позвать его из теста или из командной строки было нельзя.

Чтение модели и окна сообщений переехали в [forms/table_export.py](forms/table_export.py);
сюда приходят готовые заголовки и строки значений.
"""
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from controllers.export_header import ExportHeader


class ExportController:
    """Записывает книгу по готовым заголовкам и строкам значений."""

    # Формат разрядности. Запятая и точка в коде формата — не символы, а
    # обозначения разделителей: Excel подставляет принятые в своей локали,
    # то есть в русской покажет «1 234,57».
    INT_FORMAT = "#,##0"
    DECIMAL_FORMAT = "#,##0.00"

    # Ведущие символы, с которых Excel начинает разбор ячейки как формулы.
    FORMULA_STARTERS = ("=", "+", "-", "@")

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
    def _write_header(ws, header: ExportHeader | None) -> int:
        """Пишет шапку отчёта и возвращает номер строки, с которой идёт таблица.

        Без шапки книга получалась обезличенной: ни предприятия, ни периода, а
        лист назывался «Данные» (FUNC-4). Между шапкой и таблицей остаётся пустая
        строка — она же граница для автофильтра и для взгляда.
        """
        if header is None or not header.lines:
            return 1

        ws.title = header.sheet_title
        label_font = Font(bold=True)
        for offset, (label, value) in enumerate(header.lines):
            ws.cell(row=offset + 1, column=1, value=f"{label}:").font = label_font
            # Значение пишется текстом сознательно: это подпись отчёта, а не
            # величина, и превращать «12-ГА» в дату или число Excel не должен.
            cell = ws.cell(row=offset + 1, column=2, value=str(value))
            cell.data_type = "s"

        return len(header.lines) + 2

    @staticmethod
    def write_workbook(
        file_path: str,
        headers: list[str],
        rows: list[list[Any]],
        header_groups: list[tuple[int, int, str]] | None = None,
        header: ExportHeader | None = None,
    ) -> None:
        """Пишет книгу. Об ошибке сообщает исключением, а не окном и не `False`.

        Прежде метод возвращал `False` и сам показывал `QMessageBox`: вызывающий
        не мог узнать, что именно не получилось, а тест не мог позвать экспорт
        вовсе — модальное окно остановило бы прогон (ARCH-2).
        """
        ncols = len(headers)
        nrows = len(rows)
        groups = header_groups or []

        wb = Workbook()
        ws = wb.active
        ws.title = "Данные"

        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        hdr_font = Font(bold=True)

        # Заголовки таблицы начинаются под шапкой, а не с первой строки.
        top = ExportController._write_header(ws, header)
        header_rows = (top, top + 1) if groups else (top,)
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
                    cell = ws.cell(row=top, column=c1, value=label or "")
                else:
                    ws.merge_cells(
                        start_row=top, start_column=c1, end_row=top, end_column=c2
                    )
                    cell = ws.cell(row=top, column=c1, value=label or "")
                cell.alignment = center
                cell.font = hdr_font

            # Колонки без группы (напр. Показатель, Ед. изм., Код): заголовок на двух рядах
            for c in range(ncols):
                if c in in_group:
                    continue
                c1 = c + 1
                ws.merge_cells(start_row=top, start_column=c1, end_row=top + 1, end_column=c1)
                cell = ws.cell(row=top, column=c1, value=headers[c])
                cell.alignment = center
                cell.font = hdr_font

            # Нижний ряд заголовков для колонок внутри групп
            for c in range(ncols):
                if c not in in_group:
                    continue
                cell = ws.cell(row=top + 1, column=c + 1, value=headers[c])
                cell.alignment = center
                cell.font = hdr_font

            data_start_row = top + 2
        else:
            for c in range(ncols):
                cell = ws.cell(row=top, column=c + 1, value=headers[c])
                cell.alignment = center
                cell.font = hdr_font
            data_start_row = top + 1

        for r, row_values in enumerate(rows):
            excel_row = data_start_row + r
            for c in range(ncols):
                ExportController._write_cell(ws, excel_row, c + 1, row_values[c])

        # Ширина колонок — грубая оценка по тексту заголовка и первым строкам
        for c in range(ncols):
            letter = get_column_letter(c + 1)
            max_len = 10
            for check_row in header_rows:
                v = ws.cell(row=check_row, column=c + 1).value
                if v is not None:
                    max_len = max(max_len, min(60, len(str(v))))
            for rr in range(data_start_row, min(data_start_row + 50, data_start_row + nrows)):
                v = ws.cell(row=rr, column=c + 1).value
                if v is not None:
                    max_len = max(max_len, min(60, len(str(v))))
            ws.column_dimensions[letter].width = max_len + 2

        wb.save(file_path)
