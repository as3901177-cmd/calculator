import subprocess
import sys
import os
import math
import warnings
import logging
import tempfile
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import streamlit as st
from typing import Tuple, Optional, Dict, List, Any, Set
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict, deque
from decimal import Decimal

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
        'pandas': 'pandas>=2.2.0',
        'scipy': 'scipy>=1.11.0'
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
    from scipy.spatial import KDTree
except ImportError as e:
    st.error(f"❌ Ошибка загрузки зависимостей: {e}")
    st.info("🔄 Попробуйте перезагрузить страницу")
    st.stop()

warnings.filterwarnings('ignore')

# ==================== КОНСТАНТЫ ====================
# Ограничения обработки
MAX_SPLINE_POINTS = 5000
SPLINE_FLATTENING = 0.01
MAX_LENGTH = 1_000_000
MIN_LENGTH = 1e-6
MAX_FILE_SIZE_MB = 50
MAX_CENTER_POINTS = 500
MAX_ENTITIES_PER_BLOCK = 10000

# Параметры геометрии
BULGE_EPSILON = 0.0001
COORD_EPSILON = 1e-10
ENTITY_COORD_PRECISION = 10
PIERCING_TOLERANCE = 0.1  # мм

# Параметры визуализации
SPLINE_RENDER_MAX_POINTS = 5000
DRAWING_FONT_SCALE_FACTOR = 0.003
DRAWING_FONT_MIN_SIZE = 7
ARC_RENDER_SEGMENTS = 51

# Палитра цветов ACI (AutoCAD Color Index)
ACI_COLORS = {
    0: '#000000', 1: '#FF0000', 2: '#FFFF00', 3: '#00FF00', 4: '#00FFFF',
    5: '#0000FF', 6: '#FF00FF', 7: '#FFFFFF', 8: '#414141', 9: '#808080',
    10: '#FF0000', 11: '#FFAAAA', 12: '#BD0000', 13: '#BD3D3D', 14: '#840000',
    15: '#843D3D', 16: '#FF3333', 17: '#FF6666', 18: '#FF9999', 19: '#FFCCCC',
    20: '#FF0000', 21: '#FFFF00', 22: '#00FF00', 23: '#00FFFF', 24: '#0000FF',
    25: '#FF00FF', 26: '#FFFF80', 27: '#80FF80', 28: '#80FFFF', 29: '#8080FF',
    30: '#FF80FF', 256: '#000000', 257: '#FF0000',
}

# Цвета для статусов
COLOR_ERROR_OVERLAY = '#FF0000'
COLOR_WARNING_OVERLAY = '#FF8800'

# Цвета маркеров
MARKER_COLOR_NORMAL = '#FFFFFF'
MARKER_BG_NORMAL = '#000000'
MARKER_COLOR_WARNING = '#000000'
MARKER_BG_WARNING = '#FF8800'
MARKER_COLOR_ERROR = '#FFFFFF'
MARKER_BG_ERROR = '#FF0000'

ZERO_LENGTH_TYPES = {'POINT', 'MLINE', 'INSERT', 'TEXT', 'ATTRIB', 'DIMENSION'}
SILENT_SKIP_TYPES = {'DIMENSION', 'VIEWPORT', 'LAYOUT', 'BLOCK'}

def get_aci_color(color_id: int) -> str:
    """Преобразует ACI номер цвета в HEX код."""
    if color_id in ACI_COLORS:
        return ACI_COLORS[color_id]
    
    if 1 <= color_id <= 255:
        base_colors = [
            '#000000', '#FF0000', '#FFFF00', '#00FF00', '#00FFFF',
            '#0000FF', '#FF00FF', '#FFFFFF', '#414141', '#808080'
        ]
        return base_colors[color_id % len(base_colors)]
    
    return '#000000'

def get_color_name(color_id: int) -> str:
    """Получает название цвета по ACI коду."""
    color_names = {
        0: "Чёрный", 1: "Красный", 2: "Жёлтый", 3: "Зелёный", 4: "Голубой",
        5: "Синий", 6: "Пурпур", 7: "Белый", 8: "Тёмно-серый", 9: "Серый",
        256: "По слою", 257: "По блоку"
    }
    return color_names.get(color_id, f"Цвет {color_id}")


# ==================== ENUM ====================
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


# ==================== DATACLASS ====================
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
    original_color: int = 256
    status: ObjectStatus = ObjectStatus.NORMAL
    original_length: float = 0.0
    issue_description: str = ""
    is_closed: bool = False
    chain_id: int = -1


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
    """Собирает ошибки во время обработки."""
    
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
    
    def add_error(self, entity_type: str, entity_num: int, error_msg: str, error_class: str = ""):
        self.add_issue(ProcessingIssue(
            entity_type=entity_type, entity_num=entity_num, description=error_msg,
            error_class=error_class, severity=ErrorSeverity.ERROR
        ), object_num=entity_num)
    
    def add_warning(self, entity_type: str, entity_num: int, warning_msg: str, error_class: str = ""):
        self.add_issue(ProcessingIssue(
            entity_type=entity_type, entity_num=entity_num, description=warning_msg,
            error_class=error_class, severity=ErrorSeverity.WARNING
        ), object_num=entity_num)
    
    def add_skipped(self, entity_type: str, entity_num: int, reason: str):
        self.add_issue(ProcessingIssue(
            entity_type=entity_type, entity_num=entity_num, description=reason,
            error_class="", severity=ErrorSeverity.SKIPPED
        ), object_num=entity_num)
    
    def add_info(self, entity_type: str, entity_num: int, info_msg: str):
        self.add_issue(ProcessingIssue(
            entity_type=entity_type, entity_num=entity_num, description=info_msg,
            error_class="", severity=ErrorSeverity.INFO
        ), object_num=entity_num)
    
    @property
    def errors(self) -> List[ProcessingIssue]:
        return [i for i in self.issues if i.severity == ErrorSeverity.ERROR]
    
    @property
    def warnings(self) -> List[ProcessingIssue]:
        return [i for i in self.issues if i.severity == ErrorSeverity.WARNING]
    
    @property
    def skipped(self) -> List[ProcessingIssue]:
        return [i for i in self.issues if i.severity == ErrorSeverity.SKIPPED]
    
    @property
    def has_issues(self) -> bool:
        return bool(self.issues)
    
    @property
    def has_errors(self) -> bool:
        return bool(self.errors)
    
    @property
    def total_issues(self) -> int:
        return len(self.issues)
    
    def get_all_as_dataframe(self) -> pd.DataFrame:
        if not self.issues:
            return pd.DataFrame()
        return pd.DataFrame([issue.to_dict() for issue in self.issues])
    
    def get_summary(self) -> str:
        parts = []
        if self.errors:
            parts.append(f"🔴 Ошибок: {len(self.errors)}")
        if self.warnings:
            parts.append(f"🟡 Предупреждений: {len(self.warnings)}")
        if self.skipped:
            parts.append(f"⚪ Пропущено: {len(self.skipped)}")
        return " | ".join(parts) if parts else "✅ Проблем не обнаружено"


