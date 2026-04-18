import subprocess
import sys
import os
import math
import warnings
import logging
import io
import tempfile
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import streamlit as st
from functools import lru_cache
from typing import Tuple, Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ==================== АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ ====================
def install_dependencies():
    """Устанавливает необходимые библиотеки."""
    required = {
        'ezdxf': 'ezdxf>=1.3.0',
        'matplotlib': 'matplotlib>=3.8.0',
        'pandas': 'pandas>=2.2.0'
    }
    
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            print(f"📦 Установка {package}...")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", 
                package, "--no-cache-dir", "--quiet"
            ])

install_dependencies()

# ==================== ИМПОРТЫ ====================
try:
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
except ImportError as e:
    st.error(f"❌ Ошибка загрузки ezdxf: {e}")
    st.info("🔄 Попробуйте перезагрузить страницу")
    st.stop()

warnings.filterwarnings('ignore')

# ==================== КОНСТАНТЫ ====================
MAX_SPLINE_POINTS = 5000
SPLINE_FLATTENING = 0.01
MAX_LENGTH = 1_000_000
MIN_LENGTH = 1e-6
BULGE_EPSILON = 0.0001
COORD_EPSILON = 1e-10
ENTITY_COORD_PRECISION = 10  # Максимум 10 знаков после запятой
MAX_ENTITIES_PER_BLOCK = 10000  # Защита от слишком сложных блоков


# ==================== ENUM ДЛЯ ТИПОВ ОШИБОК ====================
class ErrorSeverity(Enum):
    """Уровни серьёзности ошибок."""
    ERROR = "🔴 Ошибка"
    WARNING = "🟡 Предупреждение"
    SKIPPED = "⚪ Пропущен"
    INFO = "🔵 Информация"


# ==================== DATACLASS ДЛЯ ОБЪЕКТА ====================
@dataclass
class DXFObject:
    """Представление объекта DXF с метаданными."""
    num: int  # Порядковый номер в спецификации (1, 2, 3...)
    real_num: int  # Реальный номер в файле (с учётом всех объектов)
    entity_type: str  # Тип: LINE, CIRCLE, ARC и т.д.
    length: float  # Длина в мм
    center: Tuple[float, float]  # (x, y)
    entity: Any = None  # Ссылка на объект ezdxf
    layer: str = ""  # Слой объекта
    color: int = 256  # Цвет (256 = By Layer)


# ==================== DATACLASS ДЛЯ ОШИБКИ ====================
@dataclass
class ProcessingIssue:
    """Представление проблемы при обработке."""
    entity_type: str
    entity_num: int
    description: str
    error_class: str = ""
    severity: ErrorSeverity = ErrorSeverity.ERROR
    
    def to_dict(self) -> Dict[str, str]:
        """Преобразование в словарь для DataFrame."""
        return {
            'Тип объекта': self.entity_type,
            '№ объекта': self.entity_num,
            'Описание': self.description,
            'Класс ошибки': self.error_class,
            'Серьёзность': self.severity.value
        }


# ==================== СБОР ОШИБОК ====================
class ErrorCollector:
    """
    Собирает ошибки во время обработки.
    Позволяет показать пользователю что именно не посчиталось.
    """
    
    def __init__(self):
        self.issues: List[ProcessingIssue] = []
    
    def add_issue(self, issue: ProcessingIssue):
        """Добавляет проблему."""
        self.issues.append(issue)
        
        # Логирование в зависимости от уровня серьёзности
        if issue.severity == ErrorSeverity.ERROR:
            logger.error(f"[{issue.entity_type}] #{issue.entity_num}: {issue.description}")
        elif issue.severity == ErrorSeverity.WARNING:
            logger.warning(f"[{issue.entity_type}] #{issue.entity_num}: {issue.description}")
        else:
            logger.info(f"[{issue.entity_type}] #{issue.entity_num}: {issue.description}")
    
    def add_error(self, entity_type: str, entity_num: int, error_msg: str, 
                  error_class: str = ""):
        """Добавляет критическую ошибку."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=error_msg,
            error_class=error_class,
            severity=ErrorSeverity.ERROR
        ))
    
    def add_warning(self, entity_type: str, entity_num: int, warning_msg: str, 
                    error_class: str = ""):
        """Добавляет предупреждение."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=warning_msg,
            error_class=error_class,
            severity=ErrorSeverity.WARNING
        ))
    
    def add_skipped(self, entity_type: str, entity_num: int, reason: str):
        """Добавляет пропущенный объект."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=reason,
            error_class="",
            severity=ErrorSeverity.SKIPPED
        ))
    
    def add_info(self, entity_type: str, entity_num: int, info_msg: str):
        """Добавляет информационное сообщение."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=info_msg,
            error_class="",
            severity=ErrorSeverity.INFO
        ))
    
    @property
    def errors(self) -> List[ProcessingIssue]:
        """Возвращает только ошибки."""
        return [i for i in self.issues if i.severity == ErrorSeverity.ERROR]
    
    @property
    def warnings(self) -> List[ProcessingIssue]:
        """Возвращает только предупреждения."""
        return [i for i in self.issues if i.severity == ErrorSeverity.WARNING]
    
    @property
    def skipped(self) -> List[ProcessingIssue]:
        """Возвращает только пропущённые."""
        return [i for i in self.issues if i.severity == ErrorSeverity.SKIPPED]
    
    @property
    def has_issues(self) -> bool:
        """Есть ли какие-либо проблемы."""
        return bool(self.issues)
    
    @property
    def has_errors(self) -> bool:
        """Есть ли критические ошибки."""
        return bool(self.errors)
    
    @property
    def total_issues(self) -> int:
        """Общее количество проблем."""
        return len(self.issues)
    
    def get_all_as_dataframe(self) -> pd.DataFrame:
        """Возвращает все проблемы единым DataFrame."""
        if not self.issues:
            return pd.DataFrame()
        
        return pd.DataFrame([issue.to_dict() for issue in self.issues])
    
    def get_summary(self) -> str:
        """Краткая сводка по проблемам."""
        parts = []
        if self.errors:
            parts.append(f"🔴 Ошибок: {len(self.errors)}")
        if self.warnings:
            parts.append(f"🟡 Предупреждений: {len(self.warnings)}")
        if self.skipped:
            parts.append(f"⚪ Пропущено: {len(self.skipped)}")
        return " | ".join(parts) if parts else "✅ Проблем не обнаружено"
    
    def get_summary_with_percent(self, total_objects: int) -> str:
        """Сводка с процентами от общего количества."""
        if total_objects == 0:
            return self.get_summary()
        
        parts = []
        if self.errors:
            pct = (len(self.errors) / total_objects) * 100
            parts.append(f"🔴 Ошибок: {len(self.errors)} ({pct:.1f}%)")
        if self.warnings:
            pct = (len(self.warnings) / total_objects) * 100
            parts.append(f"🟡 Предупреждений: {len(self.warnings)} ({pct:.1f}%)")
        if self.skipped:
            pct = (len(self.skipped) / total_objects) * 100
            parts.append(f"⚪ Пропущено: {len(self.skipped)} ({pct:.1f}%)")
        
        return " | ".join(parts) if parts else "✅ Проблем не обнаружено"


