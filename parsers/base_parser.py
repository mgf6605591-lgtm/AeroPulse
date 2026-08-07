class BaseParser:
    @classmethod
    def parse_file(cls, file_name: str) -> dict:
        raise NotImplementedError
