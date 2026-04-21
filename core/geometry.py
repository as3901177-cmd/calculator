import math
from typing import Tuple, Optional, Any
from core.errors import logger
from utils.constants import COORD_EPSILON, MAX_CENTER_POINTS

def safe_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, str):
            if value.lower().strip() in ('inf', 'nan'): return None
        result = float(value)
        return result if math.isfinite(result) else None
    except: return None

def safe_coordinate(coord: Any) -> Tuple[Optional[float], Optional[float]]:
    try:
        return safe_float(coord.x), safe_float(coord.y)
    except: return None, None

def points_close(p1: Tuple[float, float], p2: Tuple[float, float], tolerance: float) -> bool:
    try:
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) < tolerance
    except: return False

def normalize_angle(angle_deg: float) -> float:
    return angle_deg % 360.0

def get_entity_center(entity: Any) -> Tuple[float, float]:
    entity_type = entity.dxftype()
    try:
        if entity_type == 'LINE':
            x1, y1 = safe_coordinate(entity.dxf.start)
            x2, y2 = safe_coordinate(entity.dxf.end)
            return ((x1 + x2) / 2, (y1 + y2) / 2) if None not in (x1, y1, x2, y2) else (0.0, 0.0)
        elif entity_type in ('CIRCLE', 'ARC', 'ELLIPSE'):
            x, y = safe_coordinate(entity.dxf.center)
            return (x or 0.0, y or 0.0)
        elif entity_type in ('LWPOLYLINE', 'POLYLINE', 'SPLINE'):
            pts = []
            if entity_type == 'SPLINE':
                pts = [(p[0], p[1]) for i, p in enumerate(entity.flattening(0.1)) if i < MAX_CENTER_POINTS]
            else:
                pts = [(p[0], p[1]) for p in entity.points()]
            if pts:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    except: pass
    return (0.0, 0.0)

def get_entity_endpoints(entity: Any):
    entity_type = entity.dxftype()
    try:
        if entity_type == 'LINE':
            return safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
        elif entity_type == 'ARC':
            cx, cy = safe_coordinate(entity.dxf.center)
            r = safe_float(entity.dxf.radius)
            s_ang, e_ang = math.radians(entity.dxf.start_angle), math.radians(entity.dxf.end_angle)
            return (cx + r*math.cos(s_ang), cy + r*math.sin(s_ang)), (cx + r*math.cos(e_ang), cy + r*math.sin(e_ang))
        elif entity_type in ('LWPOLYLINE', 'POLYLINE', 'SPLINE'):
            pts = [(p[0], p[1]) for p in (entity.flattening(0.1) if entity_type=='SPLINE' else entity.points())]
            if len(pts) >= 2: return pts[0], pts[-1]
    except: pass
    return None, None

def get_entity_center_with_offset(entity: Any, offset: float) -> Tuple[float, float]:
    center = get_entity_center(entity)
    # Упрощенная логика смещения для визуализации
    return (center[0] + offset, center[1] + offset)