# forms/mainWin.py
import sys
from pathlib import Path

# Прямой запуск: python forms/mainWin.py — добавляем корень проекта в sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from utils.qt_plugins import ensure_qt_platform_plugins

ensure_qt_platform_plugins()

import logging
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QFileDialog, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt
from db.backup import make_backup
from db.database import db_path, get_session
from db.models.entities import Airline, AirlineIndicators, AirportIndicators
from services import journal_service as journal
from services.import_service import ImportService
from controllers.filter_controller import FilterController
from controllers.export_controller import ExportController
from forms.widgets.filter_widget import FilterWidget
from forms.widgets.airport_filter_widget import AirportFilterWidget
from forms.widgets.data_table_widget import DataTableWidget
from forms.widgets.import_dialog import ImportDialog
from forms.widgets.period_dialog import PeriodDialog
from forms.widgets.reference_dialog import ReferenceDialog
from utils.constants import MONTHS_RU, MODE_AIRLINE, MODE_AIRPORT

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self, current_user):
        super().__init__()
        self.current_user = current_user
        self.current_mode = MODE_AIRLINE
        self.filter_controller = FilterController()
        self.export_controller = ExportController()

        self.setWindowTitle(f"Система учета статистических данных — {current_user.username}")
        self.setMinimumSize(1200, 750)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self._setup_toolbar(main_layout)
        self._setup_tabs(main_layout)

        self.tabs.currentChanged.connect(self._on_main_tab_changed)

        self._load_initial_data()

    def _setup_toolbar(self, layout):
        toolbar = QHBoxLayout()

        self.import_btn = QPushButton("Импорт файлов")
        self.import_btn.clicked.connect(self.import_file)

        self.export_btn = QPushButton("Экспорт в XLSX")
        self.export_btn.clicked.connect(self.export_to_xlsx)

        self.reference_btn = QPushButton("Справочники")
        self.reference_btn.clicked.connect(self.open_references)

        self.exit_btn = QPushButton("Выход")
        self.exit_btn.clicked.connect(self.logout_action)

        toolbar.addWidget(self.import_btn)
        toolbar.addWidget(self.export_btn)
        toolbar.addWidget(self.reference_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.exit_btn)

        layout.addLayout(toolbar)

    def _setup_tabs(self, layout):
        self.tabs = QTabWidget()

        self.tab_airlines = QWidget()
        self.tabs.addTab(self.tab_airlines, "Авиакомпании")
        lay_a = QVBoxLayout(self.tab_airlines)
        self.filter_widget_airline = FilterWidget()
        self.filter_widget_airline.filters_changed.connect(self._reload_airline_tab)
        self.filter_widget_airline.reset_requested.connect(self._on_reset_airline_filters)
        lay_a.addWidget(self.filter_widget_airline)
        self.table_widget_airline = DataTableWidget()
        self.table_widget_airline.delete_requested.connect(self.delete_records)
        self.table_widget_airline.set_parent_window(self)
        lay_a.addWidget(self.table_widget_airline)

        self.tab_airports = QWidget()
        self.tabs.addTab(self.tab_airports, "Аэропорты (15-ГА)")
        lay_p = QVBoxLayout(self.tab_airports)
        self.airport_filter_widget = AirportFilterWidget()
        self.airport_filter_widget.filters_changed.connect(self._reload_airport_tab)
        self.airport_filter_widget.reset_requested.connect(self._on_reset_airport_filters)
        lay_p.addWidget(self.airport_filter_widget)
        self.table_widget_airport = DataTableWidget()
        self.table_widget_airport.delete_requested.connect(self.delete_records)
        self.table_widget_airport.set_parent_window(self)
        lay_p.addWidget(self.table_widget_airport)

        layout.addWidget(self.tabs)

    def _load_initial_data(self):
        self._reload_airline_tab()
        self._reload_airport_tab()

    def _reload_reference_lists(self):
        """Справочники изменились: сбросить кеш и перечитать списки в обеих вкладках.

        Один вызов на обе вкладки. Прежде инвалидация была точечной: после импорта
        сбрасывался кеш главного окна (в фильтрах он не участвует) и обновлялась
        только вкладка аэропортов, поэтому списки на вкладке «Авиакомпании»
        оставались прежними до перезапуска программы (BUG-7).
        """
        self.filter_controller.clear_cache()
        self.filter_widget_airline.reload_reference_lists()
        self.airport_filter_widget.reload_reference_lists()

    def _on_main_tab_changed(self, idx: int):
        self.current_mode = MODE_AIRLINE if idx == 0 else MODE_AIRPORT
        if idx == 0:
            self._reload_airline_tab()
        else:
            self._reload_airport_tab()

    def _reload_airline_tab(self):
        filters = self.filter_controller.get_current_filters(self.filter_widget_airline)
        self.table_widget_airline.load_data(MODE_AIRLINE, filters)

    def _reload_airport_tab(self):
        filters = self.filter_controller.get_airport_tab_filters(self.airport_filter_widget)
        self.table_widget_airport.load_data(MODE_AIRPORT, filters)

    def _on_reset_airline_filters(self):
        self.filter_widget_airline.reset_filters()
        self._reload_airline_tab()

    def _on_reset_airport_filters(self):
        self.airport_filter_widget.reset_filters()
        self._reload_airport_tab()

    def reload_table_for_widget(self, table_widget: DataTableWidget):
        """Перезагрузка данных при смене вида таблицы (pivot/detail)."""
        if table_widget is self.table_widget_airline:
            self._reload_airline_tab()
        elif table_widget is self.table_widget_airport:
            self._reload_airport_tab()

    def import_file(self):
        """Импорт одного или нескольких файлов; месяц/год — с листа «Титул» (D13) в каждом файле."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы для импорта", "",
            "Excel и XML (*.xlsx *.xls *.xml);;Excel (*.xlsx *.xls);;XML (*.xml);;Все файлы (*)"
        )
        if not paths:
            return

        dialog = ImportDialog(self)

        airlines = ImportService.get_airlines()
        dialog.set_entities(airlines, 'airline')

        if dialog.exec() != ImportDialog.DialogCode.Accepted:
            return

        entity_type = dialog.get_type()
        entity_id = dialog.get_entity_id()

        if not entity_id:
            QMessageBox.warning(self, "Предупреждение", "Не выбрано предприятие")
            return

        # Импорт заменяет период целиком: строки, исчезнувшие из исправленного
        # отчёта, удаляются (DATA-5). Копия снимается до первого файла — одна на
        # весь пакет, а не на каждый.
        import_backup = None
        try:
            import_backup = make_backup(db_path(), reason="import")
        except Exception:
            log.exception("Не удалось снять копию базы")

        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            report_lines = []
            any_success = False
            for file_path in paths:
                result = ImportService.import_file(
                    file_path,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    month=None,
                    year=None,
                )

                # Период не прочитался — спрашиваем его у пользователя вместо
                # прежней молчаливой подстановки «январь 2025» (DATA-2).
                if result.get("period_required"):
                    result = self._import_with_asked_period(
                        file_path, entity_type, entity_id, result
                    )

                base_name = result.get("source_file") or Path(file_path).name
                pm = result.get("period_month")
                py = result.get("period_year")
                month_label = MONTHS_RU.get(pm, pm) if pm else "?"
                period = f"{month_label} {py}" if py else str(month_label)

                if result.get("success"):
                    any_success = True
                    sheet = result.get("sheet_name")
                    where = f", лист «{sheet}»" if sheet else ""
                    report_lines.append(
                        f"OK — {base_name} ({period}{where}): {result.get('message', '')}"
                    )
                else:
                    report_lines.append(
                        f"Ошибка — {base_name}: {result.get('message', 'Неизвестная ошибка')}"
                    )

            QApplication.restoreOverrideCursor()

            report = "\n".join(report_lines)
            if import_backup:
                report += f"\n\nКопия базы перед импортом: {import_backup.name}"
            if any_success:
                QMessageBox.information(self, "Импорт завершён", report)
                self._reload_reference_lists()
                self._load_initial_data()
            else:
                QMessageBox.warning(self, "Импорт не выполнен", report)

        except Exception as e:
            QApplication.restoreOverrideCursor()
            log.exception("Импорт не выполнен")
            QMessageBox.critical(self, "Ошибка импорта", str(e))

    def open_references(self):
        """Окно ведения справочников.

        После закрытия списки фильтров перечитываются в обеих вкладках: справочники
        могли измениться, а кеш держит их до явного сброса.
        """
        ReferenceDialog(self).exec()
        self._reload_reference_lists()
        self._load_initial_data()

    def _import_with_asked_period(self, file_path, entity_type, entity_id, result: dict) -> dict:
        """Спрашивает период у пользователя и повторяет импорт файла.

        Курсор ожидания снимается на время диалога: он выставлен на весь пакет,
        а здесь управление возвращается человеку.
        """
        QApplication.restoreOverrideCursor()
        dialog = PeriodDialog(
            Path(file_path).name,
            month=result.get("period_month"),
            year=result.get("period_year"),
            parent=self,
        )
        accepted = dialog.exec() == PeriodDialog.DialogCode.Accepted
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        if not accepted:
            return {
                "success": False,
                "message": "Файл пропущен: отчётный период не указан.",
                "source_file": Path(file_path).name,
            }

        return ImportService.import_file(
            file_path,
            entity_type=entity_type,
            entity_id=entity_id,
            month=dialog.get_month(),
            year=dialog.get_year(),
        )

    def refresh_entities(self, entity_type: str, combo_box):
        """Обновляет список предприятий в диалоге"""
        if entity_type == 'airline':
            entities = ImportService.get_airlines()
        else:
            entities = ImportService.get_airports()

        combo_box.clear()
        for entity_id, entity_name in entities:
            combo_box.addItem(entity_name, entity_id)
        combo_box.setEnabled(True)

    def export_to_xlsx(self):
        """Экспорт текущей вкладки в Excel"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как", "export.xlsx",
            "Excel файлы (*.xlsx)"
        )
        if not file_path:
            return
        tw = self.table_widget_airline if self.tabs.currentIndex() == 0 else self.table_widget_airport
        groups = tw.get_header_groups_for_export()
        self.export_controller.export_to_excel(
            tw.get_table_view(),
            file_path,
            self,
            header_groups=groups,
        )

    def delete_records(self, ids_to_delete: list):
        """Удаление записей"""
        count = len(ids_to_delete)
        reply = QMessageBox.question(
            self, "Подтверждение удаления",
            f"Удалить {count} запис{'ь' if count == 1 else 'и'}?\nЭто действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Копия базы снимается до удаления: отменить его нечем, а отчётность
        # восстанавливается только повторной загрузкой файлов (FUNC-6).
        backup_path = None
        try:
            backup_path = make_backup(db_path(), reason="delete")
        except Exception:
            log.exception("Не удалось снять копию базы")

        deleted = 0
        try:
            with get_session() as session:
                if self.current_mode == MODE_AIRLINE:
                    for rec_id in ids_to_delete:
                        rec = session.get(AirlineIndicators, rec_id)
                        if rec:
                            session.delete(rec)
                            deleted += 1
                else:
                    for rec_id in ids_to_delete:
                        rec = session.get(AirportIndicators, rec_id)
                        if rec:
                            session.delete(rec)
                            deleted += 1
                session.commit()

            journal.record_deletion(
                count=deleted,
                entity_type='airline' if self.current_mode == MODE_AIRLINE else 'airport',
                message=f"копия базы: {backup_path.name}" if backup_path else "копия базы не снята",
                user=getattr(self.current_user, "username", None),
            )

            note = f"\nКопия базы: {backup_path.name}" if backup_path else ""
            QMessageBox.information(self, "Готово", f"Удалено записей: {deleted}{note}")
            self._load_initial_data()

        except Exception as e:
            log.exception("Не удалось удалить записи")
            QMessageBox.critical(self, "Ошибка", f"Ошибка удаления: {e}")

    def logout_action(self):
        """Выход из системы"""
        reply = QMessageBox.question(
            self, 'Подтверждение выхода',
            'Вы действительно хотите выйти из системы?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.close()
            from forms.auth import Auth
            self.auth_window = Auth()
            self.auth_window.show()


if __name__ == "__main__":
    print(
        "Точка входа приложения — main.py в корне проекта:\n"
        "  python main.py",
        file=sys.stderr,
    )
    raise SystemExit(1)