# ==================== УТИЛИТЫ ====================

def safe_float(value: Any) -> Optional[float]:
    """Безопасное преобразование в float."""
    try:
        if isinstance(value, str):
            lower_val = value.lower().strip()
            if lower_val in ('inf', '+inf', '-inf', 'nan', 'infinity', '+infinity', '-infinity'):
                return None
        
        if isinstance(value, Decimal):
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


def extract_polyline_points(entity: Any, max_points: int = MAX_CENTER_POINTS) -> List[Tuple[float, float]]:
    """
    НОВОЕ: Универсальная функция извлечения точек из полилиний.
    Избегает дублирования кода.
    """
    entity_type = entity.dxftype()
    points = []
    
    try:
        if entity_type == 'LWPOLYLINE':
            with entity.points('xy') as pts:
                points = [(safe_float(p[0]), safe_float(p[1])) for p in pts]
        
        elif entity_type == 'POLYLINE':
            points = [(safe_float(p[0]), safe_float(p[1])) for p in entity.points()]
        
        elif entity_type == 'SPLINE':
            for i, pt in enumerate(entity.flattening(SPLINE_FLATTENING)):
                if i >= max_points:
                    break
                x, y = safe_float(pt[0]), safe_float(pt[1])
                if x is not None and y is not None:
                    points.append((x, y))
    
    except (AttributeError, TypeError, ValueError) as e:
        logger.debug(f"Ошибка при извлечении точек {entity_type}: {e}")
    
    return [(x, y) for x, y in points if x is not None and y is not None]


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
            else:
                return bool(entity.dxf.flags & 0x01)
        
        if entity_type == 'SPLINE':
            points = extract_polyline_points(entity, max_points=2)
            if len(points) >= 2:
                first, last = points[0], points[-1]
                dist = math.hypot(last[0] - first[0], last[1] - first[1])
                return dist < COORD_EPSILON
            return False
        
        return False
    
    except Exception as e:
        logger.debug(f"Ошибка проверки замкнутости для {entity_type}: {e}")
        return False


# ==================== ВАЛИДАЦИЯ ====================

def validate_length_result(length: Any, entity_type: str, entity_num: int, 
                           collector: ErrorCollector) -> Tuple[float, bool, str]:
    """Проверяет корректность вычисленной длины."""
    if length is None:
        collector.add_error(entity_type, entity_num, "Функция вернула None вместо числа", "TypeError")
        return 0.0, False, "TypeError: None returned"
    
    try:
        length_float = float(length)
    except (ValueError, TypeError, OverflowError):
        collector.add_error(entity_type, entity_num, 
                           f"Некорректный тип результата: {type(length).__name__}", "TypeError")
        return 0.0, False, f"TypeError: {type(length).__name__}"
    
    try:
        if math.isnan(length_float):
            collector.add_error(entity_type, entity_num,
                               "Результат вычисления: NaN (не число). Возможно повреждены координаты объекта",
                               "ValueError")
            return 0.0, False, "ValueError: NaN result"
    except (TypeError, ValueError):
        pass
    
    try:
        if math.isinf(length_float):
            collector.add_error(entity_type, entity_num,
                               "Результат вычисления: Infinity. Возможно деление на ноль в геометрии",
                               "ZeroDivisionError")
            return 0.0, False, "ZeroDivisionError: Infinity"
    except (TypeError, ValueError):
        pass
    
    if length_float < 0:
        collector.add_warning(entity_type, entity_num,
                             f"Отрицательная длина: {length_float:.4f}. Используется абсолютное значение",
                             "GeometryWarning")
        return abs(length_float), True, "GeometryWarning: Negative length corrected"
    
    if length_float > MAX_LENGTH:
        collector.add_warning(entity_type, entity_num,
                             f"Аномально большая длина: {length_float:.2f} мм ({length_float/1000:.1f} м). "
                             f"Проверьте единицы измерения чертежа", "ScaleWarning")
        return length_float, True, "ScaleWarning: Abnormally large value"
    
    return length_float, True, ""


def calc_entity_safe(entity_type: str, entity: Any, entity_num: int, 
                     calculators: Dict, collector: ErrorCollector) -> Tuple[float, ObjectStatus, str]:
    """Безопасный вызов калькулятора с полным сбором ошибок."""
    if entity_type not in calculators:
        collector.add_skipped(entity_type, entity_num, f"Тип '{entity_type}' не поддерживается")
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
        collector.add_error(entity_type, entity_num,
                           f"Отсутствует атрибут DXF: {e}. Возможно файл создан в нестандартной программе",
                           "AttributeError")
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except ZeroDivisionError as e:
        collector.add_error(entity_type, entity_num,
                           f"Деление на ноль при вычислении геометрии: {e}. Объект может иметь нулевые размеры",
                           "ZeroDivisionError")
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except (ValueError, TypeError, OverflowError, MemoryError, RecursionError) as e:
        collector.add_error(entity_type, entity_num, f"{type(e).__name__}: {e}", type(e).__name__)
        return 0.0, ObjectStatus.ERROR, str(e)
    
    except Exception as e:
        collector.add_error(entity_type, entity_num, f"Неожиданная ошибка: {e}", type(e).__name__)
        return 0.0, ObjectStatus.ERROR, type(e).__name__


# ==================== РАСЧЁТ ДЛИНЫ ====================

def calc_line_length(entity: Any) -> float:
    """LINE: прямая линия."""
    start, end = entity.dxf.start, entity.dxf.end
    x1, y1 = safe_coordinate(start)
    x2, y2 = safe_coordinate(end)
    
    if None in (x1, y1, x2, y2):
        raise ValueError("Некорректные координаты линии")
    
    return math.hypot(x2 - x1, y2 - y1)


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
        raise ValueError(f"Некорректный ratio > 1: {ratio}")
    
    start_param = safe_float(entity.dxf.start_param)
    end_param = safe_float(entity.dxf.end_param)
    
    if start_param is None or end_param is None:
        raise ValueError("Некорректные параметры эллипса")
    
    try:
        mx, my, mz = safe_float(major_axis.x), safe_float(major_axis.y), safe_float(major_axis.z)
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
        return math.pi * (a + b) * (1 + 3*h / (10 + math.sqrt(4 - 3*h)))
    
    N = min(1000, max(100, int(angle_span * 100)))
    
    # НОВОЕ: Векторизация через numpy
    t = np.linspace(start_param, start_param + angle_span, N + 1)
    x = a * np.cos(t)
    y = b * np.sin(t)
    
    dx = np.diff(x)
    dy = np.diff(y)
    lengths = np.sqrt(dx**2 + dy**2)
    
    return np.sum(lengths[np.isfinite(lengths)])


