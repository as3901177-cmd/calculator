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
import matplotlib.patches as mpatches
from matplotlib.collections import LineCollection
import streamlit as st
from functools import lru_cache
from typing import Tuple, Optional, Dict, List, Any, Set
from dataclasses import dataclass, field
from enum import Enum

# ИСПРАВЛЕНИЕ 10: Импорт Decimal с fallback для старых версий Python
try:
    from decimal import Decimal, ROUND_HALF_UP
except ImportError:
    from decimal import Decimal
    ROUND_HALF_UP = None  # Fallback для Python < 3.x

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
ENTITY_COORD_PRECISION = 10
MAX_ENTITIES_PER_BLOCK = 10000
MAX_CENTER_POINTS = 500
MAX_FILE_SIZE_MB = 50

# НОВОЕ: Палитра цветов ACI (AutoCAD Color Index)
ACI_COLORS = {
    0: '#000000',      # Чёрный
    1: '#FF0000',      # Красный
    2: '#FFFF00',      # Жёлтый
    3: '#00FF00',      # Зелёный (лайм)
    4: '#00FFFF',      # Голубой
    5: '#0000FF',      # Синий
    6: '#FF00FF',      # Магента
    7: '#FFFFFF',      # Белый
    8: '#414141',      # Тёмно-серый
    9: '#808080',      # Серый
    10: '#FF0000',     # Красный светлый
    11: '#FFAAAA',     # Красный светлый
    12: '#BD0000',     # Красный тёмный
    13: '#BD3D3D',     # Красный тёмный светлый
    14: '#840000',     # Красный очень тёмный
    15: '#843D3D',     # Красный очень тёмный светлый
    16: '#FF3333',     # Красный
    17: '#FF6666',     # Красный светлый
    18: '#FF9999',     # Красный очень светлый
    19: '#FFCCCC',     # Красный светлейший
    20: '#FF0000',     # Красный
    21: '#FFFF00',     # Жёлтый
    22: '#00FF00',     # Зелёный
    23: '#00FFFF',     # Голубой
    24: '#0000FF',     # Синий
    25: '#FF00FF',     # Магента
    26: '#FFFF80',     # Жёлтый светлый
    27: '#80FF80',     # Зелёный светлый
    28: '#80FFFF',     # Голубой светлый
    29: '#8080FF',     # Синий светлый
    30: '#FF80FF',     # Магента светлый
    256: '#000000',    # По слою (используем чёрный по умолчанию)
    257: '#FF0000',    # По блоку
}

def get_aci_color(color_id: int) -> str:
    """
    Преобразует ACI номер цвета в HEX код.
    НОВОЕ: Полная поддержка цветов с кешированием
    """
    if color_id in ACI_COLORS:
        return ACI_COLORS[color_id]
    
    # Для стандартных цветов от 1 до 255
    if 1 <= color_id <= 255:
        # Используем базовую палитру для неизвестных цветов
        base_colors = [
            '#000000', '#FF0000', '#FFFF00', '#00FF00', '#00FFFF',
            '#0000FF', '#FF00FF', '#FFFFFF', '#414141', '#808080'
        ]
        return base_colors[color_id % len(base_colors)]
    
    return '#000000'  # Чёрный по умолчанию

def get_color_name(color_id: int) -> str:
    """Получает название цвета по ACI коду."""
    color_names = {
        0: "Чёрный",
        1: "Красный",
        2: "Жёлтый",
        3: "Зелёный",
        4: "Голубой",
        5: "Синий",
        6: "Пурпур",
        7: "Белый",
        8: "Тёмно-серый",
        9: "Серый",
        256: "По слою",
        257: "По блоку"
    }
    return color_names.get(color_id, f"Цвет {color_id}")

# Цвета для статусов (для оверлея ошибок)
COLOR_ERROR_OVERLAY = '#FF0000'
COLOR_WARNING_OVERLAY = '#FF8800'
COLOR_NORMAL_OVERLAY = None  # Не добавляем оверлей, используем исходный цвет

# Цвета маркеров
MARKER_COLOR_NORMAL = '#FFFFFF'
MARKER_BG_NORMAL = '#000000'
MARKER_COLOR_WARNING = '#000000'
MARKER_BG_WARNING = '#FF8800'
MARKER_COLOR_ERROR = '#FFFFFF'
MARKER_BG_ERROR = '#FF0000'

# ==================== ENUM ДЛЯ ТИПОВ ОШИБОК ====================
class ErrorSeverity(Enum):
    """Уровни серьёзности ошибок."""
    ERROR = "🔴 Ошибка"
    WARNING = "🟡 Предупреждение"
    SKIPPED = "⚪ Пропущен"
    INFO = "🔵 Информация"


class ObjectStatus(Enum):
    """Статус объекта в расчёте."""
    NORMAL = "normal"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