# ==================== УТИЛИТЫ ДЛЯ КООРДИНАТ ====================

def safe_float(value: Any) -> Optional[float]:
    """Безопасное преобразование в float."""
    try:
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    except (ValueError, TypeError, AttributeError):
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


# ==================== ВАЛИДАЦИЯ РЕЗУЛЬТАТОВ ====================

def validate_length_result(length: Any, entity_type: str, entity_num: int, 
                           collector: ErrorCollector) -> Tuple[float, bool]:
    """
    Проверяет корректность вычисленной длины.
    
    Returns:
        Tuple (валидная_длина, успех)
    """
    # Проверка на None
    if length is None:
        collector.add_error(
            entity_type, entity_num,
            "Функция вернула None вместо числа",
            "TypeError"
        )
        return 0.0, False
    
    # Проверка на число
    if not isinstance(length, (int, float)):
        collector.add_error(
            entity_type, entity_num,
            f"Некорректный тип результата: {type(length).__name__}",
            "TypeError"
        )
        return 0.0, False
    
    # Проверка на NaN
    try:
        if math.isnan(length):
            collector.add_error(
                entity_type, entity_num,
                "Результат вычисления: NaN (не число). "
                "Возможно повреждены координаты объекта",
                "ValueError"
            )
            return 0.0, False
    except (TypeError, ValueError):
        pass
    
    # Проверка на бесконечность
    try:
        if math.isinf(length):
            collector.add_error(
                entity_type, entity_num,
                "Результат вычисления: Infinity. "
                "Возможно деление на ноль в геометрии",
                "ZeroDivisionError"
            )
            return 0.0, False
    except (TypeError, ValueError):
        pass
    
    # Проверка на отрицательное значение
    if length < 0:
        collector.add_warning(
            entity_type, entity_num,
            f"Отрицательная длина: {length:.4f}. "
            f"Используется абсолютное значение",
            "GeometryWarning"
        )
        return abs(length), True
    
    # Проверка на аномально большое значение
    if length > MAX_LENGTH:
        collector.add_warning(
            entity_type, entity_num,
            f"Аномально большая длина: {length:.2f} мм ({length/1000:.1f} м). "
            f"Проверьте единицы измерения чертежа",
            "ScaleWarning"
        )
        return length, True
    
    return length, True


def calc_entity_safe(entity_type: str, entity: Any, entity_num: int, 
                     calculators: Dict, collector: ErrorCollector) -> float:
    """
    Безопасный вызов калькулятора с полным сбором ошибок.
    
    Returns:
        float: длина объекта (0.0 если ошибка)
    """
    if entity_type not in calculators:
        collector.add_skipped(
            entity_type, entity_num,
            f"Тип '{entity_type}' не поддерживается"
        )
        return 0.0
    
    try:
        # Вызов калькулятора
        raw_result = calculators[entity_type](entity)
        
        # Валидация результата
        validated_length, success = validate_length_result(
            raw_result, entity_type, entity_num, collector
        )
        
        return validated_length if success else 0.0
    
    except AttributeError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Отсутствует атрибут DXF: {e}. "
            f"Возможно файл создан в нестандартной программе",
            "AttributeError"
        )
        return 0.0
    
    except ZeroDivisionError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Деление на ноль при вычислении геометрии: {e}. "
            f"Объект может иметь нулевые размеры",
            "ZeroDivisionError"
        )
        return 0.0
    
    except ValueError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Некорректные числовые данные: {e}",
            "ValueError"
        )
        return 0.0
    
    except TypeError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Ошибка типа данных: {e}",
            "TypeError"
        )
        return 0.0
    
    except OverflowError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Переполнение числа при вычислении: {e}. "
            f"Слишком большие координаты",
            "OverflowError"
        )
        return 0.0
    
    except MemoryError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Недостаточно памяти для обработки объекта: {e}. "
            f"Возможно слишком сложный сплайн",
            "MemoryError"
        )
        return 0.0
    
    except RecursionError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Превышена глубина рекурсии: {e}. "
            f"Возможно циклическая ссылка в данных",
            "RecursionError"
        )
        return 0.0
    
    except Exception as e:
        collector.add_error(
            entity_type, entity_num,
            f"Неожиданная ошибка: {e}",
            type(e).__name__
        )
        return 0.0


# ==================== РАСЧЁТ ДЛИНЫ ====================

def calc_line_length(entity: Any) -> float:
    """LINE: прямая линия."""
    start = entity.dxf.start
    end = entity.dxf.end
    
    x1, y1 = safe_coordinate(start)
    x2, y2 = safe_coordinate(end)
    
    if None in (x1, y1, x2, y2):
        raise ValueError("Некорректные координаты линии")
    
    dx = x2 - x1
    dy = y2 - y1
    
    length = math.hypot(dx, dy)
    return length


def calc_circle_length(entity: Any) -> float:
    """CIRCLE: окружность."""
    radius = safe_float(entity.dxf.radius)
    
    if radius is None or radius <= 0:
        raise ValueError(f"Некорректный радиус окружности: {radius}")
    
    return 2 * math.pi * radius


def calc_arc_length(entity: Any) -> float:
    """ARC: дуга окружности."""
    radius = safe_float(entity.dxf.radius)
    
    if radius is None or radius <= 0:
        raise ValueError(f"Некорректный радиус дуги: {radius}")
    
    start_angle = safe_float(entity.dxf.start_angle)
    end_angle = safe_float(entity.dxf.end_angle)
    
    if start_angle is None or end_angle is None:
        raise ValueError("Некорректные углы дуги")
    
    start_angle = math.radians(start_angle)
    end_angle = math.radians(end_angle)
    
    angle = end_angle - start_angle
    
    # Нормализуем угол (от 0 до 2π)
    while angle < 0:
        angle += 2 * math.pi
    while angle > 2 * math.pi:
        angle -= 2 * math.pi
    
    return radius * angle