def calc_lwpolyline_length(entity: Any) -> float:
    """LWPOLYLINE: лёгкая полилиния с bulge."""
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
    
    try:
        is_closed = entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
    except (AttributeError, TypeError):
        is_closed = False
    
    num_segments = len(points) if is_closed else len(points) - 1
    
    for i in range(num_segments):
        curr_idx = i
        next_idx = (i + 1) % len(points) if is_closed else i + 1
        
        if next_idx >= len(points):
            continue
        
        try:
            x1, y1 = safe_float(points[curr_idx][0]), safe_float(points[curr_idx][1])
            x2, y2 = safe_float(points[next_idx][0]), safe_float(points[next_idx][1])
            
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
    points = extract_polyline_points(entity)
    
    if len(points) < 2:
        return 0.0
    
    # НОВОЕ: Векторизация через numpy
    points_array = np.array(points)
    diffs = np.diff(points_array, axis=0)
    lengths = np.sqrt(np.sum(diffs**2, axis=1))
    length = np.sum(lengths)
    
    try:
        if hasattr(entity, 'is_closed'):
            is_closed = entity.is_closed
        else:
            is_closed = bool(entity.dxf.flags & 0x01)
    except (AttributeError, TypeError):
        is_closed = False
    
    if is_closed and len(points) >= 2:
        length += math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1])
    
    return length


def calc_spline_length(entity: Any) -> float:
    """SPLINE: сплайн."""
    points = extract_polyline_points(entity, max_points=MAX_SPLINE_POINTS)
    
    if len(points) < 2:
        return 0.0
    
    # НОВОЕ: Векторизация через numpy
    points_array = np.array(points)
    diffs = np.diff(points_array, axis=0)
    lengths = np.sqrt(np.sum(diffs**2, axis=1))
    
    return np.sum(lengths)


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


calculators = {
    'LINE': calc_line_length,
    'CIRCLE': calc_circle_length,
    'ARC': calc_arc_length,
    'ELLIPSE': calc_ellipse_length,
    'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE': calc_polyline_length,
    'SPLINE': calc_spline_length,
    'POINT': calc_point_length,
    'MLINE': calc_mline_length,
    'INSERT': calc_insert_length,
    'TEXT': calc_text_length,
    'ATTRIB': calc_attrib_length,
}


# ==================== ЦЕНТР ОБЪЕКТА ====================

def get_entity_center(entity: Any) -> Tuple[float, float]:
    """Возвращает центр объекта БЕЗ смещения."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            x1, y1 = safe_coordinate(start)
            x2, y2 = safe_coordinate(end)
            if None in (x1, y1, x2, y2):
                return (0.0, 0.0)
            return ((x1 + x2) / 2, (y1 + y2) / 2)
        
        if entity_type in ('CIRCLE', 'ARC', 'ELLIPSE'):
            center = entity.dxf.center
            x, y = safe_coordinate(center)
            return (x or 0.0, y or 0.0)
        
        if entity_type == 'POINT':
            loc = entity.dxf.location
            x, y = safe_coordinate(loc)
            return (x or 0.0, y or 0.0)
        
        if entity_type in ('LWPOLYLINE', 'POLYLINE', 'SPLINE'):
            points = extract_polyline_points(entity)
            if len(points) >= 1:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            return (0.0, 0.0)
        
        if entity_type == 'INSERT':
            pos = entity.dxf.insert
            x, y = safe_coordinate(pos)
            return (x or 0.0, y or 0.0)
    
    except Exception as e:
        logger.debug(f"Ошибка при получении центра: {e}")
        return (0.0, 0.0)
    
    return (0.0, 0.0)


def normalize_angle(angle_deg: float) -> float:
    """Нормализует угол в диапазон [0, 360)."""
    return angle_deg % 360.0


def get_entity_center_with_offset(entity: Any, offset_distance: float) -> Tuple[float, float]:
    """Возвращает центр объекта СО СМЕЩЕНИЕМ для маркеров."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            x1, y1 = safe_coordinate(start)
            x2, y2 = safe_coordinate(end)
            
            if None in (x1, y1, x2, y2):
                return (0.0, 0.0)
            
            center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
            dx, dy = x2 - x1, y2 - y1
            line_length = math.hypot(dx, dy)
            
            if line_length > COORD_EPSILON:
                perp_x, perp_y = -dy / line_length, dx / line_length
                return (center_x + perp_x * offset_distance, center_y + perp_y * offset_distance)
            
            return (center_x, center_y)
        
        if entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = safe_float(entity.dxf.radius)
            x, y = safe_coordinate(center)
            if x is None or y is None or radius is None:
                return (0.0, 0.0)
            return (x + radius + offset_distance, y)
        
        if entity_type == 'ARC':
            center = entity.dxf.center
            radius = safe_float(entity.dxf.radius)
            start_angle = safe_float(entity.dxf.start_angle)
            end_angle = safe_float(entity.dxf.end_angle)
            x, y = safe_coordinate(center)
            
            if any(v is None for v in (x, y, radius, start_angle, end_angle)):
                return (0.0, 0.0)
            
            start_rad = math.radians(start_angle)
            end_rad = math.radians(end_angle)
            mid_angle = (start_rad + end_rad) / 2
            if end_rad < start_rad:
                mid_angle += math.pi
            
            return (x + (radius + offset_distance) * math.cos(mid_angle),
                   y + (radius + offset_distance) * math.sin(mid_angle))
        
        if entity_type == 'ELLIPSE':
            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            x, y = safe_coordinate(center)
            if x is None or y is None:
                return (0.0, 0.0)
            
            try:
                a = math.sqrt(safe_float(major_axis.x)**2 + safe_float(major_axis.y)**2) \
                    if (safe_float(major_axis.x) is not None and safe_float(major_axis.y) is not None) else 0
            except (AttributeError, TypeError, ValueError):
                a = 0
            
            if a <= 0:
                return (x, y)
            return (x + a + offset_distance, y)
        
        if entity_type in ('LWPOLYLINE', 'POLYLINE', 'SPLINE'):
            center = get_entity_center(entity)
            points = extract_polyline_points(entity, max_points=2)
            
            if len(points) >= 2:
                dx, dy = points[1][0] - points[0][0], points[1][1] - points[0][1]
                seg_length = math.hypot(dx, dy)
                
                if seg_length > COORD_EPSILON:
                    perp_x, perp_y = -dy / seg_length, dx / seg_length
                    return (center[0] + perp_x * offset_distance, center[1] + perp_y * offset_distance)
            
            return center
        
        if entity_type == 'INSERT':
            pos = entity.dxf.insert
            x, y = safe_coordinate(pos)
            if x is None or y is None:
                return (0.0, 0.0)
            return (x + offset_distance, y + offset_distance)
    
    except Exception as e:
        logger.debug(f"Ошибка при получении центра со смещением: {e}")
        return get_entity_center(entity)
    
    return (0.0, 0.0)


# ==================== ПОЛУЧЕНИЕ КОНЦОВ ====================

