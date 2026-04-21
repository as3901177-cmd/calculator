"""
Управление ошибками и логированием
"""

from typing import List, Dict
from dataclasses import dataclass, field

@dataclass
class ErrorRecord:
    """Запись об ошибке/предупреждении"""
    entity_type: str
    entity_num: int
    message: str
    error_type: str = "Unknown"

class ErrorCollector:
    """Сборщик ошибок, предупреждений и информации"""
    
    def __init__(self):
        self.errors: List[ErrorRecord] = []
        self.warnings: List[ErrorRecord] = []
        self.skipped: List[ErrorRecord] = []
        self.info: List[ErrorRecord] = []
    
    def add_error(self, entity_type: str, num: int, msg: str, error_type: str = "Error"):
        """Добавить ошибку"""
        self.errors.append(ErrorRecord(entity_type, num, msg, error_type))
    
    def add_warning(self, entity_type: str, num: int, msg: str, error_type: str = "Warning"):
        """Добавить предупреждение"""
        self.warnings.append(ErrorRecord(entity_type, num, msg, error_type))
    
    def add_skipped(self, entity_type: str, num: int, msg: str):
        """Добавить пропущенный объект"""
        self.skipped.append(ErrorRecord(entity_type, num, msg, "Skipped"))
    
    def add_info(self, entity_type: str, num: int, msg: str):
        """Добавить информационное сообщение"""
        self.info.append(ErrorRecord(entity_type, num, msg, "Info"))
    
    @property
    def has_errors(self) -> bool:
        """Есть ли ошибки"""
        return len(self.errors) > 0
    
    @property
    def has_warnings(self) -> bool:
        """Есть ли предупреждения"""
        return len(self.warnings) > 0
    
    @property
    def total_issues(self) -> int:
        """Общее количество проблем"""
        return len(self.errors) + len(self.warnings) + len(self.skipped)
    
    def get_summary(self) -> Dict[str, int]:
        """Получить сводку"""
        return {
            'errors': len(self.errors),
            'warnings': len(self.warnings),
            'skipped': len(self.skipped),
            'info': len(self.info)
        }