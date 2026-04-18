import subprocess
import sys
import os
import math
import warnings
import logging
import io
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import streamlit as st

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

# ==================== СБОР ОШИБОК ====================

class ErrorCollector:
    """
    Собирает ошибки во время обработки.
    Позволяет показать пользователю что именно не посчиталось.
    """
    
    def __init__(self):
        self.errors = []        # Критические ошибки
        self.warnings = []      # Предупреждения
        self.skipped = []       # Пропущенные объекты
    
    def add_error(self, entity_type, entity_num, error_msg, error_class=""):
        """Добавляет критическую ошибку."""
        self.errors.append({
            'Тип объекта': entity_type,
            '№ объекта': entity_num,
            'Описание': error_msg,
            'Класс ошибки': error_class,
            'Серьёзность': '🔴 Ошибка'
        })
        logger.error(f"[{entity_type}] #{entity_num}: {error_msg}")
    
    def add_warning(self, entity_type, entity_num, warning_msg, error_class=""):
        """Добавляет предупреждение."""
        self.warnings.append({
            'Тип объекта': entity_type,
            '№ объекта': entity_num,
            'Описание': warning_msg,
            'Класс ошибки': error_class,
            'Серьёзность': '🟡 Предупреждение'
        })
        logger.warning(f"[{entity_type}] #{entity_num}: {warning_msg}")
    
    def add_skipped(self, entity_type, entity_num, reason):
        """Добавляет пропущенный объект."""
        self.skipped.append({
            'Тип объекта': entity_type,
            '№ объекта': entity_num,
            'Причина': reason,
            'Серьёзность': '⚪ Пропущен'
        })
        logger.info(f"[{entity_type}] #{entity_num}: пропущен — {reason}")
    
    @property
    def has_issues(self):
        """Есть ли какие-либо проблемы."""
        return bool(self.errors or self.warnings or self.skipped)
    
    @property
    def total_issues(self):
        """Общее количество проблем."""
        return len(self.errors) + len(self.warnings) + len(self.skipped)
    
    def get_all_as_dataframe(self):
        """Возвращает все проблемы единым DataFrame."""
        all_issues = []
        
        for e in self.errors:
            all_issues.append(e)
        for w in self.warnings:
            all_issues.append(w)
        for s in self.skipped:
            row = {
                'Тип объекта': s['Тип объекта'],
                '№ объекта': s['№ объекта'],
                'Описание': s['Причина'],
                'Класс ошибки': '—',
                'Серьёзность': s['Серьёзность']
            }
            all_issues.append(row)
        
        if all_issues:
            return pd.DataFrame(all_issues)
        return pd.DataFrame()
    
    def get_summary(self):
        """Краткая сводка по проблемам."""
        parts = []
        if self.errors:
            parts.append(f"🔴 Ошибок: {len(self.errors)}")
        if self.warnings:
            parts.append(f"🟡 Предупреждений: {len(self.warnings)}")
        if self.skipped:
            parts.append(f"⚪ Пропущено: {len(self.skipped)}")
        return " | ".join(parts) if parts else "✅ Проблем не обнаружено"


