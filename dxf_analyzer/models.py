"""
Модели данных
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, Any

class ObjectStatus(Enum):
    """Статусы объектов"""
    NORMAL = "normal"           # Нормальный объект
    WARNING = "warning"         # Предупреждение (объект учтён с коррекцией)
    ERROR = "error"             # Ошибка (объект исключён)
    SKIPPED = "skipped"         # Пропущен

@dataclass
class DXFObject:
    """Класс для хранения информации об объекте DXF"""
    num: int                              # Порядковый номер в обработке
    real_num: int                         # Реальный номер в файле
    entity_type: str                      # Тип объекта (LINE, ARC и т.д.)
    length: float                         # Длина объекта
    center: Optional[Tuple[float, float]] # Центр объекта (x, y)
    entity: Any                           # Ссылка на сам объект ezdxf
    layer: str                            # Слой
    color: int                            # Цвет (ACI код)
    original_color: int                   # Исходный цвет
    status: ObjectStatus                  # Статус объекта
    original_length: float                # Исходная длина (до коррекции)
    issue_description: Optional[str]      # Описание проблемы
    is_closed: bool = False               # Замкнут ли объект
    chain_id: int = -1                    # ID цепи (-1 = не назначен)
    
    def __post_init__(self):
        """Валидация данных"""
        if self.length < 0:
            raise ValueError(f"Длина не может быть отрицательной: {self.length}")
        if not isinstance(self.status, ObjectStatus):
            raise TypeError(f"status должен быть ObjectStatus, получен {type(self.status)}")