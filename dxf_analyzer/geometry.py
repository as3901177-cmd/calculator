import math
from typing import Any, Tuple
from .utils import safe_float, safe_coordinate, normalize_angle
from .config import (COORD_EPSILON, BULGE_EPSILON, MAX_SPLINE_POINTS, 
                     SPLINE_FLATTENING, MAX_CENTER_POINTS)

def calc_line_length(entity: Any) -> float:
    x1, y1 = safe_coordinate(entity.dxf.start)
    x2, y2 = safe_coordinate(entity.dxf.end)
    if None in (x1, y1, x2, y2): raise ValueError("Некорректные координаты линии")
    return math.hypot(x2 - x1, y2 - y1)

def calc_circle_length(entity: Any) -> float:
    r = safe_float(entity.dxf.radius)
    if r is None or r <= 0: raise ValueError(f"Некорректный радиус: {r}")
    return 2 * math.pi * r

def calc_arc_length(entity: Any) -> float:
    r = safe_float(entity.dxf.radius)
    s = safe_float(entity.dxf.start_angle)
    e = safe_float(entity.dxf.end_angle)
    if any(v is None for v in (r, s, e)) or r <= 0: raise ValueError("Некорректные параметры дуги")
    angle = math.radians(e - s)
    while angle < 0: angle += 2 * math.pi
    return r * angle

def calc_ellipse_length(entity: Any) -> float:
    ratio = safe_float(entity.dxf.ratio)
    major_axis = entity.dxf.major_axis
    a = math.sqrt(safe_float(major_axis.x)**2 + safe_float(major_axis.y)**2)
    b = a * ratio
    s_param = safe_float(entity.dxf.start_param)
    e_param = safe_float(entity.dxf.end_param)
    span = e_param - s_param
    while span < 0: span += 2 * math.pi
    if abs(span - 2 * math.pi) < 0.01:
        h = ((a - b) ** 2) / ((a + b) ** 2)
        return math.pi * (a + b) * (1 + 3*h / (10 + math.sqrt(4 - 3*h)))
    N = 200
    length = 0.0
    for i in range(N):
        t1 = s_param + span * i / N
        t2 = s_param + span * (i + 1) / N
        length += math.hypot(a*math.cos(t2)-a*math.cos(t1), b*math.sin(t2)-b*math.sin(t1))
    return length

def calc_lwpolyline_length(entity: Any) -> float:
    points = []
    with entity.points('xyb') as pts:
        for p in pts: points.append(p)
    if len(points) < 2: return 0.0
    length = 0.0
    is_closed = entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
    num_segments = len(points) if is_closed else len(points) - 1
    for i in range(num_segments):
        p1, p2 = points[i], points[(i + 1) % len(points)]
        chord = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
        bulge = p1[2]
        if abs(bulge) < BULGE_EPSILON: length += chord
        else:
            angle = 4 * math.atan(abs(bulge))
            radius = chord / (2 * math.sin(angle / 2))
            length += radius * angle
    return length

def calc_polyline_length(entity: Any) -> float:
    pts = [(safe_float(p[0]), safe_float(p[1])) for p in entity.points()]
    pts = [p for p in pts if p[0] is not None]
    if len(pts) < 2: return 0.0
    length = sum(math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1))
    if getattr(entity, 'is_closed', bool(entity.dxf.flags & 0x01)):
        length += math.hypot(pts[0][0]-pts[-1][0], pts[0][1]-pts[-1][1])
    return length

def calc_spline_length(entity: Any) -> float:
    pts = []
    for i, pt in enumerate(entity.flattening(SPLINE_FLATTENING)):
        if i >= MAX_SPLINE_POINTS: break
        pts.append((safe_float(pt[0]), safe_float(pt[1])))
    if len(pts) < 2: return 0.0
    return sum(math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1))

def check_is_closed(entity: Any) -> bool:
    etype = entity.dxftype()
    if etype == 'CIRCLE': return True
    if etype == 'LWPOLYLINE': return entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
    if etype == 'POLYLINE': return getattr(entity, 'is_closed', bool(entity.dxf.flags & 0x01))
    return False

CALCULATORS = {
    'LINE': calc_line_length, 'CIRCLE': calc_circle_length, 'ARC': calc_arc_length,
    'ELLIPSE': calc_ellipse_length, 'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE': calc_polyline_length, 'SPLINE': calc_spline_length,
    'POINT': lambda e: 0.0, 'INSERT': lambda e: 0.0, 'TEXT': lambda e: 0.0
}