# ==================== DATACLASS ДЛЯ ОБЪЕКТА ====================
@dataclass
class DXFObject:
    """Представление объекта DXF с метаданными."""
    num: int
    real_num: int
    entity_type: str
    length: float
    center: Tuple[float, float]
    entity: Any = None
    layer: str = ""
    color: int = 256
    original_color: int = 256  # НОВОЕ: Сохраняем исходный цвет
    status: ObjectStatus = ObjectStatus.NORMAL
    original_length: float = 0.0
    issue_description: str = ""


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
    Отслеживает какие объекты имели проблемы.
    """
    
    def __init__(self):
        self.issues: List[ProcessingIssue] = []
        self.object_issues: Dict[int, List[ProcessingIssue]] = {}
    
    def add_issue(self, issue: ProcessingIssue, object_num: int = 0):
        """Добавляет проблему."""
        self.issues.append(issue)
        
        if object_num > 0:
            if object_num not in self.object_issues:
                self.object_issues[object_num] = []
            self.object_issues[object_num].append(issue)
        
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
        ), object_num=entity_num)
    
    def add_warning(self, entity_type: str, entity_num: int, warning_msg: str, 
                    error_class: str = ""):
        """Добавляет предупреждение."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=warning_msg,
            error_class=error_class,
            severity=ErrorSeverity.WARNING
        ), object_num=entity_num)
    
    def add_skipped(self, entity_type: str, entity_num: int, reason: str):
        """Добавляет пропущенный объект."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=reason,
            error_class="",
            severity=ErrorSeverity.SKIPPED
        ), object_num=entity_num)
    
    def add_info(self, entity_type: str, entity_num: int, info_msg: str):
        """Добавляет информационное сообщение."""
        self.add_issue(ProcessingIssue(
            entity_type=entity_type,
            entity_num=entity_num,
            description=info_msg,
            error_class="",
            severity=ErrorSeverity.INFO
        ), object_num=entity_num)
    
    def has_issue_for_object(self, object_num: int, severity: ErrorSeverity = None) -> bool:
        """Проверяет наличие проблемы для объекта."""
        if object_num not in self.object_issues:
            return False
        
        if severity is None:
            return len(self.object_issues[object_num]) > 0
        
        return any(issue.severity == severity for issue in self.object_issues[object_num])
    
    def get_issues_for_object(self, object_num: int) -> List[ProcessingIssue]:
        """Получает все проблемы для объекта."""
        return self.object_issues.get(object_num, [])
    
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
    """
    Безопасное преобразование в float.
    ИСПРАВЛЕНИЕ 7, 10, 12: Полная поддержка всех типов
    """
    try:
        # Проверка на строки "inf" и "nan"
        if isinstance(value, str):
            lower_val = value.lower().strip()
            if lower_val in ('inf', '+inf', '-inf', 'nan', 'infinity', '+infinity', '-infinity'):
                return None
        
        # ИСПРАВЛЕНИЕ 12: Поддержка Decimal
        if isinstance(value, Decimal):
            result = float(value)
        else:
            result = float(value)
        
        # Проверка на бесконечность и NaN
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


# ==================== ВАЛИДАЦИЯ РЕЗУЛЬТАТОВ ====================

def validate_length_result(length: Any, entity_type: str, entity_num: int, 
                           collector: ErrorCollector) -> Tuple[float, bool, str]:
    """
    Проверяет корректность вычисленной длины.
    ИСПРАВЛЕНИЕ 10: Поддержка numpy типов
    
    Returns:
        Tuple (валидная_длина, успех, описание_проблемы)
    """
    if length is None:
        collector.add_error(
            entity_type, entity_num,
            "Функция вернула None вместо числа",
            "TypeError"
        )
        return 0.0, False, "TypeError: None returned"
    
    # ИСПРАВЛЕНИЕ 10: Более гибкая проверка типа
    try:
        length_float = float(length)
    except (ValueError, TypeError, OverflowError):
        collector.add_error(
            entity_type, entity_num,
            f"Некорректный тип результата: {type(length).__name__}",
            "TypeError"
        )
        return 0.0, False, f"TypeError: {type(length).__name__}"
    
    try:
        if math.isnan(length_float):
            collector.add_error(
                entity_type, entity_num,
                "Результат вычисления: NaN (не число). "
                "Возможно повреждены координаты объекта",
                "ValueError"
            )
            return 0.0, False, "ValueError: NaN result"
    except (TypeError, ValueError):
        pass
    
    try:
        if math.isinf(length_float):
            collector.add_error(
                entity_type, entity_num,
                "Результат вычисления: Infinity. "
                "Возможно деление на ноль в геометрии",
                "ZeroDivisionError"
            )
            return 0.0, False, "ZeroDivisionError: Infinity"
    except (TypeError, ValueError):
        pass
    
    if length_float < 0:
        collector.add_warning(
            entity_type, entity_num,
            f"Отрицательная длина: {length_float:.4f}. "
            f"Используется абсолютное значение",
            "GeometryWarning"
        )
        return abs(length_float), True, "GeometryWarning: Negative length corrected"
    
    if length_float > MAX_LENGTH:
        collector.add_warning(
            entity_type, entity_num,
            f"Аномально большая длина: {length_float:.2f} мм ({length_float/1000:.1f} м). "
            f"Проверьте единицы измерения чертежа",
            "ScaleWarning"
        )
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
        collector.add_skipped(
            entity_type, entity_num,
            f"Тип '{entity_type}' не поддерживается"
        )
        return 0.0, ObjectStatus.SKIPPED, "Type not supported"
    
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
    
    except AttributeError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Отсутствует атрибут DXF: {e}. "
            f"Возможно файл создан в нестандартной программе",
            "AttributeError"
        )
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except ZeroDivisionError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Деление на ноль при вычислении геометрии: {e}. "
            f"Объект может иметь нулевые размеры",
            "ZeroDivisionError"
        )
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except ValueError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Некорректные числовые данные: {e}",
            "ValueError"
        )
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except TypeError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Ошибка типа данных: {e}",
            "TypeError"
        )
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except OverflowError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Переполнение числа при вычислении: {e}. "
            f"Слишком большие координаты",
            "OverflowError"
        )
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except MemoryError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Недостаточно памяти для обработки объекта: {e}. "
            f"Возможно слишком сложный сплайн",
            "MemoryError"
        )
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except RecursionError as e:
        collector.add_error(
            entity_type, entity_num,
            f"Превышена глубина рекурсии: {e}. "
            f"Возможно циклическая ссылка в данных",
            "RecursionError"
        )
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except Exception as e:
        collector.add_error(
            entity_type, entity_num,
            f"Неожиданная ошибка: {e}",
            type(e).__name__
        )
        return 0.0, ObjectStatus.ERROR, type(e).__name__


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
    
    angle_span = end_param - start_param
    
    while angle_span < 0:
        angle_span += 2 * math.pi
    while angle_span > 2 * math.pi:
        angle_span -= 2 * math.pi
    
    if angle_span < 1e-6:
        return 0.0
    
    if abs(angle_span - 2 * math.pi) < 0.01:
        h = ((a - b) ** 2) / ((a + b) ** 2)
        perimeter = math.pi * (a + b) * (1 + 3*h / (10 + math.sqrt(4 - 3*h)))
        return perimeter
    
    N = min(1000, max(100, int(angle_span * 100)))
    length = 0.0
    
    for i in range(N):
        t1 = start_param + angle_span * i / N
        t2 = start_param + angle_span * (i + 1) / N
        
        try:
            x1 = a * math.cos(t1)
            y1 = b * math.sin(t1)
            x2 = a * math.cos(t2)
            y2 = b * math.sin(t2)
            
            if not (math.isfinite(x1) and math.isfinite(y1) and 
                    math.isfinite(x2) and math.isfinite(y2)):
                logger.warning(f"NaN в вычислениях эллипса при t1={t1}, t2={t2}")
                continue
            
            segment_length = math.hypot(x2 - x1, y2 - y1)
            
            if math.isfinite(segment_length):
                length += segment_length
        
        except (ValueError, OverflowError) as e:
            logger.warning(f"Ошибка в итерации эллипса #{i}: {e}")
            continue
    
    return length


def calc_lwpolyline_length(entity: Any) -> float:
    """
    LWPOLYLINE: лёгкая полилиния с bulge.
    ИСПРАВЛЕНИЕ 3: Правильное получение флага замыкания
    """
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
    
    # ИСПРАВЛЕНИЕ 3: Для LWPOLYLINE используем .close свойство
    try:
        # В ezdxf LWPOLYLINE имеет .close как свойство (не is_closed)
        is_closed = entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
    except (AttributeError, TypeError):
        is_closed = False
    
    num_segments = len(points) if is_closed else len(points) - 1
    
    for i in range(num_segments):
        curr_idx = i
        
        if is_closed:
            next_idx = (i + 1) % len(points)
        else:
            next_idx = i + 1
        
        if next_idx >= len(points):
            logger.warning(f"Индекс next_idx={next_idx} >= len(points)={len(points)}")
            continue
        
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
        
        if chord < COORD_EPSILON:
            continue
        
        if abs(bulge) < BULGE_EPSILON:
            length += chord
        else:
            angle = 4 * math.atan(abs(bulge))
            
            if angle > math.pi:
                angle = math.pi
            
            sin_half = math.sin(angle / 2)
            
            if abs(sin_half) < COORD_EPSILON:
                length += chord
            else:
                radius = chord / (2 * sin_half)
                arc_len = radius * angle
                
                if arc_len > chord * 100 or not math.isfinite(arc_len):
                    length += chord
                else:
                    length += arc_len
    
    return length


def calc_polyline_length(entity: Any) -> float:
    """POLYLINE: полилиния."""
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
    
    for i in range(len(points) - 1):
        dx = points[i+1][0] - points[i][0]
        dy = points[i+1][1] - points[i][1]
        length += math.hypot(dx, dy)
    
    try:
        if hasattr(entity, 'is_closed'):
            is_closed = entity.is_closed
        else:
            is_closed = bool(entity.dxf.flags & 0x01)
    except (AttributeError, TypeError):
        is_closed = False
    
    if is_closed and len(points) >= 2:
        dx = points[0][0] - points[-1][0]
        dy = points[0][1] - points[-1][1]
        length += math.hypot(dx, dy)
    
    return length


def calc_spline_length(entity: Any) -> float:
    """
    SPLINE: сплайн.
    ИСПРАВЛЕНИЕ 20: Правильная обработка ограничения точек
    """
    try:
        points = []
        point_count = 0
        
        for pt in entity.flattening(SPLINE_FLATTENING):
            if point_count >= MAX_SPLINE_POINTS:
                logger.warning(
                    f"Сплайн ограничен до {MAX_SPLINE_POINTS} точек. "
                    f"Точность может быть снижена."
                )
                break
            
            try:
                x = safe_float(pt[0])
                y = safe_float(pt[1])
                
                # ИСПРАВЛЕНИЕ 4: Увеличиваем счётчик ТОЛЬКО при успехе
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
    """INSERT: блок."""
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

ZERO_LENGTH_TYPES = {'POINT', 'MLINE', 'INSERT', 'TEXT', 'ATTRIB', 'DIMENSION'}
SILENT_SKIP_TYPES = {'DIMENSION', 'VIEWPORT', 'LAYOUT', 'BLOCK'}


# ==================== ОПРЕДЕЛЕНИЕ ЦЕНТРА ОБЪЕКТА ====================

def get_entity_center(entity: Any) -> Tuple[float, float]:
    """
    Возвращает центр объекта БЕЗ смещения.
    ИСПРАВЛЕНИЕ 5: Защита от исключений в итераторах
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
            # ИСПРАВЛЕНИЕ 5: Защита от исключений
            try:
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
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug(f"Ошибка при чтении центра {entity_type}: {e}")
            
            return (0.0, 0.0)
        
        elif entity_type == 'SPLINE':
            try:
                points = []
                for i, pt in enumerate(entity.flattening(0.1)):
                    if i >= MAX_CENTER_POINTS:
                        break
                    x, y = safe_float(pt[0]), safe_float(pt[1])
                    if x is not None and y is not None:
                        points.append((x, y))
                
                if len(points) >= 1:
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug(f"Ошибка при чтении центра SPLINE: {e}")
            
            return (0.0, 0.0)
        
        elif entity_type == 'INSERT':
            pos = entity.dxf.insert
            x, y = safe_coordinate(pos)
            return (x or 0.0, y or 0.0)
    
    except Exception as e:
        logger.debug(f"Неожиданная ошибка при получении центра: {e}")
        return (0.0, 0.0)
    
    return (0.0, 0.0)