def validate_length_result(length, entity_type, entity_num, collector):
    """
    Проверяет корректность вычисленной длины.
    Возвращает (валидная_длина, успех).
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
    if math.isnan(length):
        collector.add_error(
            entity_type, entity_num,
            "Результат вычисления: NaN (не число). "
            "Возможно повреждены координаты объекта",
            "ValueError"
        )
        return 0.0, False
    
    # Проверка на бесконечность
    if math.isinf(length):
        collector.add_error(
            entity_type, entity_num,
            "Результат вычисления: Infinity. "
            "Возможно деление на ноль в геометрии",
            "ZeroDivisionError"
        )
        return 0.0, False
    
    # Проверка на отрицательное значение
    if length < 0:
        collector.add_warning(
            entity_type, entity_num,
            f"Отрицательная длина: {length:.4f}. "
            f"Используется абсолютное значение",
            "GeometryWarning"
        )
        return abs(length), True
    
    # Проверка на аномально большое значение (> 1 000 000 мм = 1 км)
    if length > 1_000_000:
        collector.add_warning(
            entity_type, entity_num,
            f"Аномально большая длина: {length:.2f} мм ({length/1000:.1f} м). "
            f"Проверьте единицы измерения чертежа",
            "ScaleWarning"
        )
        return length, True
    
    return length, True


def calc_entity_safe(entity_type, entity, entity_num, calculators, collector):
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
        
        return validated_length
    
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
    
    except Exception as e:
        # Последний рубеж - ловим всё остальное но ЗАПИСЫВАЕМ
        collector.add_error(
            entity_type, entity_num,
            f"Неожиданная ошибка: {e}",
            type(e).__name__
        )
        return 0.0


# ==================== РАСЧЁТ ДЛИНЫ ====================

def calc_line_length(entity):
    """LINE: прямая линия."""
    start = entity.dxf.start
    end = entity.dxf.end
    return math.hypot(end.x - start.x, end.y - start.y)


def calc_circle_length(entity):
    """CIRCLE: окружность."""
    return 2 * math.pi * entity.dxf.radius


def calc_arc_length(entity):
    """ARC: дуга окружности."""
    radius = entity.dxf.radius
    start_angle = math.radians(entity.dxf.start_angle)
    end_angle = math.radians(entity.dxf.end_angle)
    angle = end_angle - start_angle
    if angle < 0:
        angle += 2 * math.pi
    return radius * angle


def calc_ellipse_length(entity):
    """ELLIPSE: эллипс или его дуга."""
    major_axis = entity.dxf.major_axis
    ratio = entity.dxf.ratio
    start_param = entity.dxf.start_param
    end_param = entity.dxf.end_param
    
    a = math.sqrt(major_axis.x**2 + major_axis.y**2 + major_axis.z**2)
    b = a * ratio
    
    if a <= 0 or b <= 0:
        raise ValueError(f"Некорректные полуоси эллипса: a={a}, b={b}")
    
    angle_span = end_param - start_param
    if angle_span < 0:
        angle_span += 2 * math.pi
    
    if abs(angle_span - 2 * math.pi) < 0.01:
        h = ((a - b) ** 2) / ((a + b) ** 2)
        return math.pi * (a + b) * (1 + 3*h / (10 + math.sqrt(4 - 3*h)))
    
    N = 1000
    length = 0.0
    for i in range(N):
        t1 = start_param + angle_span * i / N
        t2 = start_param + angle_span * (i + 1) / N
        x1, y1 = a * math.cos(t1), b * math.sin(t1)
        x2, y2 = a * math.cos(t2), b * math.sin(t2)
        length += math.hypot(x2 - x1, y2 - y1)
    
    return length


def calc_lwpolyline_length(entity):
    """LWPOLYLINE: лёгкая полилиния с bulge."""
    points = []
    with entity.points('xyb') as pts:
        for p in pts:
            points.append(p)
    
    if len(points) < 2:
        return 0.0
    
    length = 0.0
    
    # Обрабатываем сегменты
    segments = list(range(len(points) - 1))
    if entity.closed:
        segments.append(len(points) - 1)
    
    for i in segments:
        next_i = (i + 1) % len(points)
        
        x1 = float(points[i][0])
        y1 = float(points[i][1])
        x2 = float(points[next_i][0])
        y2 = float(points[next_i][1])
        
        bulge = float(points[i][2]) if len(points[i]) >= 3 else 0.0
        
        # Защита от некорректного bulge
        if not math.isfinite(bulge):
            bulge = 0.0
        
        chord = math.hypot(x2 - x1, y2 - y1)
        
        if chord < 1e-10:
            continue
        
        if abs(bulge) < 0.0001:
            length += chord
        else:
            angle = 4 * math.atan(abs(bulge))
            sin_half = math.sin(angle / 2)
            
            # Защита от деления на ноль
            if abs(sin_half) < 1e-10:
                length += chord
            else:
                radius = chord / (2 * sin_half)
                arc_len = radius * angle
                
                # Защита от аномальных значений
                if arc_len > chord * 1000 or not math.isfinite(arc_len):
                    length += chord
                else:
                    length += arc_len
    
    return length


def calc_polyline_length(entity):
    """POLYLINE: полилиния."""
    points = list(entity.points())
    
    if len(points) < 2:
        return 0.0
    
    length = sum(
        math.hypot(
            points[i+1][0] - points[i][0],
            points[i+1][1] - points[i][1]
        )
        for i in range(len(points) - 1)
    )
    
    if entity.is_closed:
        length += math.hypot(
            points[0][0] - points[-1][0],
            points[0][1] - points[-1][1]
        )
    
    return length


def calc_spline_length(entity):
    """SPLINE: сплайн."""
    points = list(entity.flattening(0.001))
    
    if len(points) < 2:
        return 0.0
    
    return sum(
        math.hypot(
            points[i+1][0] - points[i][0],
            points[i+1][1] - points[i][1]
        )
        for i in range(len(points) - 1)
    )


def calc_point(entity):
    """POINT: точка."""
    return 0.1


def calc_mline_length(entity):
    """MLINE: мультилиния."""
    return 0.0


def calc_insert_length(entity):
    """INSERT: блок."""
    return 0.0


def calc_text_length(entity):
    """TEXT: текст."""
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
    'POINT':      calc_point,
    'MLINE':      calc_mline_length,
    'INSERT':     calc_insert_length,
    'TEXT':       calc_text_length,
}

# ==================== ЦЕНТР ОБЪЕКТА С ПЕРПЕНДИКУЛЯРНЫМ СМЕЩЕНИЕМ ====================

def get_entity_center_with_offset(entity, offset_distance, collector=None, entity_num=0):
    """
    Возвращает центр объекта СО СМЕЩЕНИЕМ от линии.
    """
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            s, e = entity.dxf.start, entity.dxf.end
            center_x = (s.x + e.x) / 2
            center_y = (s.y + e.y) / 2
            
            dx = e.x - s.x
            dy = e.y - s.y
            line_length = math.hypot(dx, dy)
            
            if line_length > 1e-10:
                perp_x = -dy / line_length
                perp_y = dx / line_length
                return (center_x + perp_x * offset_distance,
                        center_y + perp_y * offset_distance)
            
            return (center_x, center_y)
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = entity.dxf.radius
            return (center.x + radius + offset_distance, center.y)
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = math.radians(entity.dxf.start_angle)
            end_angle = math.radians(entity.dxf.end_angle)
            
            mid_angle = (start_angle + end_angle) / 2
            if end_angle < start_angle:
                mid_angle += math.pi
            
            return (
                center.x + (radius + offset_distance) * math.cos(mid_angle),
                center.y + (radius + offset_distance) * math.sin(mid_angle)
            )
        
        elif entity_type == 'ELLIPSE':
            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            a = math.sqrt(major_axis.x**2 + major_axis.y**2)
            return (center.x + a + offset_distance, center.y)
        
        elif entity_type == 'POINT':
            loc = entity.dxf.location
            return (loc.x + offset_distance, loc.y + offset_distance)
        
        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
            if entity_type == 'LWPOLYLINE':
                with entity.points('xy') as pts:
                    points = list(pts)
            else:
                points = [(p[0], p[1]) for p in entity.points()]
            
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                center_x = (min(xs) + max(xs)) / 2
                center_y = (min(ys) + max(ys)) / 2
                
                dx = points[1][0] - points[0][0]
                dy = points[1][1] - points[0][1]
                seg_length = math.hypot(dx, dy)
                
                if seg_length > 1e-10:
                    perp_x = -dy / seg_length
                    perp_y = dx / seg_length
                    return (
                        center_x + perp_x * offset_distance,
                        center_y + perp_y * offset_distance
                    )
                
                return (center_x, center_y)
        
        elif entity_type == 'SPLINE':
            points = list(entity.flattening(0.1))
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                center_x = (min(xs) + max(xs)) / 2
                center_y = (min(ys) + max(ys)) / 2
                
                mid_idx = len(points) // 2
                if mid_idx + 1 < len(points):
                    dx = points[mid_idx + 1][0] - points[mid_idx][0]
                    dy = points[mid_idx + 1][1] - points[mid_idx][1]
                    seg_length = math.hypot(dx, dy)
                    
                    if seg_length > 1e-10:
                        perp_x = -dy / seg_length
                        perp_y = dx / seg_length
                        return (
                            center_x + perp_x * offset_distance,
                            center_y + perp_y * offset_distance
                        )
                
                return (center_x, center_y)
        
        elif entity_type == 'INSERT':
            pos = entity.dxf.insert
            return (pos.x + offset_distance, pos.y + offset_distance)
    
    except AttributeError as e:
        if collector:
            collector.add_warning(
                entity_type, entity_num,
                f"Не удалось определить центр объекта: {e}. "
                f"Маркер размещён в (0,0)",
                "AttributeError"
            )
    except Exception as e:
        if collector:
            collector.add_warning(
                entity_type, entity_num,
                f"Ошибка позиционирования маркера: {e}",
                type(e).__name__
            )
    
    return (0, 0)


# ==================== ВИЗУАЛИЗАЦИЯ ====================

def draw_entity_manually(ax, entity, collector=None):
    """Рисует объект вручную ЧЕРНЫМ цветом."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start = entity.dxf.start
            end = entity.dxf.end
            ax.plot([start.x, end.x], [start.y, end.y],
                   'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = entity.dxf.radius
            circle = plt.Circle(
                (center.x, center.y), radius,
                fill=False, edgecolor='black', linewidth=1.5, zorder=1
            )
            ax.add_patch(circle)
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = entity.dxf.start_angle
            end_angle = entity.dxf.end_angle
            
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
            
            x = [center.x + radius * math.cos(math.radians(t)) for t in theta]
            y = [center.y + radius * math.sin(math.radians(t)) for t in theta]
            ax.plot(x, y, 'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'LWPOLYLINE':
            with entity.points('xy') as points:
                pts = list(points)
                if len(pts) >= 2:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    if entity.closed:
                        xs.append(xs[0])
                        ys.append(ys[0])
                    ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'POLYLINE':
            points = list(entity.points())
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                if entity.is_closed:
                    xs.append(xs[0])
                    ys.append(ys[0])
                ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'SPLINE':
            points = list(entity.flattening(0.01))
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'ELLIPSE':
            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            ratio = entity.dxf.ratio
            
            a = math.sqrt(major_axis.x**2 + major_axis.y**2)
            b = a * ratio
            angle = math.atan2(major_axis.y, major_axis.x)
            
            t = [i * 2 * math.pi / 100 for i in range(101)]
            x = [
                center.x + a * math.cos(ti) * math.cos(angle)
                         - b * math.sin(ti) * math.sin(angle)
                for ti in t
            ]
            y = [
                center.y + a * math.cos(ti) * math.sin(angle)
                         + b * math.sin(ti) * math.cos(angle)
                for ti in t
            ]
            ax.plot(x, y, 'k-', linewidth=1.5, zorder=1)
    
    except AttributeError as e:
        if collector:
            collector.add_warning(
                entity_type, 0,
                f"Объект не нарисован — отсутствует атрибут: {e}",
                "AttributeError"
            )
    except Exception as e:
        if collector:
            collector.add_warning(
                entity_type, 0,
                f"Объект не нарисован — ошибка отрисовки: {e}",
                type(e).__name__
            )


def visualize_dxf_with_numbers(doc, objects_data, show_markers=True,
                                font_size_multiplier=1.0, collector=None):
    """Создает визуализацию с номерами РЯДОМ с линиями."""
    try:
        fig, ax = plt.subplots(figsize=(18, 14), dpi=100)
        fig.patch.set_facecolor('#E5E5E5')
        ax.set_facecolor('#F0F0F0')
        
        msp = doc.modelspace()
        
        # Рисуем все объекты
        for entity in msp:
            draw_entity_manually(ax, entity, collector)
        
        if show_markers:
            all_x = [obj['center'][0] for obj in objects_data if obj['center'][0] != 0]
            all_y = [obj['center'][1] for obj in objects_data if obj['center'][1] != 0]
            
            if all_x and all_y:
                drawing_size = max(
                    max(all_x) - min(all_x),
                    max(all_y) - min(all_y)
                )
                base_font_size = max(int(drawing_size * 0.003), 7)
                font_size = int(base_font_size * font_size_multiplier)
                offset_distance = drawing_size * 0.015
            else:
                font_size = int(8 * font_size_multiplier)
                offset_distance = 10
            
            # Строим словарь entity по центру для быстрого поиска
            entity_map = {}
            for ent in msp:
                if ent.dxftype() in calculators:
                    cx, cy = get_entity_center_with_offset(ent, 0, collector)
                    key = (round(cx, 2), round(cy, 2))
                    entity_map[key] = ent
            
            # Рисуем маркеры
            for obj in objects_data:
                cx, cy = obj['center']
                key = (round(cx, 2), round(cy, 2))
                
                entity = entity_map.get(key)
                
                if entity:
                    x, y = get_entity_center_with_offset(
                        entity, offset_distance, collector, obj['num']
                    )
                else:
                    x, y = cx, cy
                    if collector:
                        collector.add_warning(
                            obj['type'], obj['num'],
                            "Не найден объект для размещения маркера. "
                            "Маркер размещён в центре bounding box",
                            "LookupWarning"
                        )
                
                if x == 0 and y == 0:
                    continue
                
                ax.annotate(
                    str(obj['num']),
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
        if collector:
            collector.add_error(
                'VISUALIZATION', 0,
                "Недостаточно памяти для создания визуализации. "
                "Попробуйте уменьшить размер файла",
                "MemoryError"
            )
        return None
    
    except Exception as e:
        if collector:
            collector.add_error(
                'VISUALIZATION', 0,
                f"Критическая ошибка визуализации: {e}",
                type(e).__name__
            )
        return None


# ==================== БЛОК ОТОБРАЖЕНИЯ ОШИБОК В UI ====================

def show_error_report(collector):
    """
    Показывает отчёт об ошибках в Streamlit UI.
    Вызывается после обработки файла.
    """
    if not collector.has_issues:
        st.success("✅ Обработка завершена без ошибок")
        return
    
    # Определяем цвет и иконку блока
    if collector.errors:
        # Есть критические ошибки
        st.error(
            f"⚠️ Обнаружены проблемы при обработке: "
            f"{collector.get_summary()}"
        )
    else:
        # Только предупреждения
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
        tabs = []
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
                df_errors = pd.DataFrame(collector.errors)
                st.dataframe(df_errors, use_container_width=True, hide_index=True)
                
                st.info(
                    "💡 Эти объекты исключены из итоговой длины реза. "
                    "Проверьте файл в CAD-редакторе."
                )
            tab_idx += 1
        
        if collector.warnings:
            with tabs[tab_idx]:
                st.markdown("**Предупреждения** — объекты обработаны с коррекцией:")
                df_warnings = pd.DataFrame(collector.warnings)
                st.dataframe(df_warnings, use_container_width=True, hide_index=True)
                
                st.info(
                    "💡 Эти объекты включены в расчёт, "
                    "но их значения были скорректированы."
                )
            tab_idx += 1
        
        if collector.skipped:
            with tabs[tab_idx]:
                st.markdown("**Пропущенные объекты** — не входят в расчёт:")
                df_skipped = pd.DataFrame(collector.skipped)
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
        if collector.errors:
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
    page_title="Анализатор Чертежей CAD Pro",
    page_icon="📐",
    layout="wide"
)

st.title("📐 Анализатор Чертежей CAD Pro")
st.markdown("""
**Профессиональный расчет длины реза для станков ЧПУ и лазерной резки**  
Загрузите DXF-чертеж и получите точный анализ с визуализацией и детальной спецификацией.
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
        **Дополнительно:**
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
        
        # ✅ Инициализируем сборщик ошибок
        collector = ErrorCollector()
        
        try:
            import tempfile
            
            # ✅ Безопасное создание временного файла
            with tempfile.NamedTemporaryFile(
                suffix='.dxf', delete=False
            ) as tmp:
                tmp.write(uploaded_file.getbuffer())
                temp_path = tmp.name
            
            try:
                doc = ezdxf.readfile(temp_path)
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
                # Удаляем временный файл в любом случае
                try:
                    os.remove(temp_path)
                except OSError as e:
                    logger.warning(f"Не удалось удалить временный файл: {e}")
            
            msp = doc.modelspace()
            
            # ==================== АНАЛИЗ ОБЪЕКТОВ ====================
            objects_data = []
            stats = {}
            total_length = 0.0
            num = 0
            skipped_types = set()
            
            for entity in msp:
                entity_type = entity.dxftype()
                
                if entity_type not in calculators:
                    skipped_types.add(entity_type)
                    continue
                
                num += 1
                
                # ✅ Безопасный расчёт с записью ошибок
                length = calc_entity_safe(
                    entity_type, entity, num, calculators, collector
                )
                
                if length <= 0.0001:
                    if length == 0.0 and entity_type not in (
                        'MLINE', 'INSERT', 'TEXT'
                    ):
                        collector.add_skipped(
                            entity_type, num,
                            f"Нулевая или слишком малая длина: {length:.6f}"
                        )
                    continue
                
                # Определяем центр объекта
                center_x, center_y = 0.0, 0.0
                
                try:
                    if entity_type == 'LINE':
                        s, e = entity.dxf.start, entity.dxf.end
                        center_x = (s.x + e.x) / 2
                        center_y = (s.y + e.y) / 2
                    
                    elif entity_type in ('CIRCLE', 'ARC', 'ELLIPSE'):
                        center = entity.dxf.center
                        center_x, center_y = center.x, center.y
                    
                    elif entity_type == 'POINT':
                        loc = entity.dxf.location
                        center_x, center_y = loc.x, loc.y
                    
                    elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
                        if entity_type == 'LWPOLYLINE':
                            with entity.points('xy') as pts:
                                points = list(pts)
                        else:
                            points = [(p[0], p[1]) for p in entity.points()]
                        if points:
                            xs = [p[0] for p in points]
                            ys = [p[1] for p in points]
                            center_x = (min(xs) + max(xs)) / 2
                            center_y = (min(ys) + max(ys)) / 2
                    
                    elif entity_type == 'SPLINE':
                        points = list(entity.flattening(0.1))
                        if points:
                            xs = [p[0] for p in points]
                            ys = [p[1] for p in points]
                            center_x = (min(xs) + max(xs)) / 2
                            center_y = (min(ys) + max(ys)) / 2
                
                except AttributeError as e:
                    collector.add_warning(
                        entity_type, num,
                        f"Не удалось определить центр: {e}. "
                        f"Маркер будет в (0,0)",
                        "AttributeError"
                    )
                except Exception as e:
                    collector.add_warning(
                        entity_type, num,
                        f"Ошибка определения центра: {e}",
                        type(e).__name__
                    )
                
                objects_data.append({
                    'num': num,
                    'type': entity_type,
                    'length': length,
                    'center': (center_x, center_y)
                })
                
                if entity_type not in stats:
                    stats[entity_type] = {
                        'count': 0, 'length': 0.0, 'items': []
                    }
                
                stats[entity_type]['count'] += 1
                stats[entity_type]['length'] += length
                stats[entity_type]['items'].append({
                    'num': num, 'length': length
                })
                
                total_length += length
            
            # ==================== ВЫВОД РЕЗУЛЬТАТОВ ====================
            
            # ✅ Показываем отчёт об ошибках ПЕРВЫМ
            show_error_report(collector)
            
            if not objects_data:
                st.warning("⚠️ В чертеже не найдено объектов для расчета.")
                if skipped_types:
                    st.info(
                        f"Необрабатываемые типы: {', '.join(sorted(skipped_types))}"
                    )
            else:
                # Подпись если есть ошибки влияющие на результат
                if collector.errors:
                    st.success(
                        f"✅ Обработано: **{len(objects_data)}** объектов "
                        f"(⚠️ {len(collector.errors)} объектов исключены из-за ошибок)"
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
                    length_groups = {}
                    for obj in objects_data:
                        key = round(obj['length'], 1)
                        if key not in length_groups:
                            length_groups[key] = {
                                'type': obj['type'],
                                'nums': [],
                                'length': obj['length']
                            }
                        length_groups[key]['nums'].append(obj['num'])
                    
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
                            show_markers, font_size_multiplier,
                            collector   # ✅ передаём collector
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
                        '№': obj['num'],
                        'Тип': obj['type'],
                        'Длина (мм)': round(obj['length'], 2),
                        'X': round(obj['center'][0], 2),
                        'Y': round(obj['center'][1], 2)
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
    """)

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; font-size: 12px;'>
    ✂️ CAD Analyzer Pro v13.0 | Улучшенная обработка ошибок | Поддержка DXF
</div>
""", unsafe_allow_html=True)
