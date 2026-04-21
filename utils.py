"""
Утилиты: работа с координатами, валидация результатов.
"""

import math
from typing import Any, Tuple, Optional, Dict
from .config import logger, MAX_LENGTH, COORD_EPSILON
from .models import ObjectStatus
from .errors import ErrorCollector


def safe_float(value: Any) -> Optional[float]:
    """Безопасное преобразование в float."""
    try:
        if isinstance(value, str):
            lower_val = value.lower().strip()
            if lower_val in ('inf', '+inf', '-inf', 'nan', 
                           'infinity', '+infinity', '-infinity'):
                return None
        
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            result = float(value)
        
        if not math.isfinite(result):
            return None
        
        return result
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def safe_coordinate(coord: Any) -> Tuple[Optional[float], Optional[float]]:
    """Безопасное извлечение (x, y) из координаты."""
    try:
        x = safe_float(coord.x)
        y = safe_float(coord.y)
        
        if x is None or y is None:
            return (None, None)
        
        return (x, y)
    except (AttributeError, TypeError):
        return (None, None)


def get_layer_info(entity: Any) -> Tuple[str, int]:
    """Получает слой и цвет объекта."""
    try:
        layer = str(entity.dxf.layer) if hasattr(entity.dxf, 'layer') else "0"
        color = int(entity.dxf.color) if hasattr(entity.dxf, 'color') else 256
        return layer, color
    except (AttributeError, ValueError, TypeError):
        return "0", 256


def check_is_closed(entity: Any) -> bool:
    """Проверяет, является ли объект замкнутым."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'CIRCLE':
            return True
        
        if entity_type == 'ELLIPSE':
            start_param = safe_float(entity.dxf.start_param)
            end_param = safe_float(entity.dxf.end_param)
            if start_param is not None and end_param is not None:
                angle_span = end_param - start_param
                while angle_span < 0:
                    angle_span += 2 * math.pi
                return abs(angle_span - 2 * math.pi) < 0.01
            return False
        
        if entity_type == 'LWPOLYLINE':
            return entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
        
        if entity_type == 'POLYLINE':
            if hasattr(entity, 'is_closed'):
                return entity.is_closed
            return bool(entity.dxf.flags & 0x01)
        
        if entity_type == 'SPLINE':
            try:
                points = []
                for i, pt in enumerate(entity.flattening(0.1)):
                    if i >= 500:
                        break
                    x, y = safe_float(pt[0]), safe_float(pt[1])
                    if x is not None and y is not None:
                        points.append((x, y))
                
                if len(points) >= 2:
                    first, last = points[0], points[-1]
                    if all(v is not None for v in (first[0], first[1], last[0], last[1])):
                        dist = math.hypot(last[0] - first[0], last[1] - first[1])
                        return dist < COORD_EPSILON
            except:
                pass
            return False
        
        return False
    
    except Exception as e:
        logger.debug(f"Ошибка проверки замкнутости для {entity_type}: {e}")
        return False


def validate_length_result(length: Any, entity_type: str, entity_num: int,
                           collector: ErrorCollector) -> Tuple[float, bool, str]:
    """
    Проверяет корректность вычисленной длины.
    
    Returns:
        Tuple (валидная_длина, успех, описание_проблемы)
    """
    if length is None:
        collector.add_error(entity_type, entity_num,
                          "Функция вернула None вместо числа", "TypeError")
        return 0.0, False, "TypeError: None returned"
    
    try:
        length_float = float(length)
    except (ValueError, TypeError, OverflowError):
        collector.add_error(entity_type, entity_num,
                          f"Некорректный тип результата: {type(length).__name__}",
                          "TypeError")
        return 0.0, False, f"TypeError: {type(length).__name__}"
    
    try:
        if math.isnan(length_float):
            collector.add_error(entity_type, entity_num,
                              "Результат вычисления: NaN", "ValueError")
            return 0.0, False, "ValueError: NaN result"
    except (TypeError, ValueError):
        pass
    
    try:
        if math.isinf(length_float):
            collector.add_error(entity_type, entity_num,
                              "Результат вычисления: Infinity", "ZeroDivisionError")
            return 0.0, False, "ZeroDivisionError: Infinity"
    except (TypeError, ValueError):
        pass
    
    if length_float < 0:
        collector.add_warning(entity_type, entity_num,
                            f"Отрицательная длина: {length_float:.4f}", "GeometryWarning")
        return abs(length_float), True, "GeometryWarning: Negative length corrected"
    
    if length_float > MAX_LENGTH:
        collector.add_warning(entity_type, entity_num,
                            f"Аномально большая длина: {length_float:.2f} мм", "ScaleWarning")
        return length_float, True, "ScaleWarning: Abnormally large value"
    
    return length_float, True, ""


def calc_entity_safe(entity_type: str, entity: Any, entity_num: int,
                     calculators: Dict, collector: ErrorCollector) -> Tuple[float, ObjectStatus, str]:
    """
    Безопасный вызов калькулятора с полным сбором ошибок.
    
    Returns:
        Tuple (длина, статус, описание_проблемы)
    """
    if entity_type not in calculators:
        collector.add_skipped(entity_type, entity_num,
                            f"Тип '{entity_type}' не поддерживается")
        return 0.0, ObjectStatus.SKIPPED, "Type not supported"
    
    error_handlers = {
        AttributeError: lambda e: (f"Отсутствует атрибут DXF: {e}", "AttributeError"),
        ZeroDivisionError: lambda e: (f"Деление на ноль: {e}", "ZeroDivisionError"),
        ValueError: lambda e: (f"Некорректные числовые данные: {e}", "ValueError"),
        TypeError: lambda e: (f"Ошибка типа данных: {e}", "TypeError"),
        OverflowError: lambda e: (f"Переполнение: {e}", "OverflowError"),
        MemoryError: lambda e: (f"Недостаточно памяти: {e}", "MemoryError"),
        RecursionError: lambda e: (f"Превышена глубина рекурсии: {e}", "RecursionError"),
    }
    
    try:
        raw_result = calculators[entity_type](entity)
        validated_length, success, issue_desc = validate_length_result(
            raw_result, entity_type, entity_num, collector
        )
        
        if not success:
            return 0.0, ObjectStatus.ERROR, issue_desc
        
        if issue_desc and "Warning" in issue_desc:
            return validated_length, ObjectStatus.WARNING, issue_desc
        
        return validated_length, ObjectStatus.NORMAL, ""
    
    except Exception as e:
        handler = error_handlers.get(type(e))
        if handler:
            msg, cls = handler(e)
        else:
            msg, cls = f"Неожиданная ошибка: {e}", type(e).__name__
        
        collector.add_error(entity_type, entity_num, msg, cls)
        return 0.0, ObjectStatus.ERROR, str(e)