def calc_ellipse_length(entity: Any) -> float:
    """ELLIPSE: эллипс или его дуга."""
    major_axis = entity.dxf.major_axis
    ratio = safe_float(entity.dxf.ratio)
    
    if ratio is None or ratio <= 0:
        raise ValueError(f"Некорректный ratio эллипса: {ratio}")
    
    if ratio > 1:
        raise ValueError(f"Некорректный ratio > 1: {ratio}. "
                        f"Minor axis не может быть больше major axis")
    
    start_param = safe_float(entity.dxf.start_param)
    end_param = safe_float(entity.dxf.end_param)
    
    if start_param is None or end_param is None:
        raise ValueError("Некорректные параметры эллипса")
    
    # Вычисляем полуоси
    try:
        mx = safe_float(major_axis.x)
        my = safe_float(major_axis.y)
        mz = safe_float(major_axis.z)
        
        if None in (mx, my, mz):
            raise ValueError("Некорректные компоненты major_axis")
        
        a = math.sqrt(mx**2 + my**2 + mz**2)
    except (AttributeError, TypeError, ValueError) as e:
        raise ValueError(f"Ошибка чтения major_axis: {e}")
    
    if a <= 0:
        raise ValueError(f"Некорректная длина major_axis: {a}")
    
    b = a * ratio
    
    if b <= 0:
        raise ValueError(f"Некорректная длина minor_axis: {b}")
    
    # Вычисляем угловой размер
    angle_span = end_param - start_param
    
    # Нормализуем угол
    while angle_span < 0:
        angle_span += 2 * math.pi
    while angle_span > 2 * math.pi:
        angle_span -= 2 * math.pi
    
    # Проверка на нулевую дугу
    if angle_span < 1e-6:
        return 0.0
    
    # ИСПРАВЛЕНИЕ: Проверка на полный эллипс с допуском
    if abs(angle_span - 2 * math.pi) < 0.01:
        # Формула Рамануджана для периметра эллипса
        h = ((a - b) ** 2) / ((a + b) ** 2)
        perimeter = math.pi * (a + b) * (1 + 3*h / (10 + math.sqrt(4 - 3*h)))
        return perimeter
    
    # Численная интеграция для дуги эллипса
    N = min(1000, max(100, int(angle_span * 100)))  # Адаптивное количество шагов
    length = 0.0
    
    for i in range(N):
        t1 = start_param + angle_span * i / N
        t2 = start_param + angle_span * (i + 1) / N
        
        x1 = a * math.cos(t1)
        y1 = b * math.sin(t1)
        x2 = a * math.cos(t2)
        y2 = b * math.sin(t2)
        
        segment_length = math.hypot(x2 - x1, y2 - y1)
        length += segment_length
    
    return length


def calc_lwpolyline_length(entity: Any) -> float:
    """LWPOLYLINE: лёгкая полилиния с bulge (ИСПРАВЛЕННАЯ)."""
    points = []
    try:
        with entity.points('xyb') as pts:
            for p in pts:
                points.append(p)
    except (AttributeError, TypeError, ValueError) as e:
        raise ValueError(f"Ошибка чтения точек полилинии: {e}")
    
    if len(points) < 2:
        return 0.0
    
    length = 0.0
    is_closed = entity.is_closed if hasattr(entity, 'is_closed') else entity.dxf.flags & 1
    
    # ИСПРАВЛЕНИЕ: Правильное определение количества сегментов
    num_segments = len(points) if is_closed else len(points) - 1
    
    for i in range(num_segments):
        curr_idx = i
        next_idx = (i + 1) % len(points) if is_closed else i + 1
        
        try:
            x1 = safe_float(points[curr_idx][0])
            y1 = safe_float(points[curr_idx][1])
            x2 = safe_float(points[next_idx][0])
            y2 = safe_float(points[next_idx][1])
            
            if None in (x1, y1, x2, y2):
                continue
            
            bulge = safe_float(points[curr_idx][2]) if len(points[curr_idx]) >= 3 else 0.0
            if bulge is None:
                bulge = 0.0
        
        except (IndexError, TypeError, ValueError):
            continue
        
        chord = math.hypot(x2 - x1, y2 - y1)
        
        # Пропускаем слишком короткие отрезки
        if chord < COORD_EPSILON:
            continue
        
        # ИСПРАВЛЕНИЕ: Если булж близко к нулю, это прямая линия
        if abs(bulge) < BULGE_EPSILON:
            length += chord
        else:
            # ИСПРАВЛЕНИЕ: Правильная формула для булжа
            # angle = 4 * atan(bulge), где bulge = sin(angle/2) / cos(angle/2)
            # Максимальное значение angle при |bulge| -> ∞ это π
            angle = 4 * math.atan(abs(bulge))
            
            # Защита от слишком больших углов
            if angle > math.pi:
                angle = math.pi
            
            sin_half = math.sin(angle / 2)
            
            # Защита от деления на ноль
            if abs(sin_half) < COORD_EPSILON:
                length += chord
            else:
                radius = chord / (2 * sin_half)
                arc_len = radius * angle
                
                # ИСПРАВЛЕНИЕ: Защита от аномальных значений
                # Дуга не может быть значительно больше хорды
                if arc_len > chord * 100 or not math.isfinite(arc_len):
                    # Используем хорду вместо аномальной дуги
                    length += chord
                else:
                    length += arc_len
    
    return length


def calc_polyline_length(entity: Any) -> float:
    """POLYLINE: полилиния (ИСПРАВЛЕННАЯ)."""
    points = []
    try:
        for p in entity.points():
            x = safe_float(p[0])
            y = safe_float(p[1])
            if x is not None and y is not None:
                points.append((x, y))
    except (ValueError, TypeError, IndexError) as e:
        raise ValueError(f"Ошибка чтения координат полилинии: {e}")
    
    if len(points) < 2:
        return 0.0
    
    length = 0.0
    
    # Суммируем отрезки между точками
    for i in range(len(points) - 1):
        dx = points[i+1][0] - points[i][0]
        dy = points[i+1][1] - points[i][1]
        length += math.hypot(dx, dy)
    
    # ИСПРАВЛЕНИЕ: Правильная проверка для замкнутой полилинии
    is_closed = entity.is_closed if hasattr(entity, 'is_closed') else entity.dxf.flags & 1
    
    if is_closed and len(points) >= 2:
        dx = points[0][0] - points[-1][0]
        dy = points[0][1] - points[-1][1]
        length += math.hypot(dx, dy)
    
    return length


