import math
from typing import Any, Tuple, Optional
from .utils import safe_float, safe_coordinate, normalize_angle
from .config import COORD_EPSILON, BULGE_EPSILON, MAX_SPLINE_POINTS, SPLINE_FLATTENING, MAX_CENTER_POINTS

def calc_line_length(entity: Any) -> float:
    p1 = safe_coordinate(entity.dxf.start)
    p2 = safe_coordinate(entity.dxf.end)
    if None in p1 or None in p2: raise ValueError("Invalid coordinates")
    return math.hypot(p2[0]-p1[0], p2[1]-p1[1])

def calc_circle_length(entity: Any) -> float:
    r = safe_float(entity.dxf.radius)
    if r is None or r <= 0: raise ValueError("Invalid radius")
    return 2 * math.pi * r

def calc_arc_length(entity: Any) -> float:
    r = safe_float(entity.dxf.radius)
    s, e = safe_float(entity.dxf.start_angle), safe_float(entity.dxf.end_angle)
    if any(v is None for v in (r, s, e)): raise ValueError("Invalid arc params")
    angle = math.radians(e - s)
    while angle < 0: angle += 2 * math.pi
    return r * angle

def calc_ellipse_length(entity: Any) -> float:
    major = entity.dxf.major_axis
    ratio = safe_float(entity.dxf.ratio)
    a = math.sqrt(safe_float(major.x)**2 + safe_float(major.y)**2)
    b = a * ratio
    s_p, e_p = safe_float(entity.dxf.start_param), safe_float(entity.dxf.end_param)
    span = e_p - s_p
    while span < 0: span += 2 * math.pi
    if abs(span - 2 * math.pi) < 0.01:
        h = ((a - b)**2) / ((a + b)**2)
        return math.pi * (a + b) * (1 + 3*h/(10 + math.sqrt(4-3*h)))
    # Numerical integration
    n, length = 200, 0.0
    for i in range(n):
        t1, t2 = s_p + span*i/n, s_p + span*(i+1)/n
        x1, y1 = a*math.cos(t1), b*math.sin(t1)
        x2, y2 = a*math.cos(t2), b*math.sin(t2)
        length += math.hypot(x2-x1, y2-y1)
    return length

def calc_lwpolyline_length(entity: Any) -> float:
    pts = []
    with entity.points('xyb') as p_list:
        for p in p_list: pts.append(p)
    if len(pts) < 2: return 0.0
    length = 0.0
    is_closed = entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
    for i in range(len(pts) if is_closed else len(pts)-1):
        p1, p2 = pts[i], pts[(i+1)%len(pts)]
        chord = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
        bulge = p1[2]
        if abs(bulge) < BULGE_EPSILON: length += chord
        else:
            angle = 4 * math.atan(abs(bulge))
            length += (chord / math.sin(angle/2)) * (angle/2)
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
    if etype == 'ELLIPSE':
        return abs(safe_float(entity.dxf.end_param) - safe_float(entity.dxf.start_param) - 2*math.pi) < 0.01
    return False

def get_entity_endpoints(entity: Any):
    etype = entity.dxftype()
    try:
        if etype == 'LINE': return safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
        if etype == 'ARC':
            c, r = safe_coordinate(entity.dxf.center), entity.dxf.radius
            s, e = math.radians(entity.dxf.start_angle), math.radians(entity.dxf.end_angle)
            return (c[0]+r*math.cos(s), c[1]+r*math.sin(s)), (c[0]+r*math.cos(e), c[1]+r*math.sin(e))
        if etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            return (pts[0][0], pts[0][1]), (pts[-1][0], pts[-1][1])
        if etype == 'SPLINE':
            pts = list(entity.flattening(0.1))
            return (pts[0][0], pts[0][1]), (pts[-1][0], pts[-1][1])
    except: pass
    return None, None