from enum import Enum


class ParserType(Enum):
    XML = "xml"
    XLSX = "xlsx"


class BaseParser:
    @classmethod
    def parse_file(cls, file_name: str) -> dict:
        raise NotImplementedError