def calc_spline_length(entity: Any) -> float:
    """SPLINE: сплайн (ИСПРАВЛЕННАЯ - без утечки памяти)."""
    try:
        # ИСПРАВЛЕНИЕ: Потребляем точки постепенно, не загружая всё в памяти
        points = []
        point_count = 0
        
        for pt in entity.flattening(SPLINE_FLATTENING):
            if point_count >= MAX_SPLINE_POINTS:
                logger.warning(
                    f"Сплайн ограничен до {MAX_SPLINE_POINTS} точек для защиты памяти"
                )
                break
            
            try:
                x = safe_float(pt[0])
                y = safe_float(pt[1])
                
                if x is not None and y is not None:
                    points.append((x, y))
                    point_count += 1
            except (IndexError, TypeError, ValueError):
                continue
    
    except MemoryError as e:
        raise MemoryError(f"Не достаточно памяти для аппроксимации сплайна: {e}")
    except Exception as e:
        raise ValueError(f"Ошибка при чтении сплайна: {e}")
    
    if len(points) < 2:
        return 0.0
    
    length = 0.0
    for i in range(len(points) - 1):
        dx = points[i+1][0] - points[i][0]
        dy = points[i+1][1] - points[i][1]
        length += math.hypot(dx, dy)
    
    return length


def calc_point_length(entity: Any) -> float:
    """POINT: точка."""
    return 0.0


def calc_mline_length(entity: Any) -> float:
    """MLINE: мультилиния."""
    return 0.0


def calc_insert_length(entity: Any) -> float:
    """INSERT: блок (не обрабатывается на этом уровне)."""
    return 0.0


def calc_text_length(entity: Any) -> float:
    """TEXT: текст."""
    return 0.0


def calc_attrib_length(entity: Any) -> float:
    """ATTRIB: атрибут блока."""
    return 0.0


# ==================== СЛОВАРЬ КАЛЬКУЛЯТОРОВ ====================
calculators = {
    'LINE':       calc_line_length,
    'CIRCLE':     calc_circle_length,
    'ARC':        calc_arc_length,
    'ELLIPSE':    calc_ellipse_length,
    'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE':   calc_polyline_length,
    'SPLINE':     calc_spline_length,
    'POINT':      calc_point_length,
    'MLINE':      calc_mline_length,
    'INSERT':     calc_insert_length,
    'TEXT':       calc_text_length,
    'ATTRIB':     calc_attrib_length,
}

# Типы, которые имеют нулевую длину
ZERO_LENGTH_TYPES = {'POINT', 'MLINE', 'INSERT', 'TEXT', 'ATTRIB', 'DIMENSION'}

# Типы, которые нужно пропустить без предупреждения
SILENT_SKIP_TYPES = {'DIMENSION', 'VIEWPORT', 'LAYOUT', 'BLOCK'}


# ==================== ОПРЕДЕЛЕНИЕ ЦЕНТРА ОБЪЕКТА ====================

def get_entity_center(entity: Any) -> Tuple[float, float]:
    """
    Возвращает центр объекта БЕЗ смещения.
    
    Returns:
        tuple: (x, y) координаты центра или (0, 0) при ошибке
    """
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            x1, y1 = safe_coordinate(start)
            x2, y2 = safe_coordinate(end)
            
            if None in (x1, y1, x2, y2):
                return (0.0, 0.0)
            
            return ((x1 + x2) / 2, (y1 + y2) / 2)
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            x, y = safe_coordinate(center)
            return (x or 0.0, y or 0.0)
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            x, y = safe_coordinate(center)
            return (x or 0.0, y or 0.0)
        
        elif entity_type == 'ELLIPSE':
            center = entity.dxf.center
            x, y = safe_coordinate(center)
            return (x or 0.0, y or 0.0)
        
        elif entity_type == 'POINT':
            loc = entity.dxf.location
            x, y = safe_coordinate(loc)
            return (x or 0.0, y or 0.0)
        
        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
            if entity_type == 'LWPOLYLINE':
                with entity.points('xy') as pts:
                    points = []
                    for p in pts:
                        x, y = safe_float(p[0]), safe_float(p[1])
                        if x is not None and y is not None:
                            points.append((x, y))
            else:
                points = []
                for p in entity.points():
                    x, y = safe_float(p[0]), safe_float(p[1])
                    if x is not None and y is not None:
                        points.append((x, y))
            
            if len(points) >= 1:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            
            return (0.0, 0.0)
        
        elif entity_type == 'SPLINE':
            points = []
            for i, pt in enumerate(entity.flattening(0.1)):
                if i >= 1000:  # Ограничиваем для производительности
                    break
                x, y = safe_float(pt[0]), safe_float(pt[1])
                if x is not None and y is not None:
                    points.append((x, y))
            
            if len(points) >= 1:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            
            return (0.0, 0.0)
        
        elif entity_type == 'INSERT':
            pos = entity.dxf.insert
            x, y = safe_coordinate(pos)
            return (x or 0.0, y or 0.0)
    
    except Exception:
        return (0.0, 0.0)
    
    return (0.0, 0.0)


