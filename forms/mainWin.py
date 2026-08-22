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
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QFileDialog, QMessageBox
)
from db.backup import make_backup
from db.database import db_path
from services.deletion_service import BackupUnavailable, delete_indicators
from services.edit_service import PeriodTaken, RecordGone, update_indicator
from services.import_service import ImportService
from controllers.filter_controller import FilterController
from forms.widgets.filter_widget import FilterWidget
from forms.widgets.airport_filter_widget import AirportFilterWidget
from forms.widgets.data_table_widget import DataTableWidget
from forms.widgets.import_dialog import ENTITY_FROM_FILE, ImportDialog
from forms.widgets.record_edit_dialog import RecordEditDialog
from forms.widgets.reference_dialog import ReferenceDialog
from forms.widgets.scroll_host import HorizontalScrollHost
from forms.import_runner import ImportRunner
from forms.table_export import export_table_to_excel
from utils.constants import MONTHS_RU, MODE_AIRLINE, MODE_AIRPORT

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Главное окно приложения.

    О выходе из системы оно только сообщает: окно входа создаёт и показывает
    владелец жизненного цикла (`forms.app_controller`). Прежде главное окно
    заводило новое окно входа само и клало его в своё поле, будучи уже
    закрытым, — так и набирались «мёртвые» окна на каждом входе-выходе (BUG-8).
    """

    logout_requested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, current_user):
        super().__init__()
        self.current_user = current_user
        self.current_mode = MODE_AIRLINE
        self.filter_controller = FilterController()
        self._import_runner = None

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
        lay_a.addWidget(HorizontalScrollHost(self.filter_widget_airline))
        self.table_widget_airline = DataTableWidget()
        self.table_widget_airline.delete_requested.connect(self.delete_records)
        self.table_widget_airline.edit_requested.connect(self.edit_record)
        self.table_widget_airline.reload_requested.connect(self._reload_airline_tab)
        lay_a.addWidget(self.table_widget_airline)

        self.tab_airports = QWidget()
        self.tabs.addTab(self.tab_airports, "Аэропорты (15-ГА)")
        lay_p = QVBoxLayout(self.tab_airports)
        self.airport_filter_widget = AirportFilterWidget()
        self.airport_filter_widget.filters_changed.connect(self._reload_airport_tab)
        self.airport_filter_widget.reset_requested.connect(self._on_reset_airport_filters)
        lay_p.addWidget(HorizontalScrollHost(self.airport_filter_widget))
        self.table_widget_airport = DataTableWidget()
        self.table_widget_airport.delete_requested.connect(self.delete_records)
        self.table_widget_airport.edit_requested.connect(self.edit_record)
        self.table_widget_airport.reload_requested.connect(self._reload_airport_tab)
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

    def _entity_type(self) -> str:
        """Вид отчётности открытой вкладки — так, как его называют службы.

        Номер режима — внутреннее дело окна; за его пределами предприятие
        описывается словом, и перевод должен быть в одном месте.
        """
        return 'airline' if self.current_mode == MODE_AIRLINE else 'airport'

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

    def import_file(self):
        """Импорт одного или нескольких файлов; месяц/год — с листа «Титул» (D13) в каждом файле."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы для импорта", "",
            "Excel и XML (*.xlsx *.xls *.xml);;Excel (*.xlsx *.xls);;XML (*.xml);;Все файлы (*)"
        )
        if not paths:
            return

        # Тип предприятия — по вкладке, с которой позвали импорт. Диалог всегда
        # открывался на «Авиакомпании», и с вкладки аэропортов пользователь
        # получал не тот список (FUNC-12).
        opened_for = self._entity_type()
        dialog = ImportDialog(self)
        dialog.type_changed.connect(
            lambda entity_type: self.refresh_entities(entity_type, dialog.entity_combo)
        )
        dialog.select_type(opened_for)
        # Список заполняется здесь, а не обработчиком смены типа: если нужный тип
        # уже стоит первым, Qt сигнала о смене не шлёт и список остался бы пустым.
        self.refresh_entities(opened_for, dialog.entity_combo)

        if dialog.exec() != ImportDialog.DialogCode.Accepted:
            return

        entity_type = dialog.get_type()
        entity_id = dialog.get_entity_id()

        if not entity_id and not dialog.entity_from_file():
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

        # Разбор и запись уходят в рабочий поток: на пачке файлов окно
        # переставало перерисовываться и помечалось как «Не отвечает» (BUG-11).
        # Раннер держится в поле, иначе его соберёт сборщик мусора на первом же
        # возврате из этого метода — вместе с потоком.
        self._import_runner = ImportRunner(paths, entity_type, entity_id, parent=self)
        self._import_runner.finished.connect(
            lambda results, cancelled: self._on_import_finished(
                results, cancelled, import_backup
            )
        )
        self._import_runner.start()

    def _on_import_finished(self, results: list, cancelled: bool, import_backup) -> None:
        """Отчёт о пакете: по строке на файл, копия базы и признак отмены."""
        runner, self._import_runner = self._import_runner, None
        if runner is not None:
            runner.deleteLater()

        report_lines = []
        any_success = False
        for result in results:
            base_name = result.source_file or "?"
            month_label = MONTHS_RU.get(result.month, result.month) if result.month else "?"
            period = f"{month_label} {result.year}" if result.year else str(month_label)

            if result.success:
                any_success = True
                where = f", лист «{result.sheet_name}»" if result.sheet_name else ""
                report_lines.append(
                    f"OK — {base_name} ({period}{where}): {result.message}"
                )
            else:
                report_lines.append(
                    f"Ошибка — {base_name}: {result.message or 'Неизвестная ошибка'}"
                )

        report = "\n".join(report_lines)
        if cancelled:
            # Отмена срабатывает между файлами, поэтому загруженное остаётся
            # загруженным — сказать об этом надо прямо.
            head = f"Импорт прерван. Обработано файлов: {len(results)}."
            report = f"{head}\n\n{report}" if report else head
        if import_backup:
            report += f"\n\nКопия базы перед импортом: {import_backup.name}"

        if any_success:
            title = "Импорт прерван" if cancelled else "Импорт завершён"
            QMessageBox.information(self, title, report)
            self._reload_reference_lists()
            self._load_initial_data()
        else:
            QMessageBox.warning(self, "Импорт не выполнен", report)

    def open_references(self):
        """Окно ведения справочников.

        После закрытия списки фильтров перечитываются в обеих вкладках: справочники
        могли измениться, а кеш держит их до явного сброса.
        """
        ReferenceDialog(self).exec()
        self._reload_reference_lists()
        self._load_initial_data()

    def refresh_entities(self, entity_type: str, combo_box):
        """Обновляет список предприятий в диалоге.

        Список открывается пунктом «из файла»: отчёт называет своё предприятие сам
        — 12-ГА в титуле, 15-ГА в шапке бланка, а сводный бланк предприятия
        перечисляет сразу все свои аэропорты, и выбрать из них одно нельзя. Без
        этого пункта годовой комплект на несколько авиакомпаний пришлось бы
        раскладывать по папкам и грузить по одной, указывая каждую руками.
        """
        combo_box.clear()
        combo_box.addItem("— предприятие из файла —", ENTITY_FROM_FILE)
        if entity_type == 'airline':
            entities = ImportService.get_airlines()
        else:
            entities = ImportService.get_airports()

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
        export_table_to_excel(
            tw.get_table_view(),
            file_path,
            self,
            header_groups=groups,
            header=tw.export_header(user=getattr(self.current_user, "username", None)),
        )

    def edit_record(self, row):
        """Правка записи: диалог и итог. Копию, изменение и журнал ведёт служба (ARCH-16)."""
        dialog = RecordEditDialog(row, self)
        if dialog.exec() != RecordEditDialog.DialogCode.Accepted:
            return

        result = self._edit(
            row.id, month=dialog.month(), year=dialog.year(), value=dialog.value(),
            require_backup=True,
        )
        if result is None:
            return

        if not result.changed:
            QMessageBox.information(self, "Готово", "Запись оставлена без изменений.")
            return

        note = (f"\nКопия базы: {result.backup.name}" if result.backup
                else "\nКопия базы не снята.")
        QMessageBox.information(self, "Готово", f"Запись изменена.{note}")
        # Перечитывание за пределами обработки ошибок: правка уже состоялась, и
        # назвать её неудачей из-за сбоя перерисовки значило бы соврать.
        self._load_initial_data()

    def _edit(self, record_id: int, *, month, year, value, require_backup: bool):
        """Правка через службу. None — не состоялась, причина уже показана."""
        try:
            return update_indicator(
                self._entity_type(),
                record_id,
                month=month,
                year=year,
                value=value,
                user=getattr(self.current_user, "username", None),
                require_backup=require_backup,
            )
        except BackupUnavailable as error:
            # Копия снимается до изменения, поэтому сейчас ещё ничего не изменено
            # и решение принадлежит человеку, а не журналу приложения (FUNC-13).
            if not self._agrees_to_edit_without_backup(error):
                return None
            return self._edit(record_id, month=month, year=year, value=value,
                              require_backup=False)
        except PeriodTaken as error:
            # Не ошибка программы, а занятый период: ключ отчётной строки —
            # показатель, предприятие, месяц и год.
            QMessageBox.warning(self, "Период занят", str(error))
            return None
        except RecordGone:
            QMessageBox.warning(
                self, "Записи больше нет",
                "Эту запись уже удалили. Обновите таблицу.",
            )
            return None
        except Exception as error:
            log.exception("Не удалось изменить запись")
            QMessageBox.critical(self, "Ошибка", f"Ошибка правки: {error}")
            return None

    def _agrees_to_edit_without_backup(self, error: Exception) -> bool:
        """Вопрос вместо молчания. По умолчанию — «нет»: прежнее значение не вернуть."""
        return QMessageBox.question(
            self, "Копию базы снять не удалось",
            f"Не удалось снять копию базы:\n{error}\n\n"
            "Если изменить сейчас, прежнее значение восстановить будет нечем.\n"
            "Изменить всё равно?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def delete_records(self, ids_to_delete: list):
        """Удаление записей: вопрос и итог. Копию, удаление и журнал ведёт служба (ARCH-16)."""
        count = len(ids_to_delete)
        reply = QMessageBox.question(
            self, "Подтверждение удаления",
            f"Удалить {count} запис{'ь' if count == 1 else 'и'}?\nЭто действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        result = self._delete(ids_to_delete, require_backup=True)
        if result is None:
            return

        note = (f"\nКопия базы: {result.backup.name}" if result.backup
                else "\nКопия базы не снята.")
        QMessageBox.information(self, "Готово", f"Удалено записей: {result.deleted}{note}")
        # Перечитывание за пределами обработки ошибок: удаление уже состоялось, и
        # назвать его неудачей из-за сбоя перерисовки значило бы соврать.
        self._load_initial_data()

    def _delete(self, ids: list, *, require_backup: bool):
        """Удаление через службу. None — не состоялось, причина уже показана."""
        try:
            return delete_indicators(
                self._entity_type(),
                ids,
                user=getattr(self.current_user, "username", None),
                require_backup=require_backup,
            )
        except BackupUnavailable as error:
            # Копия снимается до удаления, поэтому сейчас ещё ничего не потеряно
            # и решение принадлежит человеку, а не журналу приложения (FUNC-13).
            if not self._agrees_to_delete_without_backup(error):
                return None
            return self._delete(ids, require_backup=False)
        except Exception as error:
            log.exception("Не удалось удалить записи")
            QMessageBox.critical(self, "Ошибка", f"Ошибка удаления: {error}")
            return None

    def _agrees_to_delete_without_backup(self, error: Exception) -> bool:
        """Вопрос вместо молчания. По умолчанию — «нет»: отменить удаление нечем."""
        return QMessageBox.question(
            self, "Копию базы снять не удалось",
            f"Не удалось снять копию базы:\n{error}\n\n"
            "Если удалить сейчас, восстановить записи будет нечем.\n"
            "Удалить всё равно?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def logout_action(self):
        """Выход из системы: вернуться к окну входа, не закрывая программу."""
        reply = QMessageBox.question(
            self, 'Подтверждение выхода',
            'Вы действительно хотите выйти из системы?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.logout_requested.emit()

    def closeEvent(self, event):
        """Закрытие окна крестиком — это закрытие программы.

        Отличить его от закрытия при выходе из системы может только владелец
        окон: он один знает, что смена окон сейчас идёт.
        """
        super().closeEvent(event)
        self.closed.emit()


if __name__ == "__main__":
    print(
        "Точка входа приложения — main.py в корне проекта:\n"
        "  python main.py",
        file=sys.stderr,
    )
    raise SystemExit(1)
