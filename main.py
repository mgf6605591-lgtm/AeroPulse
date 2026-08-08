import logging
import os
import sys

from utils.qt_plugins import ensure_qt_platform_plugins

ensure_qt_platform_plugins()

from PyQt6.QtWidgets import QApplication, QMessageBox
from db.database import init_db
from forms.app_controller import AppController
from forms.widgets.account_dialogs import ensure_initial_admin
from utils.logging_setup import log_path, setup_logging
from utils.paths import get_app_dir

log = logging.getLogger(__name__)


def main():
    # Рабочая директория = каталог exe (PyInstaller) или корень проекта (разработка).
    try:
        os.chdir(get_app_dir())
    except OSError:
        pass

    written_to = setup_logging()
    log.info("Запуск приложения; журнал: %s", written_to or "только вывод")

    # QApplication создаётся до обращения к базе. Прежде init_db() шёл первым, и
    # любая его неудача — повреждённая база, нет прав на запись рядом с exe,
    # упавшая миграция — оставляла пользователя без единого сообщения: показать
    # его было нечем, а трейсбек уходил в несуществующий stdout (BUG-15).
    app = QApplication(sys.argv)
    # Смена окна входа на главное и обратно проходит через момент, когда открытых
    # окон нет. С поведением по умолчанию приложение в этот момент завершалось бы,
    # и переход держался бы лишь на том, что новое окно успевает появиться.
    # Закрывается программа теперь там, где это решено явно — в AppController.
    app.setQuitOnLastWindowClosed(False)

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
