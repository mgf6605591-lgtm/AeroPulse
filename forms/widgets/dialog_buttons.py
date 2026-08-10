# forms/widgets/dialog_buttons.py
"""Подписи стандартных кнопок диалога.

`QDialogButtonBox.button()` возвращает `None`, если такой кнопки в наборе нет, —
и пять мест в трёх диалогах вызывали `.setText()` прямо на результате. Пока
кнопку запрашивают ту же, что и создали, это работает; опечатка в константе дала
бы `AttributeError` при открытии окна, а заметить её было бы нечем (INFRA-7).

Здесь проверка одна на всех, и заодно исчезло само повторение.
"""
from PyQt6.QtWidgets import QDialogButtonBox


def set_caption(
    buttons: QDialogButtonBox, which: QDialogButtonBox.StandardButton, caption: str
) -> None:
    """Переименовывает стандартную кнопку. Кнопки нет в наборе — молча ничего."""
    button = buttons.button(which)
    if button is not None:
        button.setText(caption)