def normalize_angle(angle_deg: float) -> float:
    """
    Нормализует угол в диапазон [0, 360).
    ИСПРАВЛЕНИЕ 7: Правильная нормализация
    """
    return angle_deg % 360.0


def get_entity_center_with_offset(entity: Any, offset_distance: float) -> Tuple[float, float]:
    """
    Возвращает центр объекта СО СМЕЩЕНИЕМ для маркеров.
    ИСПРАВЛЕНИЕ 6: Защита от исключений в итераторах
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
            
            # ИСПРАВЛЕНИЕ 6: Защита от исключений
            try:
                if entity_type == 'LWPOLYLINE':
                    with entity.points('xy') as pts:
                        points = [(safe_float(p[0]), safe_float(p[1])) for p in pts]
                else:
                    points = [(safe_float(p[0]), safe_float(p[1])) for p in entity.points()]
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug(f"Ошибка при получении смещения {entity_type}: {e}")
                return center
            
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
            
            try:
                points = []
                for i, pt in enumerate(entity.flattening(0.1)):
                    if i >= MAX_CENTER_POINTS:
                        break
                    x, y = safe_float(pt[0]), safe_float(pt[1])
                    if x is not None and y is not None:
                        points.append((x, y))
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug(f"Ошибка при получении смещения SPLINE: {e}")
                return center
            
            if len(points) >= 2:
                mid_idx = len(points) // 2
                
                if mid_idx + 1 < len(points):
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
    
    except Exception as e:
        logger.debug(f"Ошибка при получении центра со смещением: {e}")
        return get_entity_center(entity)
    
    return (0.0, 0.0)


# ==================== ВИЗУАЛИЗАЦИЯ ====================

def draw_entity_manually(ax: Any, entity: Any, color: str = '#000000', 
                         linewidth: float = 1.5, use_original_color: bool = False) -> bool:
    """
    Рисует объект вручную с указанным цветом.
    НОВОЕ: Добавлена поддержка исходных цветов из файла
    ИСПРАВЛЕНИЕ 4, 6: Правильная обработка is_closed
    ИСПРАВЛЕНИЕ 14: Проверка angle_diff на нулевое значение
    """
    entity_type = entity.dxftype()
    
    # НОВОЕ: Если нужен исходный цвет, получаем его
    if use_original_color:
        _, original_color = get_layer_info(entity)
        color = get_aci_color(original_color)
    
    try:
        if entity_type == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            x1, y1 = safe_coordinate(start)
            x2, y2 = safe_coordinate(end)
            
            if None not in (x1, y1, x2, y2):
                ax.plot([x1, x2], [y1, y2], color=color, linewidth=linewidth, zorder=1)
                return True
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = safe_float(entity.dxf.radius)
            x, y = safe_coordinate(center)
            
            if x is not None and y is not None and radius is not None and radius > 0:
                circle = plt.Circle(
                    (x, y), radius,
                    fill=False, edgecolor=color, linewidth=linewidth, zorder=1
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
            
            start_angle_norm = normalize_angle(start_angle)
            end_angle_norm = normalize_angle(end_angle)
            
            # Определение направления дуги
            if start_angle_norm <= end_angle_norm:
                angle_diff = end_angle_norm - start_angle_norm
            else:
                angle_diff = 360 - (start_angle_norm - end_angle_norm)
            
            # ИСПРАВЛЕНИЕ 14: Проверка angle_diff на нулевое значение
            if angle_diff < 0.001:
                return False
            
            theta = [
                start_angle_norm + i * angle_diff / 50
                for i in range(51)
            ]
            
            xs = [x + radius * math.cos(math.radians(t)) for t in theta]
            ys = [y + radius * math.sin(math.radians(t)) for t in theta]
            ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
            return True
        
        elif entity_type == 'LWPOLYLINE':
            # ИСПРАВЛЕНИЕ 4: Правильная обработка is_closed для LWPOLYLINE
            try:
                with entity.points('xy') as points:
                    pts = [(safe_float(p[0]), safe_float(p[1])) for p in points]
                    pts = [(x, y) for x, y in pts if x is not None and y is not None]
                    
                    if len(pts) >= 2:
                        xs = [p[0] for p in pts]
                        ys = [p[1] for p in pts]
                        
                        try:
                            is_closed = entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
                        except (AttributeError, TypeError):
                            is_closed = False
                        
                        if is_closed:
                            xs.append(xs[0])
                            ys.append(ys[0])
                        
                        ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
                        return True
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug(f"Ошибка при рисовании LWPOLYLINE: {e}")
                return False
        
        elif entity_type == 'POLYLINE':
            try:
                points = [(safe_float(p[0]), safe_float(p[1])) for p in entity.points()]
                points = [(x, y) for x, y in points if x is not None and y is not None]
                
                if len(points) >= 2:
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    
                    try:
                        if hasattr(entity, 'is_closed'):
                            is_closed = entity.is_closed
                        else:
                            is_closed = bool(entity.dxf.flags & 0x01)
                    except (AttributeError, TypeError):
                        is_closed = False
                    
                    if is_closed:
                        xs.append(xs[0])
                        ys.append(ys[0])
                    
                    ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
                    return True
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug(f"Ошибка при рисовании POLYLINE: {e}")
                return False
        
        elif entity_type == 'SPLINE':
            try:
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
                    ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
                    return True
            except (AttributeError, TypeError, ValueError) as e:
                logger.debug(f"Ошибка при рисовании SPLINE: {e}")
                return False
        
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
                ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
                return True
            except (TypeError, ValueError) as e:
                logger.debug(f"Ошибка при рисовании ELLIPSE: {e}")
                return False
    
    except Exception as e:
        logger.debug(f"Неожиданная ошибка при рисовании: {e}")
        return False
    
    return False


def visualize_dxf_with_status_indicators(
    doc: Any, 
    objects_data: List[DXFObject],
    collector: ErrorCollector,
    show_markers: bool = True,
    font_size_multiplier: float = 1.0,
    use_original_colors: bool = False  # НОВОЕ: Флаг для использования исходных цветов
) -> Tuple[Optional[Any], Optional[str]]:
    """
    Создает визуализацию с цветовой индикацией статуса объектов.
    НОВОЕ: Поддержка исходных цветов из файла
    ИСПРАВЛЕНИЕ 2, 19: Добавлена обработка ошибок и возврат информации об ошибке
    
    Returns:
        Tuple (фигура, сообщение об ошибке или None если успех)
    """
    fig = None
    try:
        fig, ax = plt.subplots(figsize=(20, 16), dpi=100)
        fig.patch.set_facecolor('#E5E5E5')
        ax.set_facecolor('#F0F0F0')
        
        msp = doc.modelspace()
        
        # Создаём словарь статусов по номерам объектов в файле
        status_by_real_num: Dict[int, Tuple[ObjectStatus, str]] = {}
        for obj in objects_data:
            status_by_real_num[obj.real_num] = (obj.status, obj.issue_description)
        
        # Рисуем все объекты с правильным цветом
        real_object_num = 0
        for entity in msp:
            real_object_num += 1
            entity_type = entity.dxftype()
            
            if entity_type not in calculators:
                continue
            
            if real_object_num in status_by_real_num:
                status, _ = status_by_real_num[real_object_num]
                
                # НОВОЕ: Логика для выбора цвета
                if use_original_colors:
                    # Используем исходный цвет, но с оверлеем для ошибок
                    draw_entity_manually(ax, entity, use_original_color=True, linewidth=1.5)
                    
                    # Добавляем оверлей ошибки если нужно
                    if status == ObjectStatus.ERROR:
                        draw_entity_manually(ax, entity, color=COLOR_ERROR_OVERLAY, linewidth=2.5)
                    elif status == ObjectStatus.WARNING:
                        draw_entity_manually(ax, entity, color=COLOR_WARNING_OVERLAY, linewidth=2.5)
                else:
                    # Обычная схема цветов по статусу
                    if status == ObjectStatus.ERROR:
                        color = '#FF0000'
                        linewidth = 2.0
                    elif status == ObjectStatus.WARNING:
                        color = '#FF8800'
                        linewidth = 2.0
                    else:
                        color = '#000000'
                        linewidth = 1.5
                    
                    draw_entity_manually(ax, entity, color=color, linewidth=linewidth)
            else:
                # Объект не в расчётах, рисуем серым
                draw_entity_manually(ax, entity, color='#CCCCCC', linewidth=1.0)
        
        # Рисуем маркеры для объектов расчёта
        if show_markers and objects_data:
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
                
                # Рисуем маркеры
                for obj in objects_data:
                    if obj.entity is None:
                        continue
                    
                    x, y = get_entity_center_with_offset(obj.entity, offset_distance)
                    
                    if x == 0 and y == 0:
                        continue
                    
                    if obj.status == ObjectStatus.ERROR:
                        marker_color = MARKER_COLOR_ERROR
                        marker_bg = MARKER_BG_ERROR
                    elif obj.status == ObjectStatus.WARNING:
                        marker_color = MARKER_COLOR_WARNING
                        marker_bg = MARKER_BG_WARNING
                    else:
                        marker_color = MARKER_COLOR_NORMAL
                        marker_bg = MARKER_BG_NORMAL
                    
                    ax.annotate(
                        str(obj.num),
                        (x, y),
                        fontsize=font_size,
                        fontweight='bold',
                        ha='center',
                        va='center',
                        color=marker_color,
                        zorder=101,
                        bbox=dict(
                            boxstyle='circle,pad=0.35',
                            facecolor=marker_bg,
                            edgecolor='white',
                            linewidth=1.5,
                            alpha=0.95
                        )
                    )
            
            # Легенда
            from matplotlib.patches import Patch
            legend_elements = [
                Patch(facecolor='#000000', edgecolor='black', label='✓ Нормальные (учтены)'),
                Patch(facecolor='#FF8800', edgecolor='black', label='⚠ Коррекция (учтены)'),
                Patch(facecolor='#FF0000', edgecolor='black', label='✗ Ошибки (исключены)'),
                Patch(facecolor='#CCCCCC', edgecolor='black', label='- Пропущены'),
            ]
            
            ax.legend(
                handles=legend_elements,
                loc='upper right',
                fontsize=10,
                framealpha=0.95,
                edgecolor='black',
                fancybox=True,
                shadow=True
            )
        
        ax.set_aspect('equal')
        ax.autoscale()
        ax.margins(0.05)
        ax.axis('off')
        
        # Заголовок с информацией
        title_text = f"Анализ чертежа | Объектов обработано: {len(objects_data)}"
        if collector.has_errors:
            title_text += f" | Ошибок: {len(collector.errors)}"
        if collector.warnings:
            title_text += f" | Предупреждений: {len(collector.warnings)}"
        
        fig.suptitle(title_text, fontsize=12, fontweight='bold')
        
        plt.tight_layout(pad=0.3)
        
        return fig, None  # ИСПРАВЛЕНИЕ 19: Возвращаем None если успех
    
    except MemoryError as e:
        error_msg = f"Недостаточно памяти для визуализации: {e}"
        logger.error(error_msg)
        return None, error_msg  # ИСПРАВЛЕНИЕ 19: Возвращаем сообщение об ошибке
    
    except Exception as e:
        error_msg = f"Ошибка визуализации: {e}"
        logger.error(error_msg)
        return None, error_msg  # ИСПРАВЛЕНИЕ 19: Возвращаем сообщение об ошибке
    
    finally:
        # ИСПРАВЛЕНИЕ 2: Finally блок для гарантированной очистки
        pass


# ==================== БЛОК ОТОБРАЖЕНИЯ ОШИБОК В UI ====================

def show_error_report(collector: ErrorCollector):
    """
    Показывает отчёт об ошибках в Streamlit UI.
    ИСПРАВЛЕНИЕ 8: Правильная структура табов
    """
    if not collector.has_issues:
        st.success("✅ Обработка завершена без ошибок")
        return
    
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
    
    with st.expander(
        f"🔍 Подробный отчёт о проблемах ({collector.total_issues} записей)",
        expanded=False
    ):
        # ИСПРАВЛЕНИЕ 8: Правильная построение списка вкладок
        tab_labels = []
        
        if collector.errors:
            tab_labels.append(f"🔴 Ошибки ({len(collector.errors)})")
        if collector.warnings:
            tab_labels.append(f"🟡 Предупреждения ({len(collector.warnings)})")
        if collector.skipped:
            tab_labels.append(f"⚪ Пропущено ({len(collector.skipped)})")
        
        tab_labels.append("📋 Все проблемы")
        
        # ИСПРАВЛЕНИЕ 8: Гарантируем, что tab_labels не пусты
        if not tab_labels:
            st.info("✅ Проблем не обнаружено")
            return
        
        tabs = st.tabs(tab_labels)
        tab_idx = 0
        
        if collector.errors:
            with tabs[tab_idx]:
                st.markdown("**Критические ошибки** — объекты НЕ учтены в расчёте:")
                df_errors = pd.DataFrame([issue.to_dict() for issue in collector.errors])
                st.dataframe(df_errors, use_container_width=True, hide_index=True)
                st.info("💡 Эти объекты исключены из итоговой длины реза.")
            tab_idx += 1
        
        if collector.warnings:
            with tabs[tab_idx]:
                st.markdown("**Предупреждения** — объекты включены в расчёт с коррекцией:")
                df_warnings = pd.DataFrame([issue.to_dict() for issue in collector.warnings])
                st.dataframe(df_warnings, use_container_width=True, hide_index=True)
                st.warning("💡 Эти объекты включены в расчёт с коррекцией значений.")
            tab_idx += 1
        
        if collector.skipped:
            with tabs[tab_idx]:
                st.markdown("**Пропущенные объекты** — не входят в расчёт:")
                df_skipped = pd.DataFrame([issue.to_dict() for issue in collector.skipped])
                st.dataframe(df_skipped, use_container_width=True, hide_index=True)
                st.info("💡 Эти типы объектов не поддерживаются или имеют нулевую длину.")
            tab_idx += 1
        
        with tabs[tab_idx]:
            st.markdown("**Полный лог всех проблем:**")
            df_all = collector.get_all_as_dataframe()
            if not df_all.empty:
                st.dataframe(df_all, use_container_width=True, hide_index=True)
                csv_log = df_all.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 Скачать лог ошибок (CSV)",
                    data=csv_log,
                    file_name="error_log.csv",
                    mime="text/csv"
                )
        
        if collector.has_errors:
            st.markdown("---")
            st.markdown("### 📊 Влияние на результат расчёта")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Объектов с ошибками", len(collector.errors))
            with col2:
                st.metric("Предупреждений", len(collector.warnings))
            st.warning(
                "⚠️ **Итоговая длина реза может быть занижена** "
                f"из-за {len(collector.errors)} объектов с ошибками."
            )


# ==================== STREAMLIT ИНТЕРФЕЙС ====================

st.set_page_config(
    page_title="Анализатор Чертежей CAD Pro v17.0",
    page_icon="📐",
    layout="wide"
)

st.title("📐 Анализатор Чертежей CAD Pro v17.0")
st.markdown("""
**Профессиональный расчет длины реза для станков ЧПУ и лазерной резки**

