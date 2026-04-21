import math
from typing import Any, Dict, Callable
from core.geometry import safe_float, safe_coordinate
from utils.constants import MAX_SPLINE_POINTS, SPLINE_FLATTENING, BULGE_EPSILON, COORD_EPSILON

def calc_line_length(entity) -> float:
    x1, y1 = safe_coordinate(entity.dxf.start)
    x2, y2 = safe_coordinate(entity.dxf.end)
    return math.hypot(x2 - x1, y2 - y1)

def calc_circle_length(entity) -> float:
    return 2 * math.pi * safe_float(entity.dxf.radius)

def calc_arc_length(entity) -> float:
    r = safe_float(entity.dxf.radius)
    a = (entity.dxf.end_angle - entity.dxf.start_angle) % 360
    return r * math.radians(a)

def calc_lwpolyline_length(entity) -> float:
    points = list(entity.points('xyb'))
    if len(points) < 2: return 0.0
    length = 0.0
    is_closed = entity.close or bool(entity.dxf.flags & 1)
    for i in range(len(points) if is_closed else len(points)-1):
        p1 = points[i]
        p2 = points[(i+1)%len(points)]
        chord = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
        bulge = p1[2]
        if abs(bulge) < BULGE_EPSILON: length += chord
        else:
            angle = 4 * math.atan(abs(bulge))
            length += (chord / math.sin(angle/2)) * (angle/2) if chord > 0 else 0
    return length

def calc_polyline_length(entity) -> float:
    pts = list(entity.points())
    length = sum(math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1))
    if entity.is_closed: length += math.hypot(pts[-1][0]-pts[0][0], pts[-1][1]-pts[0][1])
    return length

def calc_spline_length(entity) -> float:
    pts = list(entity.flattening(SPLINE_FLATTENING))
    return sum(math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1))

def calc_ellipse_length(entity) -> float:
    a = entity.dxf.major_axis.magnitude
    b = a * entity.dxf.ratio
    # Приближение Рамануджана
    return math.pi * (3*(a+b) - math.sqrt((3*a+b)*(a+3*b)))

calculators = {
    'LINE': calc_line_length,
    'CIRCLE': calc_circle_length,
    'ARC': calc_arc_length,
    'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE': calc_polyline_length,
    'SPLINE': calc_spline_length,
    'ELLIPSE': calc_ellipse_length,
    'POINT': lambda e: 0.0,
    'TEXT': lambda e: 0.0,
    'INSERT': lambda e: 0.0
}