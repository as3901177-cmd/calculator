from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Dict, List, Any

class ErrorSeverity(Enum):
    ERROR = "🔴 Ошибка"
    WARNING = "🟡 Предупреждение"
    SKIPPED = "⚪ Пропущен"
    INFO = "🔵 Информация"

class ObjectStatus(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"

@dataclass
class DXFObject:
    num: int
    real_num: int
    entity_type: str
    length: float
    center: Tuple[float, float]
    entity: Any = None
    layer: str = ""
    color: int = 256
    original_color: int = 256
    status: ObjectStatus = ObjectStatus.NORMAL
    original_length: float = 0.0
    issue_description: str = ""
    is_closed: bool = False
    chain_id: int = -1

@dataclass
class ProcessingIssue:
    entity_type: str
    entity_num: int
    description: str
    error_class: str = ""
    severity: ErrorSeverity = ErrorSeverity.ERROR
    
    def to_dict(self) -> Dict[str, str]:
        return {
            'Тип объекта': self.entity_type,
            '№ объекта': self.entity_num,
            'Описание': self.description,
            'Класс ошибки': self.error_class,
            'Серьёзность': self.severity.value
        }