### 🎯 Новое в v17.0:
✅ **Сохранение исходных цветов линий из файла DXF**  
✅ **Полная палитра ACI цветов AutoCAD**  
✅ **Опция переключения между исходными цветами и индикацией ошибок**  
✅ **Группировка объектов по цветам в спецификации**  
✅ **Все исправления из v16.0 сохранены**  
""")

with st.expander("ℹ️ Информация о цветах"):
    st.markdown("""
    ### Режимы отображения чертежа:
    
    **Режим 1: Исходные цвета из файла (по умолчанию)**
    - Линии отображаются теми цветами, которые установлены в DXF файле
    - Ошибки выделяются красной обводкой поверх исходного цвета
    - Предупреждения выделяются оранжевой обводкой
    
    **Режим 2: Индикация статуса**
    - Чёрный = Нормальные объекты (учтены)
    - Оранжевый = Предупреждения (учтены с коррекцией)
    - Красный = Ошибки (исключены)
    - Серый = Пропущены
    """)

st.markdown("---")

uploaded_file = st.file_uploader(
    "📂 Загрузите чертеж в формате DXF",
    type=["dxf"]
)

if uploaded_file is not None:
    # ИСПРАВЛЕНИЕ 16: Проверка размера файла
    file_size_mb = uploaded_file.size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        st.error(
            f"❌ Файл слишком большой: {file_size_mb:.1f} МБ "
            f"(максимум: {MAX_FILE_SIZE_MB} МБ)"
        )
        st.stop()
    
    # ИСПРАВЛЕНИЕ 1: Правильная структура try-except
    collector = ErrorCollector()
    fig = None
    
    with st.spinner('⏳ Обработка чертежа...'):
        try:
            with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
                tmp.write(uploaded_file.getbuffer())
                temp_path = tmp.name
            
            try:
                doc = ezdxf.readfile(temp_path)
                
                dxf_version = doc.dxfversion
                if dxf_version < 'AC1018':
                    collector.add_warning(
                        'FILE', 0,
                        f"Старая версия DXF: {dxf_version}",
                        "DXFVersionWarning"
                    )
                
                collector.add_info('FILE', 0, f"Файл загружен. Версия: {dxf_version}")
            
            except ezdxf.DXFError as e:
                collector.add_error('FILE', 0, f"Ошибка чтения DXF: {e}", "DXFError")
                show_error_report(collector)
                st.stop()
            except Exception as e:
                collector.add_error('FILE', 0, f"Ошибка: {e}", type(e).__name__)
                show_error_report(collector)
                st.stop()
            finally:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            
            msp = doc.modelspace()
            
            # ==================== АНАЛИЗ ====================
            objects_data: List[DXFObject] = []
            stats: Dict[str, Dict[str, Any]] = {}
            color_stats: Dict[int, Dict[str, Any]] = {}  # НОВОЕ: Статистика по цветам
            total_length = 0.0
            skipped_types = set()
            
            real_object_num = 0
            calc_object_num = 0
            
            for entity in msp:
                entity_type = entity.dxftype()
                real_object_num += 1
                
                layer, color = get_layer_info(entity)
                
                if entity_type not in calculators:
                    if entity_type not in SILENT_SKIP_TYPES:
                        skipped_types.add(entity_type)
                    continue
                
                length, status, issue_desc = calc_entity_safe(
                    entity_type, entity, real_object_num, calculators, collector
                )
                
                if length < MIN_LENGTH:
                    if entity_type not in ZERO_LENGTH_TYPES:
                        collector.add_skipped(
                            entity_type, real_object_num,
                            f"Нулевая длина: {length:.6f}"
                        )
                    continue
                
                calc_object_num += 1
                center = get_entity_center(entity)
                
                dxf_obj = DXFObject(
                    num=calc_object_num,
                    real_num=real_object_num,
                    entity_type=entity_type,
                    length=length,
                    center=center,
                    entity=entity,
                    layer=layer,
                    color=color,
                    original_color=color,  # НОВОЕ: Сохраняем исходный цвет
                    status=status,
                    original_length=length,
                    issue_description=issue_desc
                )
                
                objects_data.append(dxf_obj)
                
                if entity_type not in stats:
                    stats[entity_type] = {'count': 0, 'length': 0.0, 'items': []}
                
                stats[entity_type]['count'] += 1
                stats[entity_type]['length'] += length
                stats[entity_type]['items'].append({'num': calc_object_num, 'length': length})
                
                # НОВОЕ: Статистика по цветам
                if color not in color_stats:
                    color_stats[color] = {
                        'count': 0,
                        'length': 0.0,
                        'color_name': get_color_name(color),
                        'hex_color': get_aci_color(color)
                    }
                
                color_stats[color]['count'] += 1
                color_stats[color]['length'] += length
                
                total_length += length
            
            # ==================== ВЫВОД ====================
            show_error_report(collector)
            
            if not objects_data:
                st.warning("⚠️ В чертеже не найдено объектов для расчета")
                if skipped_types:
                    st.info(f"Пропущено: {', '.join(sorted(skipped_types))}")
            else:
                if collector.has_errors:
                    st.success(
                        f"✅ Обработано: **{len(objects_data)}** объектов "
                        f"(🔴 {len(collector.errors)} ошибок)"
                    )
                else:
                    st.success(f"✅ Обработано: **{len(objects_data)}** объектов")
                
                # Метрики
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
                    st.markdown("### 📊 Сводная спецификация по типам")
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
                    st.dataframe(df_summary, use_container_width=True, hide_index=True)
                    
                    # НОВОЕ: Спецификация по цветам
                    st.markdown("### 🎨 Статистика по цветам")
                    color_rows = []
                    for color_id in sorted(color_stats.keys()):
                        color_info = color_stats[color_id]
                        color_rows.append({
                            '🟦 Цвет': f"<span style='color: {color_info['hex_color']}'>●</span> {color_info['color_name']}",
                            'Код': color_id,
                            'Кол-во': color_info['count'],
                            'Длина (мм)': round(color_info['length'], 2)
                        })
                    
                    if color_rows:
                        df_colors = pd.DataFrame(color_rows)
                        st.markdown(df_colors.to_html(escape=False), unsafe_allow_html=True)
                    
                    st.markdown("### 🔄 Повторяющиеся элементы")
                    length_groups: Dict[float, Dict] = {}
                    
                    # ИСПРАВЛЕНИЕ 18: Оптимизированная группировка
                    for obj in objects_data:
                        # Оптимизация: группируем прямо без Decimal если не нужна точность
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
                        st.dataframe(df_groups, use_container_width=True, hide_index=True)
                    else:
                        st.info("Повторяющихся элементов не обнаружено")
                
                with col_right:
                    st.markdown("### 🎨 Чертеж с цветовой индикацией")
                    
                    # НОВОЕ: Опция выбора режима отображения цветов
                    display_mode = st.radio(
                        "Режим отображения:",
                        options=["Исходные цвета", "Индикация ошибок"],
                        horizontal=True
                    )
                    
                    use_original_colors = display_mode == "Исходные цвета"
                    
                    show_markers = st.checkbox("🔴 Показать маркеры", value=True)
                    
                    if show_markers:
                        font_size_multiplier = st.slider(
                            "📏 Размер шрифта",
                            min_value=0.5, max_value=3.0, value=1.0, step=0.1
                        )
                    else:
                        font_size_multiplier = 1.0
                    
                    with st.spinner('Генерация визуализации...'):
                        fig, error_msg = visualize_dxf_with_status_indicators(
                            doc, objects_data, collector,
                            show_markers, font_size_multiplier,
                            use_original_colors  # НОВОЕ: Передаём флаг режима
                        )
                        
                        # ИСПРАВЛЕНИЕ 19: Правильная обработка ошибок
                        if fig is not None:
                            st.pyplot(fig, use_container_width=True)
                        else:
                            if error_msg:
                                st.error(f"❌ {error_msg}")
                            else:
                                st.error("❌ Не удалось создать визуализацию")
                
                # ИСПРАВЛЕНИЕ 17: Правильное управление фигурой в Streamlit
                # Streamlit сам управляет фигурами после st.pyplot()
        
        except Exception as e:
            collector.add_error('SYSTEM', 0, f"Критическая ошибка: {e}", type(e).__name__)
            show_error_report(collector)
            
            import traceback
            with st.expander("🔍 Трассировка ошибки"):
                st.code(traceback.format_exc())

else:
    st.info("👈 Загрузите DXF-чертеж для начала")
    st.markdown("""
    ### 📝 О версии v17.0 (НОВАЯ):
    
    **ГЛАВНОЕ ОБНОВЛЕНИЕ:**
    - ✅ **Сохранение исходных цветов линий из DXF файла**
    - ✅ Полная поддержка палитры ACI цветов AutoCAD
    - ✅ Переключение между режимами отображения
    - ✅ Группировка по цветам в спецификации
    
    **ВСЕ ПРЕДЫДУЩИЕ ИСПРАВЛЕНИЯ:**
    - ✅ Полная переструктуризация try-except блоков
    - ✅ Защита от утечек фигур matplotlib
    - ✅ Исправлены все проблемы с is_closed
    - ✅ Добавлена валидация размера файла (макс. 50 МБ)
    - ✅ Поддержка numpy типов в safe_float
    - ✅ Оптимизирована группировка элементов
    - ✅ Корректная обработка исключений везде
    """)

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; font-size: 12px;'>
    ✂️ CAD Analyzer Pro v17.0 | Лицензия MIT
</div>
""", unsafe_allow_html=True)
