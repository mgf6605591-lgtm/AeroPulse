import logging
import os
import sys

from utils.qt_plugins import ensure_qt_platform_plugins

ensure_qt_platform_plugins()

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox
from db.database import init_db
from forms.app_controller import AppController
from forms.widgets.account_dialogs import ensure_initial_admin
from utils.logging_setup import log_path, setup_logging
from utils.paths import get_app_dir, migrate_legacy_data_dir, resource_path

log = logging.getLogger(__name__)


def main():
    # Рабочая директория = каталог exe (PyInstaller) или корень проекта (разработка).
    try:
        os.chdir(get_app_dir())
    except OSError:
        pass

    # Данные переезжают из каталога программы прежде, чем журнал и база откроют
    # там свои файлы: перенос застал бы их занятыми, а на Windows занятый файл
    # не переименовать.
    moved, move_error = _relocate_user_data()

    written_to = setup_logging()
    log.info("Запуск приложения; журнал: %s", written_to or "только вывод")
    if moved:
        log.info("Данные перенесены в каталог пользователя: %s", ", ".join(moved))
    if move_error is not None:
        log.error("Не удалось перенести данные в каталог пользователя",
                  exc_info=move_error)

    # QApplication создаётся до обращения к базе. Прежде init_db() шёл первым, и
    # любая его неудача — повреждённая база, нет прав на запись рядом с exe,
    # упавшая миграция — оставляла пользователя без единого сообщения: показать
    # его было нечем, а трейсбек уходил в несуществующий stdout (BUG-15).
    app = QApplication(sys.argv)
    # Иконка задаётся явно, а не берётся из ресурсов exe: при запуске из
    # исходников ресурсов нет, и окно осталось бы с заглушкой Qt.
    app.setWindowIcon(QIcon(str(resource_path("assets", "AeroPulse.ico"))))
    # Смена окна входа на главное и обратно проходит через момент, когда открытых
    # окон нет. С поведением по умолчанию приложение в этот момент завершалось бы,
    # и переход держался бы лишь на том, что новое окно успевает появиться.
    # Закрывается программа теперь там, где это решено явно — в AppController.
    app.setQuitOnLastWindowClosed(False)

    # Запуск с неперенесённой базой опаснее, чем отказ запускаться: программа
    # завела бы в новом каталоге пустую базу, и для пользователя это выглядит
    # как потеря всей отчётности, хотя прежняя лежит на месте.
    if move_error is not None:
        _show_startup_failure(
            "Не удалось перенести данные в каталог пользователя.\n"
            "Программа не запущена, чтобы не начать работу с пустой базой, "
            "пока прежняя лежит рядом с программой.",
            move_error,
            written_to,
        )
        sys.exit(1)

    try:
        init_db()
    except Exception as error:
        log.exception("Не удалось подготовить базу данных")
        _show_startup_failure("Не удалось подготовить базу данных.", error, written_to)
        sys.exit(1)

    # Пустая база — первый запуск: администратора заводит пользователь. Учётной
    # записи по умолчанию больше нет, входить в форму входа не с чем (SEC-2).
    if not ensure_initial_admin():
        log.info("Первичная настройка отменена пользователем")
        sys.exit(0)

    controller = AppController(app)
    # Окно входа собирается из auth.ui, и файла может не оказаться на месте:
    # в сборке PyInstaller разметка либо попала в бандл, либо нет. Без этой
    # ветки такой запуск выглядел бы так же, как неудачная подготовка базы до
    # BUG-15, — ярлык нажат, не произошло ничего (BUG-18).
    try:
        controller.start()
    except Exception as error:
        log.exception("Не удалось открыть окно входа")
        _show_startup_failure("Не удалось открыть окно входа.", error, written_to)
        sys.exit(1)
    sys.exit(app.exec())


def _relocate_user_data() -> tuple[list[str], Exception | None]:
    """Переносит данные из каталога программы. Ошибку возвращает, а не поднимает.

    Показать её здесь нечем: `QApplication` ещё не создан, а журнал ещё не
    настроен — он и сам живёт в том каталоге, который этот перенос заканчивает.
    Поэтому решение о том, что делать с неудачей, принимается выше.
    """
    try:
        return migrate_legacy_data_dir(), None
    except OSError as error:
        return [], error


def _show_startup_failure(what: str, error: Exception, written_to) -> None:
    """Сообщение о том, почему программа не запустилась.

    Текст называет причину и место журнала: без этого установка у пользователя
    выглядит как «нажал на ярлык, ничего не произошло».
    """
    where = str(written_to or log_path())
    QMessageBox.critical(
        None,
        "Не удалось запустить программу",
        f"{what}\n\n"
        f"{error}\n\n"
        f"Подробности записаны в журнал:\n{where}",
    )


if __name__ == "__main__":
    main()
