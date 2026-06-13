# services/parse_service.py
import xml.etree.ElementTree as ET
from parsers.xlsx_parser import XLSXParser
from parsers.xml_parser import XMLParser
from parsers.f15_xml_parser import F15XMLParser


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
        if file_path.endswith(('.xlsx', '.xls')):
            return XLSXParser.parse_file(
                file_path, 
                month=month, 
                year=year,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name
            )
        elif file_path.endswith('.xml'):
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
            return XMLParser.parse_file(
                file_path,
                month=month,
                year=year,
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
            )
        else:
            raise ValueError(f"Неподдерживаемый формат файла: {file_path}")