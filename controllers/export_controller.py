# controllers/export_controller.py
from typing import List, Tuple, Optional, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QTableView
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter


class ExportController:
    """Экспорт таблицы главного окна в XLSX в том же виде, что на экране (DisplayRole, группы заголовков)."""

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
                    val = model.data(idx, Qt.ItemDataRole.DisplayRole)
                    if val is None:
                        cell_val: Any = ""
                    elif isinstance(val, str):
                        cell_val = val
                    else:
                        cell_val = val
                    cell = ws.cell(row=excel_row, column=c + 1, value=cell_val)
                    if isinstance(cell_val, (int, float)):
                        cell.alignment = Alignment(horizontal="right", vertical="center")

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