def get_entity_endpoints(entity: Any) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    """Извлекает начальную и конечную точки объекта."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            x1, y1 = safe_coordinate(start)
            x2, y2 = safe_coordinate(end)
            if None in (x1, y1, x2, y2):
                return None, None
            return (x1, y1), (x2, y2)
        
        if entity_type == 'ARC':
            center = entity.dxf.center
            radius = safe_float(entity.dxf.radius)
            start_angle = safe_float(entity.dxf.start_angle)
            end_angle = safe_float(entity.dxf.end_angle)
            cx, cy = safe_coordinate(center)
            
            if any(v is None for v in (cx, cy, radius, start_angle, end_angle)):
                return None, None
            
            start_rad = math.radians(start_angle)
            end_rad = math.radians(end_angle)
            
            start_point = (cx + radius * math.cos(start_rad), cy + radius * math.sin(start_rad))
            end_point = (cx + radius * math.cos(end_rad), cy + radius * math.sin(end_rad))
            
            return start_point, end_point
        
        if entity_type in ('LWPOLYLINE', 'POLYLINE', 'SPLINE'):
            points = extract_polyline_points(entity, max_points=MAX_CENTER_POINTS)
            if len(points) >= 2:
                return points[0], points[-1]
        
        if entity_type in ('CIRCLE', 'ELLIPSE'):
            return None, None
    
    except Exception as e:
        logger.debug(f"Ошибка извлечения концов {entity_type}: {e}")
    
    return None, None


def points_close(p1: Tuple[float, float], p2: Tuple[float, float], tolerance: float) -> bool:
    """Проверяет близость двух точек."""
    try:
        distance = math.hypot(p1[0] - p2[0], p1[1] - p2[1])
        return distance < tolerance
    except (TypeError, IndexError):
        return False


# ==================== ПОИСК СВЯЗАННЫХ КОНТУРОВ (ОПТИМИЗИРОВАНО) ====================

def find_connected_chain(
    start_idx: int, 
    objects: List[DXFObject], 
    tolerance: float,
    endpoints_cache: Dict[int, Tuple],
    kdtree: Optional[KDTree] = None,
    point_to_objects: Optional[Dict] = None
) -> Set[int]:
    """
    ОПТИМИЗИРОВАНО: Находит связанные объекты через KDTree O(N log N).
    
    Изменения:
    - Использует collections.deque вместо list
    - Получает endpoints_cache извне (создаётся один раз)
    - Использует KDTree для быстрого поиска соседей
    """
    chain = {start_idx}
    queue = deque([start_idx])  # НОВОЕ: deque вместо list
    
    while queue:
        current_idx = queue.popleft()  # НОВОЕ: O(1) вместо O(N)
        
        current_endpoints = endpoints_cache.get(current_idx, (None, None))
        start_pt, end_pt = current_endpoints
        
        if start_pt is None or end_pt is None:
            continue
        
        # НОВОЕ: Если есть KDTree, используем его для быстрого поиска
        if kdtree is not None and point_to_objects is not None:
            candidates = set()
            for point in [start_pt, end_pt]:
                # Поиск всех точек в радиусе tolerance за O(log N)
                nearby_indices = kdtree.query_ball_point(point, tolerance)
                for pt_idx in nearby_indices:
                    candidates.update(point_to_objects.get(pt_idx, []))
            
            # Проверяем только кандидатов
            for idx in candidates:
                if idx in chain or idx == current_idx:
                    continue
                
                obj = objects[idx]
                if obj.status not in (ObjectStatus.NORMAL, ObjectStatus.WARNING):
                    continue
                
                neighbor_endpoints = endpoints_cache.get(idx, (None, None))
                neighbor_start, neighbor_end = neighbor_endpoints
                
                if neighbor_start is None or neighbor_end is None:
                    continue
                
                # Проверяем близость
                if (points_close(end_pt, neighbor_start, tolerance) or
                    points_close(end_pt, neighbor_end, tolerance) or
                    points_close(start_pt, neighbor_start, tolerance) or
                    points_close(start_pt, neighbor_end, tolerance)):
                    chain.add(idx)
                    queue.append(idx)
        
        else:
            # Fallback: O(N²) если KDTree недоступен
            for idx, obj in enumerate(objects):
                if idx in chain:
                    continue
                
                if obj.status not in (ObjectStatus.NORMAL, ObjectStatus.WARNING):
                    continue
                
                neighbor_endpoints = endpoints_cache.get(idx, (None, None))
                neighbor_start, neighbor_end = neighbor_endpoints
                
                if neighbor_start is None or neighbor_end is None:
                    continue
                
                connections = [
                    points_close(end_pt, neighbor_start, tolerance),
                    points_close(end_pt, neighbor_end, tolerance),
                    points_close(start_pt, neighbor_start, tolerance),
                    points_close(start_pt, neighbor_end, tolerance)
                ]
                
                if any(connections):
                    chain.add(idx)
                    queue.append(idx)
    
    return chain


# ==================== ПОДСЧЁТ ВРЕЗОК (ИСПРАВЛЕНО) ====================

def count_piercings_advanced(
    objects_data: List[DXFObject], 
    collector: ErrorCollector,
    tolerance: float = PIERCING_TOLERANCE
) -> Tuple[int, Dict[str, Any]]:
    """
    ИСПРАВЛЕНО: Правильный подсчёт врезок с анализом связности.
    
    Исправления:
    - Создание endpoints_cache один раз
    - Использование KDTree для оптимизации
    - Правильная классификация цепей
    """
    valid_objects = [
        obj for obj in objects_data 
        if obj.status in (ObjectStatus.NORMAL, ObjectStatus.WARNING)
    ]
    
    if not valid_objects:
        return 0, {
            'total': 0, 'closed_objects': 0, 'open_chains': 0,
            'isolated_objects': 0, 'chains': []
        }
    
    # НОВОЕ: Создаём кэш endpoints ОДИН РАЗ
    endpoints_cache = {}
    all_points = []
    point_to_objects = defaultdict(list)
    
    for idx, obj in enumerate(valid_objects):
        if obj.entity is not None:
            endpoints = get_entity_endpoints(obj.entity)
            endpoints_cache[idx] = endpoints
            
            # Строим индекс точек для KDTree
            start_pt, end_pt = endpoints
            if start_pt:
                pt_idx = len(all_points)
                all_points.append(start_pt)
                point_to_objects[pt_idx].append(idx)
            if end_pt:
                pt_idx = len(all_points)
                all_points.append(end_pt)
                point_to_objects[pt_idx].append(idx)
    
    # НОВОЕ: Создаём KDTree для быстрого поиска соседей
    kdtree = None
    if all_points:
        try:
            kdtree = KDTree(all_points)
        except Exception as e:
            logger.warning(f"Не удалось создать KDTree: {e}. Используется fallback O(N²)")
    
    visited = set()
    chain_count = 0
    chains_details = []
    
    closed_count = 0
    open_chains_count = 0
    isolated_count = 0
    
    for idx, obj in enumerate(valid_objects):
        if idx in visited:
            continue
        
        entity_type = obj.entity.dxftype() if obj.entity else "UNKNOWN"
        
        # Замкнутые объекты - отдельные цепи
        if obj.is_closed or entity_type in ('CIRCLE', 'ELLIPSE'):
            chain_count += 1
            closed_count += 1
            visited.add(idx)
            
            chains_details.append({
                'chain_id': chain_count,
                'type': 'closed',
                'objects_count': 1,
                'objects': [obj.num],
                'entity_types': [entity_type],
                'total_length': obj.length,
                'is_closed': True
            })
            
            obj.chain_id = chain_count
            logger.debug(f"Цепь #{chain_count}: Замкнутый {entity_type} (объект #{obj.num})")
            continue
        
        # НОВОЕ: Передаём endpoints_cache и KDTree
        chain = find_connected_chain(idx, valid_objects, tolerance, endpoints_cache, kdtree, point_to_objects)
        
        if len(chain) == 1:
            isolated_count += 1
        else:
            open_chains_count += 1
        
        visited.update(chain)
        chain_count += 1
        
        chain_objects = [valid_objects[i] for i in chain]
        chain_length = sum(obj.length for obj in chain_objects)
        chain_entity_types = [obj.entity.dxftype() if obj.entity else "UNKNOWN" for obj in chain_objects]
        
        chains_details.append({
            'chain_id': chain_count,
            'type': 'open' if len(chain) > 1 else 'isolated',
            'objects_count': len(chain),
            'objects': [obj.num for obj in chain_objects],
            'entity_types': chain_entity_types,
            'total_length': chain_length,
            'is_closed': False
        })
        
        for i in chain:
            valid_objects[i].chain_id = chain_count
        
        logger.debug(f"Цепь #{chain_count}: {len(chain)} объектов ({', '.join(chain_entity_types)}), длина {chain_length:.2f} мм")
    
    statistics = {
        'total': chain_count,
        'closed_objects': closed_count,
        'open_chains': open_chains_count,
        'isolated_objects': isolated_count,
        'chains': chains_details,
        'tolerance_used': tolerance,
        'total_objects_analyzed': len(valid_objects),
        'total_objects_in_file': len(objects_data)
    }
    
    collector.add_info('PIERCING', 0,
                      f"Анализ связности: найдено {chain_count} цепей "
                      f"({closed_count} замкнутых, {open_chains_count} групп, {isolated_count} изолированных) "
                      f"при допуске {tolerance} мм")
    
    return chain_count, statistics


def get_piercing_statistics(objects_data: List[DXFObject]) -> Dict[str, Any]:
    """
    ИСПРАВЛЕНО: Правильная классификация типов цепей.
    
    Исправления:
    - Анализ ПОСЛЕ сбора всех объектов цепи
    - Правильное вычисление 'open' без вычитания
    """
    unique_chains = set()
    chains_info = defaultdict(lambda: {
        'objects': [],
        'types': set(),
        'statuses': set(),
        'is_closed': False,
        'total_length': 0.0
    })
    
    errors_excluded = 0
    skipped_count = 0
    by_type = defaultdict(int)
    by_status = defaultdict(int)
    
    for obj in objects_data:
        if obj.status == ObjectStatus.ERROR:
            errors_excluded += 1
            continue
        
        if obj.status == ObjectStatus.SKIPPED:
            skipped_count += 1
            continue
        
        if obj.status in (ObjectStatus.NORMAL, ObjectStatus.WARNING):
            if obj.chain_id > 0:
                unique_chains.add(obj.chain_id)
                
                chains_info[obj.chain_id]['objects'].append(obj.num)
                chains_info[obj.chain_id]['types'].add(obj.entity_type)
                chains_info[obj.chain_id]['statuses'].add(obj.status.value)
                
                # ИСПРАВЛЕНО: is_closed берём из первого объекта цепи
                if not chains_info[obj.chain_id]['is_closed']:
                    chains_info[obj.chain_id]['is_closed'] = obj.is_closed
                
                chains_info[obj.chain_id]['total_length'] += obj.length
            
            by_type[obj.entity_type] += 1
            by_status[obj.status.value] += 1
    
    # ИСПРАВЛЕНО: Анализ типов цепей ПОСЛЕ сбора всех данных
    closed_chains = set()
    open_chains = set()
    isolated_chains = set()
    
    for chain_id, info in chains_info.items():
        if info['is_closed']:
            closed_chains.add(chain_id)
        elif len(info['objects']) == 1:
            isolated_chains.add(chain_id)
        else:
            open_chains.add(chain_id)
    
    chains_list = []
    for chain_id in sorted(unique_chains):
        info = chains_info[chain_id]
        chains_list.append({
            'chain_id': chain_id,
            'objects_count': len(info['objects']),
            'objects': info['objects'],
            'types': list(info['types']),
            'statuses': list(info['statuses']),
            'is_closed': info['is_closed'],
            'total_length': info['total_length']
        })
    
    # ИСПРАВЛЕНО: Правильное вычисление без вычитания
    return {
        'total': len(unique_chains),
        'closed': len(closed_chains),
        'open': len(open_chains),  # ИСПРАВЛЕНО: без вычитания
        'isolated': len(isolated_chains),
        'by_type': dict(by_type),
        'by_status': dict(by_status),
        'errors_excluded': errors_excluded,
        'skipped_count': skipped_count,
        'chains': chains_list
    }


# ==================== ВИЗУАЛИЗАЦИЯ (РАЗБИТО НА ФУНКЦИИ) ====================

def setup_figure() -> Tuple[Any, Any]:
    """Создаёт и настраивает figure и axes."""
    fig, ax = plt.subplots(figsize=(20, 16), dpi=100)
    fig.patch.set_facecolor('#E5E5E5')
    ax.set_facecolor('#F0F0F0')
    return fig, ax


def draw_entities(ax: Any, msp: Any, objects_data: List[DXFObject], 
                 use_original_colors: bool, show_chains: bool, chain_colors: Dict):
    """Рисует все entity на чертеже."""
    status_by_real_num = {
        obj.real_num: (obj.status, obj.issue_description, obj.chain_id)
        for obj in objects_data
    }
    
    real_object_num = 0
    for entity in msp:
        real_object_num += 1
        entity_type = entity.dxftype()
        
        if entity_type not in calculators:
            continue
        
        if real_object_num in status_by_real_num:
            status, _, chain_id = status_by_real_num[real_object_num]
            
            if show_chains and chain_id > 0:
                color = chain_colors.get(chain_id, '#000000')
                linewidth = 2.0
            elif use_original_colors:
                draw_entity_manually(ax, entity, use_original_color=True, linewidth=1.5)
                if status == ObjectStatus.ERROR:
                    draw_entity_manually(ax, entity, color=COLOR_ERROR_OVERLAY, linewidth=2.5)
                elif status == ObjectStatus.WARNING:
                    draw_entity_manually(ax, entity, color=COLOR_WARNING_OVERLAY, linewidth=2.5)
                continue
            else:
                if status == ObjectStatus.ERROR:
                    color, linewidth = '#FF0000', 2.0
                elif status == ObjectStatus.WARNING:
                    color, linewidth = '#FF8800', 2.0
                else:
                    color, linewidth = '#000000', 1.5
            
            draw_entity_manually(ax, entity, color=color, linewidth=linewidth)
        else:
            draw_entity_manually(ax, entity, color='#CCCCCC', linewidth=1.0)


def draw_markers(ax: Any, objects_data: List[DXFObject], font_size_multiplier: float,
                show_chains: bool, chain_colors: Dict):
    """Рисует маркеры номеров объектов."""
    valid_objects = [obj for obj in objects_data if obj.center[0] != 0 or obj.center[1] != 0]
    
    if not valid_objects:
        return
    
    all_x = [obj.center[0] for obj in valid_objects]
    all_y = [obj.center[1] for obj in valid_objects]
    
    if all_x and all_y:
        drawing_size = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
        if drawing_size > 0:
            base_font_size = max(int(drawing_size * DRAWING_FONT_SCALE_FACTOR), DRAWING_FONT_MIN_SIZE)
            font_size = int(base_font_size * font_size_multiplier)
            offset_distance = drawing_size * 0.015
        else:
            font_size = int(8 * font_size_multiplier)
            offset_distance = 10
    else:
        font_size = int(8 * font_size_multiplier)
        offset_distance = 10
    
    for obj in objects_data:
        if obj.entity is None:
            continue
        
        x, y = get_entity_center_with_offset(obj.entity, offset_distance)
        if x == 0 and y == 0:
            continue
        
        if show_chains and obj.chain_id > 0:
            marker_color = '#FFFFFF'
            marker_bg = chain_colors.get(obj.chain_id, '#000000')
        elif obj.status == ObjectStatus.ERROR:
            marker_color, marker_bg = MARKER_COLOR_ERROR, MARKER_BG_ERROR
        elif obj.status == ObjectStatus.WARNING:
            marker_color, marker_bg = MARKER_COLOR_WARNING, MARKER_BG_WARNING
        else:
            marker_color, marker_bg = MARKER_COLOR_NORMAL, MARKER_BG_NORMAL
        
        ax.annotate(
            str(obj.num), (x, y),
            fontsize=font_size, fontweight='bold', ha='center', va='center',
            color=marker_color, zorder=101,
            bbox=dict(boxstyle='circle,pad=0.35', facecolor=marker_bg,
                     edgecolor='white', linewidth=1.5, alpha=0.95)
        )


def add_legend(ax: Any, show_chains: bool, use_original_colors: bool, chain_colors: Dict):
    """Добавляет легенду."""
    from matplotlib.patches import Patch
    
    if show_chains:
        legend_elements = [
            Patch(facecolor='#888888', edgecolor='black', label=f'Цепей найдено: {len(chain_colors)}')
        ]
    elif not use_original_colors:
        legend_elements = [
            Patch(facecolor='#000000', edgecolor='black', label='✓ Нормальные (учтены)'),
            Patch(facecolor='#FF8800', edgecolor='black', label='⚠ Коррекция (учтены)'),
            Patch(facecolor='#FF0000', edgecolor='black', label='✗ Ошибки (исключены)'),
            Patch(facecolor='#CCCCCC', edgecolor='black', label='- Пропущены'),
        ]
    else:
        return
    
    ax.legend(handles=legend_elements, loc='lower left', fontsize=10,
             framealpha=0.95, edgecolor='black', fancybox=True, shadow=True)


def visualize_dxf_with_status_indicators(
    doc: Any, 
    objects_data: List[DXFObject],
    collector: ErrorCollector,
    show_markers: bool = True,
    font_size_multiplier: float = 1.0,
    use_original_colors: bool = False,
    show_chains: bool = False
) -> Tuple[Optional[Any], Optional[str]]:
    """
    РЕФАКТОРИНГ: Разбито на подфункции для читаемости.
    
    Создает визуализацию с цветовой индикацией статуса объектов.
    """
    try:
        fig, ax = setup_figure()
        msp = doc.modelspace()
        
        # Генерация цветов для цепей
        chain_colors = {}
        if show_chains:
            unique_chains = set(obj.chain_id for obj in objects_data if obj.chain_id > 0)
            import colorsys
            for i, chain_id in enumerate(sorted(unique_chains)):
                hue = i / max(len(unique_chains), 1)
                rgb = colorsys.hsv_to_rgb(hue, 0.7, 0.9)
                chain_colors[chain_id] = '#{:02x}{:02x}{:02x}'.format(
                    int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255)
                )
        
        # Рисуем entity
        draw_entities(ax, msp, objects_data, use_original_colors, show_chains, chain_colors)
        
        # Рисуем маркеры
        if show_markers and objects_data:
            draw_markers(ax, objects_data, font_size_multiplier, show_chains, chain_colors)
            add_legend(ax, show_chains, use_original_colors, chain_colors)
        
        ax.set_aspect('equal')
        ax.autoscale()
        ax.margins(0.05)
        ax.axis('off')
        
        title_text = f"Анализ чертежа | Объектов обработано: {len(objects_data)}"
        if collector.has_errors:
            title_text += f" | Ошибок: {len(collector.errors)}"
        if collector.warnings:
            title_text += f" | Предупреждений: {len(collector.warnings)}"
        
        fig.suptitle(title_text, fontsize=12, fontweight='bold')
        plt.tight_layout(pad=0.3)
        
        return fig, None
    
    except MemoryError as e:
        error_msg = f"Недостаточно памяти для визуализации: {e}"
        logger.error(error_msg)
        return None, error_msg
    
    except Exception as e:
        error_msg = f"Ошибка визуализации: {e}"
        logger.error(error_msg)
        return None, error_msg


def draw_entity_manually(ax: Any, entity: Any, color: str = '#000000', 
                         linewidth: float = 1.5, use_original_color: bool = False) -> bool:
    """Рисует объект вручную с указанным цветом."""
    entity_type = entity.dxftype()
    
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
                circle = plt.Circle((x, y), radius, fill=False, edgecolor=color, linewidth=linewidth, zorder=1)
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
            
            if start_angle_norm <= end_angle_norm:
                angle_diff = end_angle_norm - start_angle_norm
            else:
                angle_diff = 360 - (start_angle_norm - end_angle_norm)
            
            if angle_diff < 0.001:
                return False
            
            # НОВОЕ: Векторизация через numpy
            theta = np.linspace(start_angle_norm, start_angle_norm + angle_diff, ARC_RENDER_SEGMENTS)
            xs = x + radius * np.cos(np.radians(theta))
            ys = y + radius * np.sin(np.radians(theta))
            ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
            return True
        
        elif entity_type == 'LWPOLYLINE':
            try:
                with entity.points('xy') as points:
                    pts = [(safe_float(p[0]), safe_float(p[1])) for p in points]
                    pts = [(x, y) for x, y in pts if x is not None and y is not None]
                    
                    if len(pts) >= 2:
                        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                        
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
                    xs, ys = [p[0] for p in points], [p[1] for p in points]
                    
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
                    if i >= SPLINE_RENDER_MAX_POINTS:
                        break
                    x, y = safe_float(pt[0]), safe_float(pt[1])
                    if x is not None and y is not None:
                        points.append((x, y))
                
                if len(points) >= 2:
                    xs, ys = [p[0] for p in points], [p[1] for p in points]
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
                a = math.sqrt(safe_float(major_axis.x)**2 + safe_float(major_axis.y)**2)
                b = a * ratio
                angle = math.atan2(safe_float(major_axis.y), safe_float(major_axis.x))
                
                if a <= 0 or b <= 0:
                    return False
                
                # НОВОЕ: Векторизация через numpy
                t = np.linspace(0, 2 * np.pi, 101)
                xs = x + a * np.cos(t) * np.cos(angle) - b * np.sin(t) * np.sin(angle)
                ys = y + a * np.cos(t) * np.sin(angle) + b * np.sin(t) * np.cos(angle)
                ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
                return True
            except (TypeError, ValueError) as e:
                logger.debug(f"Ошибка при рисовании ELLIPSE: {e}")
                return False
    
    except Exception as e:
        logger.debug(f"Неожиданная ошибка при рисовании: {e}")
        return False
    
    return False


# ==================== БЛОК ОТОБРАЖЕНИЯ ОШИБОК ====================

def show_error_report(collector: ErrorCollector):
    """Показывает отчёт об ошибках в Streamlit UI."""
    if not collector.has_issues:
        st.success("✅ Обработка завершена без ошибок")
        return
    
    if collector.has_errors:
        st.error(f"⚠️ Обнаружены ошибки при обработке: {collector.get_summary()}")
    else:
        st.warning(f"⚠️ Обработка завершена с предупреждениями: {collector.get_summary()}")
    
    with st.expander(f"🔍 Подробный отчёт о проблемах ({collector.total_issues} записей)", expanded=False):
        tab_labels = []
        
        if collector.errors:
            tab_labels.append(f"🔴 Ошибки ({len(collector.errors)})")
        if collector.warnings:
            tab_labels.append(f"🟡 Предупреждения ({len(collector.warnings)})")
        if collector.skipped:
            tab_labels.append(f"⚪ Пропущено ({len(collector.skipped)})")
        
        tab_labels.append("📋 Все проблемы")
        
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
            st.warning(f"⚠️ **Итоговая длина реза может быть занижена** из-за {len(collector.errors)} объектов с ошибками.")


# ==================== STREAMLIT ИНТЕРФЕЙС ====================

st.set_page_config(
    page_title="Анализатор Чертежей CAD Pro v24.1",
    page_icon="📐",
    layout="wide"
)

st.title("📐 Анализатор Чертежей CAD Pro v24.1")
st.markdown("**Профессиональный расчет длины реза для станков ЧПУ и лазерной резки**")

with st.expander("ℹ️ Информация о подсчёте врезок"):
    st.markdown("""
    ### 📍 Как считаются врезки (точки прожига):
    
    **Что такое врезка:**
    - Это точка, где лазер включается для начала резки
    - Каждая **связанная цепь объектов** = **1 врезка**
    
    **Примеры:**
    - 1 окружность = 1 врезка ✅
    - 4 LINE, образующих прямоугольник = 1 врезка ✅ (если концы совпадают)
    - 4 несвязанных LINE = 4 врезки ✅
    - 2 дуги, образующих окружность = 1 врезка ✅ (если зазор < допуска)
    
    **Алгоритм:**
    1. Замкнутые объекты (CIRCLE, замкнутые полилинии) = изолированные цепи
    2. Для открытых объектов строим граф связности по близости концов
    3. Используется допуск 0.1 мм (настраивается)
    4. Каждая найденная цепь = 1 врезка
    
    **Типы цепей:**
    - **Замкнутые** - полные контуры (окружности, замкнутые полилинии)
    - **Открытые группы** - несколько связанных объектов
    - **Изолированные** - одиночные незамкнутые объекты
    """)

with st.expander("ℹ️ Информация о цветах"):
    st.markdown("""
    ### Режимы отображения чертежа:
    
    **Режим 1: Исходные цвета из файла (по умолчанию)**
    - Линии отображаются теми цветами, которые установлены в DXF файле
    - Ошибки выделяются красной обводкой поверх исходного цвета
    - Предупреждения выделяются оранжевой обводкой
    - Легенда НЕ отображается (чертёж чистый)
    
    **Режим 2: Индикация ошибок**
    - Чёрный = Нормальные объекты (учтены)
    - Оранжевый = Предупреждения (учтены с коррекцией)
    - Красный = Ошибки (исключены)
    - Серый = Пропущены
    - Легенда отображается в левом нижнем углу
    
    **Режим 3: Визуализация цепей**
    - Каждая цепь выделена уникальным цветом
    - Помогает увидеть связанные объекты
    - Удобно для проверки корректности анализа
    """)

st.markdown("---")

uploaded_file = st.file_uploader("📂 Загрузите чертеж в формате DXF", type=["dxf"])

if uploaded_file is not None:
    file_size_mb = uploaded_file.size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        st.error(f"❌ Файл слишком большой: {file_size_mb:.1f} МБ (максимум: {MAX_FILE_SIZE_MB} МБ)")
        st.stop()
    
    collector = ErrorCollector()
    
    with st.spinner('⏳ Обработка чертежа...'):
        try:
            with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
                tmp.write(uploaded_file.getbuffer())
                temp_path = tmp.name
            
            try:
                doc = ezdxf.readfile(temp_path)
                dxf_version = doc.dxfversion
                
                if dxf_version < 'AC1018':
                    collector.add_warning('FILE', 0, f"Старая версия DXF: {dxf_version}", "DXFVersionWarning")
                
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
            color_stats: Dict[int, Dict[str, Any]] = {}
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
                
                length, status, issue_desc = calc_entity_safe(entity_type, entity, real_object_num, calculators, collector)
                
                if length < MIN_LENGTH:
                    if entity_type not in ZERO_LENGTH_TYPES:
                        collector.add_skipped(entity_type, real_object_num, f"Нулевая длина: {length:.6f}")
                    continue
                
                calc_object_num += 1
                center = get_entity_center(entity)
                is_closed = check_is_closed(entity)
                
                dxf_obj = DXFObject(
                    num=calc_object_num, real_num=real_object_num, entity_type=entity_type,
                    length=length, center=center, entity=entity, layer=layer, color=color,
                    original_color=color, status=status, original_length=length,
                    issue_description=issue_desc, is_closed=is_closed, chain_id=-1
                )
                
                objects_data.append(dxf_obj)
                
                if entity_type not in stats:
                    stats[entity_type] = {'count': 0, 'length': 0.0, 'items': []}
                
                stats[entity_type]['count'] += 1
                stats[entity_type]['length'] += length
                stats[entity_type]['items'].append({'num': calc_object_num, 'length': length})
                
                if color not in color_stats:
                    color_stats[color] = {
                        'count': 0, 'length': 0.0,
                        'color_name': get_color_name(color),
                        'hex_color': get_aci_color(color)
                    }
                
                color_stats[color]['count'] += 1
                color_stats[color]['length'] += length
                total_length += length
            
            piercing_count, piercing_details = count_piercings_advanced(objects_data, collector, tolerance=PIERCING_TOLERANCE)
            piercing_stats = get_piercing_statistics(objects_data)
            
            # ==================== ВЫВОД ====================
            show_error_report(collector)
            
            if not objects_data:
                st.warning("⚠️ В чертеже не найдено объектов для расчета")
                if skipped_types:
                    st.info(f"Пропущено: {', '.join(sorted(skipped_types))}")
            else:
                if collector.has_errors:
                    st.success(f"✅ Обработано: **{len(objects_data)}** объектов (🔴 {len(collector.errors)} ошибок)")
                else:
                    st.success(f"✅ Обработано: **{len(objects_data)}** объектов")
                
                st.markdown("### 📏 Итоговая длина реза:")
                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    st.metric("Миллиметры", f"{total_length:.2f}")
                with col2:
                    st.metric("Сантиметры", f"{total_length/10:.2f}")
                with col3:
                    st.metric("Метры", f"{total_length/1000:.4f}")
                with col4:
                    st.metric("Объектов", f"{len(objects_data)}")
                with col5:
                    st.metric("🔵 Врезок (цепей)", f"{piercing_count}")
                
                st.markdown("### 📍 Статистика врезок (анализ связности):")
                
                col_p1, col_p2, col_p3, col_p4, col_p5 = st.columns(5)
                
                with col_p1:
                    st.metric("🔵 Всего цепей", piercing_details['total'], help="Количество связанных групп объектов")
                with col_p2:
                    st.metric("🔴 Замкнутые", piercing_details['closed_objects'], help="Полные контуры (окружности, замкнутые полилинии)")
                with col_p3:
                    st.metric("🔗 Открытые группы", piercing_details['open_chains'], help="Несколько связанных открытых объектов")
                with col_p4:
                    st.metric("➡️ Изолированные", piercing_details['isolated_objects'], help="Одиночные открытые объекты")
                with col_p5:
                    st.metric("⚙️ Допуск", f"{piercing_details['tolerance_used']} мм", help="Точки ближе этого значения считаются соединёнными")
                
                if piercing_details['chains']:
                    with st.expander(f"🔍 Детали цепей ({len(piercing_details['chains'])} шт.)", expanded=False):
                        chains_rows = []
                        for chain_info in piercing_details['chains']:
                            chain_type_emoji = {
                                'closed': '🔴',
                                'open': '🔗',
                                'isolated': '➡️'
                            }.get(chain_info['type'], '❓')
                            
                            chains_rows.append({
                                'ID': chain_info['chain_id'],
                                'Тип': f"{chain_type_emoji} {chain_info['type']}",
                                'Объектов': chain_info['objects_count'],
                                'Номера объектов': ', '.join(map(str, chain_info['objects'])),
                                'Типы': ', '.join(chain_info['entity_types']),
                                'Длина (мм)': round(chain_info['total_length'], 2)
                            })
                        
                        df_chains = pd.DataFrame(chains_rows)
                        st.dataframe(df_chains, use_container_width=True, hide_index=True)
                        
                        csv_chains = df_chains.to_csv(index=False, encoding='utf-8-sig')
                        st.download_button(
                            label="📥 Скачать детали цепей (CSV)",
                            data=csv_chains,
                            file_name="chains_details.csv",
                            mime="text/csv"
                        )
                
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
                
                with col_right:
                    st.markdown("### 🎨 Чертеж с цветовой индикацией")
                    
                    display_mode = st.radio("Режим отображения:", options=["Исходные цвета", "Индикация ошибок", "Визуализация цепей"], horizontal=True)
                    
                    use_original_colors = display_mode == "Исходные цвета"
                    show_chains = display_mode == "Визуализация цепей"
                    
                    show_markers = st.checkbox("🔴 Показать маркеры", value=True)
                    
                    if show_markers:
                        font_size_multiplier = st.slider("📏 Размер шрифта", min_value=0.5, max_value=3.0, value=1.0, step=0.1)
                    else:
                        font_size_multiplier = 1.0
                    
                    with st.spinner('Генерация визуализации...'):
                        fig, error_msg = visualize_dxf_with_status_indicators(
                            doc, objects_data, collector, show_markers, font_size_multiplier, use_original_colors, show_chains
                        )
                        
                        if fig is not None:
                            st.pyplot(fig, use_container_width=True)
                            if show_chains:
                                st.info(f"💡 Каждый цвет = отдельная цепь. Найдено {piercing_count} цепей.")
                        else:
                            if error_msg:
                                st.error(f"❌ {error_msg}")
                            else:
                                st.error("❌ Не удалось создать визуализацию")
        
        except Exception as e:
            collector.add_error('SYSTEM', 0, f"Критическая ошибка: {e}", type(e).__name__)
            show_error_report(collector)
            
            import traceback
            with st.expander("🔍 Трассировка ошибки"):
                st.code(traceback.format_exc())

else:
    st.info("👈 Загрузите DXF-чертеж для начала")
    st.markdown("""
    ### 📝 О версии v24.1:
    
    **ГЛАВНЫЕ УЛУЧШЕНИЯ:**
    - ✅ **ИСПРАВЛЕНЫ критические баги в статистике врезок**
    - ✅ **Оптимизация производительности через KDTree** (до 100x быстрее для больших файлов)
    - ✅ **Векторизация через NumPy** (до 10x быстрее рендеринг)
    - ✅ **Рефакторинг кода** (функции разбиты, убраны дубликаты)
    - ✅ **Использование collections.deque** вместо list для O(1) операций
    - ✅ **Кэширование endpoints создаётся один раз**
    - ✅ **Удалены неиспользуемые импорты**
    - ✅ **Magic numbers вынесены в константы**
    
    **ВСЕ ФУНКЦИИ v24.0:**
    - ✅ Правильный подсчёт врезок с анализом связности
    - ✅ Алгоритм находит связанные объекты (граф смежности)
    - ✅ Прямоугольник из 4 LINE = 1 врезка (не 4!)
    """)

with st.expander("### 🎯 Новое в v24.1:"):
    st.markdown("""
    ✅ **ИСПРАВЛЕНЫ критические баги:**
    - Правильный подсчёт открытых цепей (без некорректного вычитания)
    - Правильная классификация типов цепей (анализ после сбора всех данных)
    - Удален бесполезный `finally: pass`
    
    ✅ **Оптимизация производительности:**
    - KDTree для поиска соседей O(log N) вместо O(N²)
    - Endpoints кэш создаётся один раз
    - `collections.deque` вместо `list` для очереди
    - Векторизация вычислений через NumPy
    
    ✅ **Улучшение качества кода:**
    - Удалены неиспользуемые импорты
    - Magic numbers вынесены в константы
    - Создана утилита `extract_polyline_points()`
    - Визуализация разбита на подфункции
    
    ✅ **Все функции v24.0 сохранены**
    """)

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; font-size: 12px;'>
    ✂️ CAD Analyzer Pro v24.1 | Лицензия MIT | ОПТИМИЗИРОВАННАЯ ВЕРСИЯ
</div>
""", unsafe_allow_html=True)