def get_entity_center_with_offset(entity: Any, offset_distance: float) -> Tuple[float, float]:
    """
    Возвращает центр объекта СО СМЕЩЕНИЕМ для маркеров.
    """
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            x1, y1 = safe_coordinate(start)
            x2, y2 = safe_coordinate(end)
            
            if None in (x1, y1, x2, y2):
                return (0.0, 0.0)
            
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2
            
            dx = x2 - x1
            dy = y2 - y1
            line_length = math.hypot(dx, dy)
            
            if line_length > COORD_EPSILON:
                perp_x = -dy / line_length
                perp_y = dx / line_length
                return (
                    center_x + perp_x * offset_distance,
                    center_y + perp_y * offset_distance
                )
            
            return (center_x, center_y)
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = safe_float(entity.dxf.radius)
            x, y = safe_coordinate(center)
            
            if x is None or y is None or radius is None:
                return (0.0, 0.0)
            
            return (x + radius + offset_distance, y)
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = safe_float(entity.dxf.radius)
            start_angle = safe_float(entity.dxf.start_angle)
            end_angle = safe_float(entity.dxf.end_angle)
            
            x, y = safe_coordinate(center)
            
            if any(v is None for v in (x, y, radius, start_angle, end_angle)):
                return (0.0, 0.0)
            
            start_angle = math.radians(start_angle)
            end_angle = math.radians(end_angle)
            
            mid_angle = (start_angle + end_angle) / 2
            if end_angle < start_angle:
                mid_angle += math.pi
            
            return (
                x + (radius + offset_distance) * math.cos(mid_angle),
                y + (radius + offset_distance) * math.sin(mid_angle)
            )
        
        elif entity_type == 'ELLIPSE':
            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            x, y = safe_coordinate(center)
            
            if x is None or y is None:
                return (0.0, 0.0)
            
            try:
                a = math.sqrt(
                    safe_float(major_axis.x)**2 + 
                    safe_float(major_axis.y)**2
                ) if (safe_float(major_axis.x) is not None and 
                      safe_float(major_axis.y) is not None) else 0
            except (AttributeError, TypeError, ValueError):
                a = 0
            
            if a <= 0:
                return (x, y)
            
            return (x + a + offset_distance, y)
        
        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
            center = get_entity_center(entity)
            
            if entity_type == 'LWPOLYLINE':
                with entity.points('xy') as pts:
                    points = [(safe_float(p[0]), safe_float(p[1])) for p in pts]
            else:
                points = [(safe_float(p[0]), safe_float(p[1])) for p in entity.points()]
            
            points = [(x, y) for x, y in points if x is not None and y is not None]
            
            if len(points) >= 2:
                dx = points[1][0] - points[0][0]
                dy = points[1][1] - points[0][1]
                seg_length = math.hypot(dx, dy)
                
                if seg_length > COORD_EPSILON:
                    perp_x = -dy / seg_length
                    perp_y = dx / seg_length
                    return (
                        center[0] + perp_x * offset_distance,
                        center[1] + perp_y * offset_distance
                    )
            
            return center
        
        elif entity_type == 'SPLINE':
            center = get_entity_center(entity)
            points = []
            
            for i, pt in enumerate(entity.flattening(0.1)):
                if i >= 500:
                    break
                x, y = safe_float(pt[0]), safe_float(pt[1])
                if x is not None and y is not None:
                    points.append((x, y))
            
            if len(points) >= 2:
                mid_idx = len(points) // 2
                dx = points[mid_idx + 1][0] - points[mid_idx][0]
                dy = points[mid_idx + 1][1] - points[mid_idx][1]
                seg_length = math.hypot(dx, dy)
                
                if seg_length > COORD_EPSILON:
                    perp_x = -dy / seg_length
                    perp_y = dx / seg_length
                    return (
                        center[0] + perp_x * offset_distance,
                        center[1] + perp_y * offset_distance
                    )
            
            return center
        
        elif entity_type == 'INSERT':
            pos = entity.dxf.insert
            x, y = safe_coordinate(pos)
            
            if x is None or y is None:
                return (0.0, 0.0)
            
            return (x + offset_distance, y + offset_distance)
    
    except Exception:
        return get_entity_center(entity)
    
    return (0.0, 0.0)


# ==================== ВИЗУАЛИЗАЦИЯ ====================

def draw_entity_manually(ax: Any, entity: Any) -> bool:
    """
    Рисует объект вручную ЧЁРНЫМ цветом.
    
    Returns:
        bool: успешность отрисовки
    """
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            x1, y1 = safe_coordinate(start)
            x2, y2 = safe_coordinate(end)
            
            if None not in (x1, y1, x2, y2):
                ax.plot([x1, x2], [y1, y2], 'k-', linewidth=1.5, zorder=1)
                return True
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = safe_float(entity.dxf.radius)
            x, y = safe_coordinate(center)
            
            if x is not None and y is not None and radius is not None and radius > 0:
                circle = plt.Circle(
                    (x, y), radius,
                    fill=False, edgecolor='black', linewidth=1.5, zorder=1
                )
                ax.add_patch(circle)
                return True
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = safe_float(entity.dxf.radius)
            start_angle = safe_float(entity.dxf.start_angle)
            end_angle = safe_float(entity.dxf.end_angle)
            x, y = safe_coordinate(center)
            
            if any(v is None for v in (x, y, radius, start_angle, end_angle)):
                return False
            
            if end_angle > start_angle:
                theta = [
                    start_angle + i * (end_angle - start_angle) / 50
                    for i in range(51)
                ]
            else:
                theta = [
                    start_angle + i * (360 + end_angle - start_angle) / 50
                    for i in range(51)
                ]
            
            xs = [x + radius * math.cos(math.radians(t)) for t in theta]
            ys = [y + radius * math.sin(math.radians(t)) for t in theta]
            ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
            return True
        
        elif entity_type == 'LWPOLYLINE':
            with entity.points('xy') as points:
                pts = [(safe_float(p[0]), safe_float(p[1])) for p in points]
                pts = [(x, y) for x, y in pts if x is not None and y is not None]
                
                if len(pts) >= 2:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    
                    if entity.is_closed:
                        xs.append(xs[0])
                        ys.append(ys[0])
                    
                    ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
                    return True
        
        elif entity_type == 'POLYLINE':
            points = [(safe_float(p[0]), safe_float(p[1])) for p in entity.points()]
            points = [(x, y) for x, y in points if x is not None and y is not None]
            
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                
                is_closed = entity.is_closed if hasattr(entity, 'is_closed') else entity.dxf.flags & 1
                
                if is_closed:
                    xs.append(xs[0])
                    ys.append(ys[0])
                
                ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
                return True
        
        elif entity_type == 'SPLINE':
            points = []
            for i, pt in enumerate(entity.flattening(0.01)):
                if i >= 5000:
                    break
                x, y = safe_float(pt[0]), safe_float(pt[1])
                if x is not None and y is not None:
                    points.append((x, y))
            
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
                return True
        
        elif entity_type == 'ELLIPSE':
            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            ratio = safe_float(entity.dxf.ratio)
            x, y = safe_coordinate(center)
            
            if x is None or y is None or ratio is None:
                return False
            
            try:
                a = math.sqrt(
                    safe_float(major_axis.x)**2 + safe_float(major_axis.y)**2
                )
                b = a * ratio
                angle = math.atan2(safe_float(major_axis.y), safe_float(major_axis.x))
                
                if a <= 0 or b <= 0:
                    return False
                
                t = [i * 2 * math.pi / 100 for i in range(101)]
                xs = [
                    x + a * math.cos(ti) * math.cos(angle)
                      - b * math.sin(ti) * math.sin(angle)
                    for ti in t
                ]
                ys = [
                    y + a * math.cos(ti) * math.sin(angle)
                      + b * math.sin(ti) * math.cos(angle)
                    for ti in t
                ]
                ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
                return True
            except (TypeError, ValueError):
                return False
    
    except Exception:
        return False
    
    return False


