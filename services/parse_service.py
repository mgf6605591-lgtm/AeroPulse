# services/parse_service.py
import xml.etree.ElementTree as ET
from pathlib import Path

from parsers.xlsx_parser import XLSXParser
from parsers.xml_parser import XMLParser
from parsers.f15_xml_parser import F15XMLParser
from parsers.f15_xlsx_parser import F15XLSXParser
from parsers.f15_fkp_xlsx_parser import F15FKPXLSXParser


class ParseService:
    """Сервис для парсинга файлов разных форматов"""

    @classmethod
    def parse_file(cls, file_path: str, month: str = None, year: int = None,
                   entity_type: str = None, entity_id: int = None, entity_name: str = None) -> dict:
        """
        Парсит файл и возвращает структурированные данные.
        
        Args:
            file_path: путь к файлу
            month: месяц (если не удалось определить из файла)
            year: год (если не удалось определить из файла)
            entity_type: тип предприятия ('airline' или 'airport')
            entity_id: ID предприятия из БД
            entity_name: название предприятия
            
        Returns:
            dict: структурированные данные для импорта
        """
        # Расширение сравнивается в нижнем регистре: Windows не различает регистр
        # в именах файлов, и присланный отчёт с «.XLSX» не открывался вовсе (BUG-6).
        suffix = Path(file_path).suffix.lower()
        if suffix in ('.xlsx', '.xls'):
            # Форма выбирается по содержимому книги, а не по тому, что указал
            # пользователь: раньше любой XLSX разбирался раскладкой 12-ГА, и бланк
            # аэропорта молча попадал в отчётность авиакомпании и наоборот (DATA-6).
            #
            # Сводный бланк предприятия проверяется первым: он тоже относится к
            # форме 15-ГА, но перечисляет её сразу по всем аэропортам, а разбор
            # одиночного бланка увидел бы в нём один отчёт с перепутанными
            # строками.
            parser = cls._xlsx_parser(file_path)
            return parser.parse_file(
                file_path,
                month=month,
                year=year,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name
            )
        elif suffix == '.xml':
            tree = ET.parse(file_path)
            root = tree.getroot()
            if F15XMLParser.is_meta_template_only(root):
                raise ValueError(
                    "Этот XML — шаблон метаданных формы 15-ГА (как f15.xml из справочника), "
                    "а не файл отчёта с данными. Используйте XML выгрузки отчёта с заполненными row/col."
                )
            if F15XMLParser.is_f15_data(root):
                return F15XMLParser._parse_root(
                    root,
                    month,
                    year,
                    entity_type,
                    entity_id,
                    entity_name,
                    file_path,
                )
            # Разобранный корень передаётся дальше, а не имя файла: форма уже
            # определена по нему, и повторный ET.parse читал бы и разбирал тот же
            # файл второй раз — ветка 15-ГА так не делала с самого начала (BUG-17).
            return XMLParser._parse_root(
                root,
                month,
                year,
                entity_type,
                entity_id,
                entity_name,
                file_path,
            )
        else:
            raise ValueError(f"Неподдерживаемый формат файла: {file_path}")

    @staticmethod
    def _xlsx_parser(file_path: str):
        """Разбор книги по её содержимому: сводный бланк 15-ГА, одиночный, иначе 12-ГА."""
        if F15FKPXLSXParser.is_fkp_workbook(file_path):
            return F15FKPXLSXParser
        if F15XLSXParser.is_f15_workbook(file_path):
            return F15XLSXParser
        return XLSXParser