"""
Вспомогательные функции
"""

from typing import Tuple, Callable, Dict, Any
from .models import ObjectStatus
from .errors import ErrorCollector

def get_layer_info(entity) -> Tuple[str, int]:
    """
    Извлечение информации о слое и цвете объекта
    
    Args:
        entity: Объект ezdxf
        
    Returns:
        Tuple[str, int]: (название слоя, код цвета)
    """
    try:
        layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
        color = entity.dxf.color if hasattr(entity.dxf, 'color') else 7
        return layer, color
    except Exception:
        return "0", 7

def calc_entity_safe(
    entity_type: str,
    entity: Any,
    real_num: int,
    calculators: Dict[str, Callable],
    collector: ErrorCollector
) -> Tuple[float, ObjectStatus, str]:
    """
    Безопасный расчёт длины объекта с обработкой ошибок
    
    Args:
        entity_type: Тип объекта
        entity: Сам объект ezdxf
        real_num: Реальный номер объекта в файле
        calculators: Словарь функций-калькуляторов
        collector: Коллектор ошибок
        
    Returns:
        Tuple[float, ObjectStatus, str]: (длина, статус, описание проблемы)
    """
    try:
        calculator = calculators.get(entity_type)
        if not calculator:
            return 0.0, ObjectStatus.SKIPPED, f"Нет калькулятора для {entity_type}"
        
        length = calculator(entity)
        
        if length < 0:
            collector.add_error(
                entity_type, real_num,
                f"Отрицательная длина: {length:.6f}",
                "NegativeLengthError"
            )
            return 0.0, ObjectStatus.ERROR, f"Отрицательная длина: {length:.6f}"
        
        return length, ObjectStatus.NORMAL, ""
        
    except AttributeError as e:
        collector.add_error(
            entity_type, real_num,
            f"Отсутствует атрибут: {e}",
            "AttributeError"
        )
        return 0.0, ObjectStatus.ERROR, f"Ошибка атрибута: {e}"
        
    except (ValueError, TypeError) as e:
        collector.add_error(
            entity_type, real_num,
            f"Ошибка расчёта: {e}",
            type(e).__name__
        )
        return 0.0, ObjectStatus.ERROR, f"Ошибка расчёта: {e}"
        
    except Exception as e:
        collector.add_error(
            entity_type, real_num,
            f"Неизвестная ошибка: {e}",
            type(e).__name__
        )
        return 0.0, ObjectStatus.ERROR, f"Неизвестная ошибка: {e}"