def visualize_dxf_with_numbers(doc: Any, objects_data: List[DXFObject], 
                                show_markers: bool = True,
                                font_size_multiplier: float = 1.0) -> Optional[Any]:
    """
    Создает визуализацию с номерами рядом с линиями.
    
    ИСПРАВЛЕНИЯ:
    - Использует ссылки на entity из DXFObject
    - Правильная привязка маркеров к объектам
    - Безопасная обработка координат
    
    Returns:
        matplotlib.figure.Figure или None при ошибке
    """
    try:
        fig, ax = plt.subplots(figsize=(18, 14), dpi=100)
        fig.patch.set_facecolor('#E5E5E5')
        ax.set_facecolor('#F0F0F0')
        
        msp = doc.modelspace()
        
        # Рисуем все объекты
        for entity in msp:
            draw_entity_manually(ax, entity)
        
        if show_markers and objects_data:
            # Получаем размеры чертежа
            valid_objects = [
                obj for obj in objects_data
                if obj.center[0] != 0 or obj.center[1] != 0
            ]
            
            if valid_objects:
                all_x = [obj.center[0] for obj in valid_objects]
                all_y = [obj.center[1] for obj in valid_objects]
                
                if all_x and all_y:
                    drawing_size = max(
                        max(all_x) - min(all_x),
                        max(all_y) - min(all_y)
                    )
                    
                    if drawing_size > 0:
                        base_font_size = max(int(drawing_size * 0.003), 7)
                        font_size = int(base_font_size * font_size_multiplier)
                        offset_distance = drawing_size * 0.015
                    else:
                        font_size = int(8 * font_size_multiplier)
                        offset_distance = 10
                else:
                    font_size = int(8 * font_size_multiplier)
                    offset_distance = 10
                
                # Рисуем маркеры ИСПОЛЬЗУЯ ССЫЛКИ НА ENTITY
                for obj in objects_data:
                    if obj.entity is None:
                        continue
                    
                    # ИСПРАВЛЕНИЕ: Используем entity из объекта напрямую
                    x, y = get_entity_center_with_offset(obj.entity, offset_distance)
                    
                    if x == 0 and y == 0:
                        continue
                    
                    ax.annotate(
                        str(obj.num),
                        (x, y),
                        fontsize=font_size,
                        fontweight='bold',
                        ha='center',
                        va='center',
                        color='white',
                        zorder=101,
                        bbox=dict(
                            boxstyle='circle,pad=0.35',
                            facecolor='#FF0000',
                            edgecolor='white',
                            linewidth=1.5,
                            alpha=0.95
                        )
                    )
        
        ax.set_aspect('equal')
        ax.autoscale()
        ax.margins(0.05)
        ax.axis('off')
        plt.tight_layout(pad=0.3)
        
        return fig
    
    except MemoryError:
        logger.error("Недостаточно памяти для визуализации")
        return None
    
    except Exception as e:
        logger.error(f"Ошибка визуализации: {e}")
        return None


# ==================== БЛОК ОТОБРАЖЕНИЯ ОШИБОК В UI ====================

def show_error_report(collector: ErrorCollector):
    """
    Показывает отчёт об ошибках в Streamlit UI.
    """
    if not collector.has_issues:
        st.success("✅ Обработка завершена без ошибок")
        return
    
    # Определяем цвет и иконку блока
    if collector.has_errors:
        st.error(
            f"⚠️ Обнаружены ошибки при обработке: "
            f"{collector.get_summary()}"
        )
    else:
        st.warning(
            f"⚠️ Обработка завершена с предупреждениями: "
            f"{collector.get_summary()}"
        )
    
    # Детальный отчёт в раскрывающемся блоке
    with st.expander(
        f"🔍 Подробный отчёт о проблемах ({collector.total_issues} записей)",
        expanded=False
    ):
        # Вкладки по типам проблем
        tab_labels = []
        
        if collector.errors:
            tab_labels.append(f"🔴 Ошибки ({len(collector.errors)})")
        if collector.warnings:
            tab_labels.append(f"🟡 Предупреждения ({len(collector.warnings)})")
        if collector.skipped:
            tab_labels.append(f"⚪ Пропущено ({len(collector.skipped)})")
        tab_labels.append("📋 Все проблемы")
        
        tabs = st.tabs(tab_labels)
        
        tab_idx = 0
        
        if collector.errors:
            with tabs[tab_idx]:
                st.markdown("**Критические ошибки** — объекты не учтены в расчёте:")
                df_errors = pd.DataFrame([issue.to_dict() for issue in collector.errors])
                st.dataframe(df_errors, use_container_width=True, hide_index=True)
                
                st.info(
                    "💡 Эти объекты исключены из итоговой длины реза. "
                    "Проверьте файл в CAD-редакторе."
                )
            tab_idx += 1
        
        if collector.warnings:
            with tabs[tab_idx]:
                st.markdown("**Предупреждения** — объекты обработаны с коррекцией:")
                df_warnings = pd.DataFrame([issue.to_dict() for issue in collector.warnings])
                st.dataframe(df_warnings, use_container_width=True, hide_index=True)
                
                st.info(
                    "💡 Эти объекты включены в расчёт, "
                    "но их значения были скорректированы."
                )
            tab_idx += 1
        
        if collector.skipped:
            with tabs[tab_idx]:
                st.markdown("**Пропущенные объекты** — не входят в расчёт:")
                df_skipped = pd.DataFrame([issue.to_dict() for issue in collector.skipped])
                st.dataframe(df_skipped, use_container_width=True, hide_index=True)
                
                st.info(
                    "💡 Эти типы объектов не поддерживаются "
                    "или имеют нулевую длину реза."
                )
            tab_idx += 1
        
        # Все проблемы вместе
        with tabs[tab_idx]:
            st.markdown("**Полный лог всех проблем:**")
            df_all = collector.get_all_as_dataframe()
            if not df_all.empty:
                st.dataframe(df_all, use_container_width=True, hide_index=True)
                
                # Скачать лог
                csv_log = df_all.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 Скачать лог ошибок (CSV)",
                    data=csv_log,
                    file_name="error_log.csv",
                    mime="text/csv"
                )
        
        # Влияние на результат
        if collector.has_errors:
            st.markdown("---")
            st.markdown("### 📊 Влияние на результат расчёта")
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric(
                    label="Объектов с ошибками",
                    value=len(collector.errors),
                    help="Эти объекты НЕ включены в итоговую длину"
                )
            with col2:
                st.metric(
                    label="Предупреждений",
                    value=len(collector.warnings),
                    help="Эти объекты включены с коррекцией значений"
                )
            
            st.warning(
                "⚠️ **Итоговая длина реза может быть занижена** "
                f"из-за {len(collector.errors)} объектов с ошибками. "
                "Рекомендуется проверить исходный файл."
            )


