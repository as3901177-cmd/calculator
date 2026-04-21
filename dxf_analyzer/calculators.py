"""
Калькуляторы длины для различных типов объектов DXF
"""

import math
from typing import Any

def calc_line_length(entity: Any) -> float:
    """Расчёт длины LINE"""
    start = entity.dxf.start
    end = entity.dxf.end
    return math.sqrt(
        (end.x - start.x)**2 + 
        (end.y - start.y)**2 + 
        (end.z - start.z)**2
    )

def calc_arc_length(entity: Any) -> float:
    """Расчёт длины ARC"""
    radius = entity.dxf.radius
    start_angle = math.radians(entity.dxf.start_angle)
    end_angle = math.radians(entity.dxf.end_angle)
    
    # Нормализация углов
    if end_angle < start_angle:
        end_angle += 2 * math.pi
    
    angle_diff = end_angle - start_angle
    return radius * angle_diff

def calc_circle_length(entity: Any) -> float:
    """Расчёт длины CIRCLE"""
    return 2 * math.pi * entity.dxf.radius

def calc_polyline_length(entity: Any) -> float:
    """Расчёт длины POLYLINE"""
    total = 0.0
    points = list(entity.points())
    
    for i in range(len(points) - 1):
        p1, p2 = points[i], points[i + 1]
        total += math.sqrt(
            (p2.x - p1.x)**2 + 
            (p2.y - p1.y)**2 + 
            (p2.z - p1.z)**2
        )
    
    # Если полилиния замкнута
    if entity.is_closed and len(points) > 1:
        p1, p2 = points[-1], points[0]
        total += math.sqrt(
            (p2.x - p1.x)**2 + 
            (p2.y - p1.y)**2 + 
            (p2.z - p1.z)**2
        )
    
    return total

def calc_lwpolyline_length(entity: Any) -> float:
    """Расчёт длины LWPOLYLINE (облегчённая полилиния)"""
    total = 0.0
    points = list(entity.get_points('xy'))
    
    for i in range(len(points) - 1):
        x1, y1 = points[i][:2]
        x2, y2 = points[i + 1][:2]
        total += math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    
    # Если полилиния замкнута
    if entity.closed and len(points) > 1:
        x1, y1 = points[-1][:2]
        x2, y2 = points[0][:2]
        total += math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    
    return total

def calc_spline_length(entity: Any) -> float:
    """Расчёт длины SPLINE (аппроксимация)"""
    try:
        # Получаем точки аппроксимации сплайна
        points = list(entity.flattening(0.01))
        
        total = 0.0
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            total += math.sqrt(
                (p2[0] - p1[0])**2 + 
                (p2[1] - p1[1])**2
            )
        
        return total
    except Exception:
        # Если не удалось аппроксимировать, пытаемся через контрольные точки
        control_points = list(entity.control_points)
        if len(control_points) < 2:
            return 0.0
        
        total = 0.0
        for i in range(len(control_points) - 1):
            p1, p2 = control_points[i], control_points[i + 1]
            total += math.sqrt(
                (p2.x - p1.x)**2 + 
                (p2.y - p1.y)**2
            )
        
        return total * 1.2  # Поправочный коэффициент для кривизны

def calc_ellipse_length(entity: Any) -> float:
    """Расчёт длины ELLIPSE (приближённо по формуле Рамануджана)"""
    try:
        major_axis = entity.dxf.major_axis
        ratio = entity.dxf.ratio  # Отношение малой оси к большой
        
        a = math.sqrt(major_axis.x**2 + major_axis.y**2)  # Большая полуось
        b = a * ratio  # Малая полуось
        
        # Формула Рамануджана для периметра эллипса
        h = ((a - b)**2) / ((a + b)**2)
        perimeter = math.pi * (a + b) * (1 + (3 * h) / (10 + math.sqrt(4 - 3 * h)))
        
        # Если это не полный эллипс, учитываем углы
        start_param = entity.dxf.start_param if hasattr(entity.dxf, 'start_param') else 0
        end_param = entity.dxf.end_param if hasattr(entity.dxf, 'end_param') else 2 * math.pi
        
        angle_ratio = abs(end_param - start_param) / (2 * math.pi)
        
        return perimeter * angle_ratio
        
    except Exception:
        return 0.0

# Словарь всех калькуляторов
calculators = {
    'LINE': calc_line_length,
    'ARC': calc_arc_length,
    'CIRCLE': calc_circle_length,
    'POLYLINE': calc_polyline_length,
    'LWPOLYLINE': calc_lwpolyline_length,
    'SPLINE': calc_spline_length,
    'ELLIPSE': calc_ellipse_length,
}