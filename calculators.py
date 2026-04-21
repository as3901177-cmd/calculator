"""
Калькуляторы длины для различных типов DXF объектов.
"""

import math
from typing import Any, Dict
from .config import logger, MAX_SPLINE_POINTS, SPLINE_FLATTENING, COORD_EPSILON, BULGE_EPSILON
from .utils import safe_float, safe_coordinate


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
    
    angle = math.radians(end_angle) - math.radians(start_angle)
    while angle < 0:
        angle += 2 * math.pi
    while angle > 2 * math.pi:
        angle -= 2 * math.pi
    
    return radius * angle


def calc_ellipse_length(entity: Any) -> float:
    """ELLIPSE: эллипс или его дуга."""
    major_axis = entity.dxf.major_axis
    ratio = safe_float(entity.dxf.ratio)
    start_param = safe_float(entity.dxf.start_param)
    end_param = safe_float(entity.dxf.end_param)
    
    if ratio is None or ratio <= 0:
        raise ValueError(f"Некорректный ratio эллипса: {ratio}")
    if ratio > 1:
        raise ValueError(f"Некорректный ratio > 1: {ratio}")
    if start_param is None or end_param is None:
        raise ValueError("Некорректные параметры эллипса")
    
    mx, my, mz = safe_float(major_axis.x), safe_float(major_axis.y), safe_float(major_axis.z)
    if None in (mx, my, mz):
        raise ValueError("Некорректные компоненты major_axis")
    
    a = math.sqrt(mx**2 + my**2 + mz**2)
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
    
    # Полный эллипс - приближение Рамануджана
    if abs(angle_span - 2 * math.pi) < 0.01:
        h = ((a - b) ** 2) / ((a + b) ** 2)
        return math.pi * (a + b) * (1 + 3*h / (10 + math.sqrt(4 - 3*h)))
    
    # Дуга - численное интегрирование
    N = min(1000, max(100, int(angle_span * 100)))
    length = 0.0
    
    for i in range(N):
        t1 = start_param + angle_span * i / N
        t2 = start_param + angle_span * (i + 1) / N
        
        try:
            x1, y1 = a * math.cos(t1), b * math.sin(t1)
            x2, y2 = a * math.cos(t2), b * math.sin(t2)
            
            if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
                continue
            
            segment = math.hypot(x2 - x1, y2 - y1)
            if math.isfinite(segment):
                length += segment
        except (ValueError, OverflowError):
            continue
    
    return length


def calc_lwpolyline_length(entity: Any) -> float:
    """LWPOLYLINE: лёгкая полилиния с bulge."""
    try:
        with entity.points('xyb') as pts:
            points = [p for p in pts]
    except (AttributeError, TypeError, ValueError) as e:
        raise ValueError(f"Ошибка чтения точек полилинии: {e}")
    
    if len(points) < 2:
        return 0.0
    
    try:
        is_closed = entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
    except (AttributeError, TypeError):
        is_closed = False
    
    length = 0.0
    num_segments = len(points) if is_closed else len(points) - 1
    
    for i in range(num_segments):
        next_idx = (i + 1) % len(points) if is_closed else i + 1
        if next_idx >= len(points):
            continue
        
        try:
            x1 = safe_float(points[i][0])
            y1 = safe_float(points[i][1])
            x2 = safe_float(points[next_idx][0])
            y2 = safe_float(points[next_idx][1])
            
            if None in (x1, y1, x2, y2):
                continue
            
            bulge = safe_float(points[i][2]) if len(points[i]) >= 3 else 0.0
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
                length += arc_len if (arc_len <= chord * 100 and math.isfinite(arc_len)) else chord
    
    return length


def calc_polyline_length(entity: Any) -> float:
    """POLYLINE: полилиния."""
    points = []
    try:
        for p in entity.points():
            x, y = safe_float(p[0]), safe_float(p[1])
            if x is not None and y is not None:
                points.append((x, y))
    except (ValueError, TypeError, IndexError) as e:
        raise ValueError(f"Ошибка чтения координат полилинии: {e}")
    
    if len(points) < 2:
        return 0.0
    
    length = sum(math.hypot(points[i+1][0] - points[i][0], 
                            points[i+1][1] - points[i][1]) 
                 for i in range(len(points) - 1))
    
    try:
        is_closed = entity.is_closed if hasattr(entity, 'is_closed') else bool(entity.dxf.flags & 0x01)
    except (AttributeError, TypeError):
        is_closed = False
    
    if is_closed and len(points) >= 2:
        length += math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1])
    
    return length


def calc_spline_length(entity: Any) -> float:
    """SPLINE: сплайн."""
    try:
        points = []
        point_count = 0
        
        for pt in entity.flattening(SPLINE_FLATTENING):
            if point_count >= MAX_SPLINE_POINTS:
                logger.warning(f"Сплайн ограничен до {MAX_SPLINE_POINTS} точек")
                break
            
            try:
                x, y = safe_float(pt[0]), safe_float(pt[1])
                if x is not None and y is not None:
                    points.append((x, y))
                    point_count += 1
            except (IndexError, TypeError, ValueError):
                continue
    
    except MemoryError as e:
        raise MemoryError(f"Недостаточно памяти для аппроксимации сплайна: {e}")
    except Exception as e:
        raise ValueError(f"Ошибка при чтении сплайна: {e}")
    
    if len(points) < 2:
        return 0.0
    
    return sum(math.hypot(points[i+1][0] - points[i][0], 
                         points[i+1][1] - points[i][1]) 
              for i in range(len(points) - 1))


# Калькуляторы для типов с нулевой длиной
def calc_zero_length(entity: Any) -> float:
    """Для типов с нулевой длиной (POINT, TEXT, etc.)."""
    return 0.0


# ==================== СЛОВАРЬ КАЛЬКУЛЯТОРОВ ====================
calculators: Dict[str, Any] = {
    'LINE': calc_line_length,
    'CIRCLE': calc_circle_length,
    'ARC': calc_arc_length,
    'ELLIPSE': calc_ellipse_length,
    'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE': calc_polyline_length,
    'SPLINE': calc_spline_length,
    'POINT': calc_zero_length,
    'MLINE': calc_zero_length,
    'INSERT': calc_zero_length,
    'TEXT': calc_zero_length,
    'ATTRIB': calc_zero_length,
}