# ==================== STREAMLIT ИНТЕРФЕЙС ====================

st.set_page_config(
    page_title="Анализатор Чертежей CAD Pro v15.0",
    page_icon="📐",
    layout="wide"
)

st.title("📐 Анализатор Чертежей CAD Pro v15.0")
st.markdown("""
**Профессиональный расчет длины реза для станков ЧПУ и лазерной резки**  
Загрузите DXF-чертеж и получите точный анализ с визуализацией и детальной спецификацией.

### 🎯 Улучшения v15.0:
✅ **ИСПРАВЛЕНА нумерация** — теперь маркеры правильно привязаны к объектам  
✅ **Убрана утечка памяти** в обработке сплайнов  
✅ **Исправлена работа булжа** в полилиниях  
✅ **Добавлены типы данных** (dataclass, Enum) для надёжности  
✅ **Улучшена валидация эллипсов** и параметров  
✅ **Оптимизирована производительность** при больших чертежах  
""")

with st.expander("ℹ️ Поддерживаемые типы геометрии"):
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        **Базовые примитивы:**
        - LINE (отрезок)
        - CIRCLE (окружность)
        - ARC (дуга)
        - ELLIPSE (эллипс)
        """)
    with col2:
        st.markdown("""
        **Сложные контуры:**
        - LWPOLYLINE (легкая полилиния)
        - POLYLINE (полилиния)
        - SPLINE (сплайн)
        """)
    with col3:
        st.markdown("""
        **Прочие объекты:**
        - POINT (точки)
        - INSERT (блоки)
        - TEXT (текст)
        """)

st.markdown("---")

uploaded_file = st.file_uploader(
    "📂 Загрузите чертеж в формате DXF",
    type=["dxf"],
    help="Выберите файл DXF для расчета"
)

if uploaded_file is not None:
    with st.spinner('⏳ Обработка чертежа...'):
        
        # Инициализируем сборщик ошибок
        collector = ErrorCollector()
        
        try:
            # Безопасное создание временного файла
            with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
                tmp.write(uploaded_file.getbuffer())
                temp_path = tmp.name
            
            try:
                # Попытка чтения файла
                doc = ezdxf.readfile(temp_path)
                
                # Проверка версии DXF
                dxf_version = doc.dxfversion
                if dxf_version < 'AC1018':  # R2004
                    collector.add_warning(
                        'FILE', 0,
                        f"Старая версия DXF: {dxf_version}. "
                        f"Поддержка может быть ограничена",
                        "DXFVersionWarning"
                    )
                
                collector.add_info(
                    'FILE', 0,
                    f"Файл успешно загружен. Версия DXF: {dxf_version}"
                )
            
            except ezdxf.DXFError as e:
                collector.add_error(
                    'FILE', 0,
                    f"Ошибка чтения DXF файла: {e}. "
                    f"Файл может быть повреждён или иметь неподдерживаемую версию",
                    "DXFError"
                )
                show_error_report(collector)
                st.stop()
            except Exception as e:
                collector.add_error(
                    'FILE', 0,
                    f"Не удалось открыть файл: {e}",
                    type(e).__name__
                )
                show_error_report(collector)
                st.stop()
            finally:
                # Удаляем временный файл
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            
            msp = doc.modelspace()
            
            # ==================== АНАЛИЗ ОБЪЕКТОВ ====================
            
            # Собираем ВСЕ объекты один раз
            all_entities = list(msp)
            
            # Собираем нумерованные объекты для расчёта
            objects_data: List[DXFObject] = []
            stats: Dict[str, Dict[str, Any]] = {}
            total_length = 0.0
            skipped_types = set()
            
            # ИСПРАВЛЕНИЕ: Правильная нумерация
            real_object_num = 0  # Номер всех объектов в файле
            calc_object_num = 0  # Номер объектов для расчёта
            
            for entity in all_entities:
                entity_type = entity.dxftype()
                
                # Увеличиваем номер для ВСЕХ объектов
                real_object_num += 1
                
                # Получаем информацию о слое и цвете
                layer, color = get_layer_info(entity)
                
                # Проверяем, поддерживается ли тип
                if entity_type not in calculators:
                    if entity_type not in SILENT_SKIP_TYPES:
                        skipped_types.add(entity_type)
                    continue
                
                # Безопасный расчёт
                length = calc_entity_safe(
                    entity_type, entity, real_object_num, calculators, collector
                )
                
                # Пропускаем объекты с нулевой длиной (если это не ожидаемо)
                if length < MIN_LENGTH:
                    if entity_type not in ZERO_LENGTH_TYPES:
                        collector.add_skipped(
                            entity_type, real_object_num,
                            f"Нулевая или слишком малая длина: {length:.6f}"
                        )
                    continue
                
                # Увеличиваем номер для объектов расчёта
                calc_object_num += 1
                
                # Определяем центр объекта
                center = get_entity_center(entity)
                
                # Создаём объект данных
                dxf_obj = DXFObject(
                    num=calc_object_num,
                    real_num=real_object_num,
                    entity_type=entity_type,
                    length=length,
                    center=center,
                    entity=entity,  # ИСПРАВЛЕНИЕ: Сохраняем ссылку на entity!
                    layer=layer,
                    color=color
                )
                
                objects_data.append(dxf_obj)
                
                # Статистика по типам
                if entity_type not in stats:
                    stats[entity_type] = {
                        'count': 0,
                        'length': 0.0,
                        'items': []
                    }
                
                stats[entity_type]['count'] += 1
                stats[entity_type]['length'] += length
                stats[entity_type]['items'].append({
                    'num': calc_object_num,
                    'length': length
                })
                
                total_length += length
            
            # ==================== ВЫВОД РЕЗУЛЬТАТОВ ====================
            
            # Показываем отчёт об ошибках ПЕРВЫМ
            show_error_report(collector)
            
            if not objects_data:
                st.warning("⚠️ В чертеже не найдено объектов для расчета.")
                if skipped_types:
                    st.info(
                        f"Необрабатываемые типы: {', '.join(sorted(skipped_types))}"
                    )
            else:
                # Результирующее сообщение
                if collector.has_errors:
                    st.success(
                        f"✅ Обработано: **{len(objects_data)}** объектов "
                        f"(⚠️ {len(collector.errors)} исключены из-за ошибок, "
                        f"⚠️ {len(collector.warnings)} скорректированы)"
                    )
                else:
                    st.success(
                        f"✅ Успешно обработано: **{len(objects_data)}** объектов"
                    )
                
                # Итоговая длина
                st.markdown("### 📏 Итоговая длина реза:")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Миллиметры", f"{total_length:.2f}")
                with col2:
                    st.metric("Сантиметры", f"{total_length/10:.2f}")
                with col3:
                    st.metric("Метры", f"{total_length/1000:.4f}")
                with col4:
                    st.metric("Объектов", f"{len(objects_data)}")
                
                st.markdown("---")
                
                col_left, col_right = st.columns([1, 1.5])
                
                with col_left:
                    st.markdown("### 📊 Сводная спецификация")
                    
                    summary_rows = []
                    for entity_type in sorted(stats.keys()):
                        count = stats[entity_type]['count']
                        length = stats[entity_type]['length']
                        avg = length / count if count > 0 else 0
                        summary_rows.append({
                            'Тип': entity_type,
                            'Кол-во': count,
                            'Длина (мм)': round(length, 2),
                            'Средняя': round(avg, 2)
                        })
                    
                    df_summary = pd.DataFrame(summary_rows)
                    st.dataframe(
                        df_summary, use_container_width=True, hide_index=True
                    )
                    
                    if skipped_types:
                        st.caption(
                            f"⚠️ Пропущено: {', '.join(sorted(skipped_types))}"
                        )
                    
                    st.markdown("### 🔄 Повторяющиеся элементы")
                    length_groups: Dict[float, Dict] = {}
                    
                    for obj in objects_data:
                        key = round(obj.length, 1)
                        if key not in length_groups:
                            length_groups[key] = {
                                'type': obj.entity_type,
                                'nums': [],
                                'length': obj.length
                            }
                        length_groups[key]['nums'].append(obj.num)
                    
                    group_rows = []
                    for key in sorted(length_groups.keys(), reverse=True):
                        group = length_groups[key]
                        count = len(group['nums'])
                        if count > 1:
                            group_rows.append({
                                'Тип': group['type'],
                                'Размер': f"{group['length']:.2f} мм",
                                'Кол-во': count,
                                'Итого': f"{group['length']*count:.2f} мм"
                            })
                    
                    if group_rows:
                        df_groups = pd.DataFrame(group_rows)
                        st.dataframe(
                            df_groups, use_container_width=True, hide_index=True
                        )
                    else:
                        st.info("Повторяющихся элементов не обнаружено")
                
                with col_right:
                    st.markdown("### 🎨 Чертеж с маркировкой")
                    
                    control_col1, control_col2 = st.columns(2)
                    with control_col1:
                        show_markers = st.checkbox(
                            "🔴 Показать маркеры",
                            value=True
                        )
                    with control_col2:
                        font_size_multiplier = st.slider(
                            "📏 Размер шрифта маркеров",
                            min_value=0.5,
                            max_value=3.0,
                            value=1.0,
                            step=0.1,
                            disabled=not show_markers
                        )
                    
                    if show_markers:
                        st.caption("⬛ Черные линии | 🔴 Красные номера | Серый фон")
                    else:
                        st.caption("⬛ Только чертеж без маркировки")
                    
                    with st.spinner('Генерация визуализации...'):
                        fig = visualize_dxf_with_numbers(
                            doc, objects_data,
                            show_markers, font_size_multiplier
                        )
                        
                        if fig:
                            st.pyplot(fig, use_container_width=True)
                            plt.close(fig)
                        else:
                            st.error("❌ Не удалось создать визуализацию")
                
                # Детальная спецификация
                st.markdown("---")
                st.markdown("### 📋 Детальная спецификация")
                
                detail_rows = []
                for obj in objects_data:
                    detail_rows.append({
                        '№': obj.num,
                        'Тип': obj.entity_type,
                        'Длина (мм)': round(obj.length, 2),
                        'X': round(obj.center[0], 2),
                        'Y': round(obj.center[1], 2),
                        'Слой': obj.layer
                    })
                
                df_detail = pd.DataFrame(detail_rows)
                
                selected_types = st.multiselect(
                    "🔍 Фильтр по типу геометрии:",
                    options=sorted(stats.keys()),
                    default=sorted(stats.keys())
                )
                
                if selected_types:
                    df_filtered = df_detail[
                        df_detail['Тип'].isin(selected_types)
                    ]
                    st.dataframe(
                        df_filtered,
                        use_container_width=True,
                        hide_index=True,
                        height=400
                    )
                    
                    csv = df_filtered.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 Скачать спецификацию (CSV)",
                        data=csv,
                        file_name=f"specification_{uploaded_file.name}.csv",
                        mime="text/csv"
                    )
        
        except Exception as e:
            collector.add_error(
                'SYSTEM', 0,
                f"Критическая системная ошибка: {e}",
                type(e).__name__
            )
            show_error_report(collector)
            
            import traceback
            with st.expander("🔍 Трассировка ошибки (для разработчика)"):
                st.code(traceback.format_exc())

else:
    st.info("👈 Загрузите DXF-чертеж для начала анализа")
    st.markdown("""
    ### 🚀 Руководство пользователя:
    
    1. **Загрузите чертеж** в формате DXF
    2. **Получите анализ** с отчётом об ошибках
    3. **Настройте отображение** маркеров
    4. **Экспортируйте результаты** в CSV
    
    ### 📝 О версии v15.0:
    
    **КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ:**
    - ✅ Исправлена нумерация объектов — маркеры теперь правильно привязаны
    - ✅ Убрана утечка памяти при обработке сплайнов
    - ✅ Исправлен расчёт булжа в полилиниях
    - ✅ Добавлена проверка версии DXF
    - ✅ Улучшена обработка эллипсов с проверкой ratio
    
    **УЛУЧШЕНИЯ АРХИТЕКТУРЫ:**
    - ✅ Добавлены dataclass для структурирования данных
    - ✅ Использование Enum для уровней серьёзности ошибок
    - ✅ Функция safe_float() для безопасного преобразования чисел
    - ✅ Функция safe_coordinate() для безопасного извлечения координат
    - ✅ Правильная работа с entity через сохранённые ссылки
    
    **ОПТИМИЗАЦИЯ:**
    - ✅ Потоковая обработка сплайнов вместо загрузки в памяти
    - ✅ Ограничение количества точек для визуализации
    - ✅ Оптимизированная отрисовка маркеров
    """)

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; font-size: 12px;'>
    ✂️ CAD Analyzer Pro v15.0 | Полностью исправленная версия | 
    <a href='#' style='color: gray;'>Лицензия MIT</a>
</div>
""", unsafe_allow_html=True)
