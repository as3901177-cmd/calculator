import math
import logging
from typing import Tuple, Optional, List, Set, Dict, Any
from config import *
from models import ObjectStatus, ErrorCollector, DXFObject

logger = logging.getLogger(__name__)

# ==================== УТИЛИТЫ КООРДИНАТ ====================

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

def normalize_angle(angle_deg: float) -> float:
    """Нормализует угол в диапазон [0, 360)."""
    return angle_deg % 360.0

def get_layer_info(entity: Any) -> Tuple[str, int]:
    try:
        layer = str(entity.dxf.layer) if hasattr(entity.dxf, 'layer') else "0"
        color = int(entity.dxf.color) if hasattr(entity.dxf, 'color') else 256
        return layer, color
    except: return "0", 256

def check_is_closed(entity: Any) -> bool:
    etype = entity.dxftype()
    try:
        if etype == 'CIRCLE': return True
        if etype == 'LWPOLYLINE': return entity.close or bool(entity.dxf.flags & 1)
        if etype == 'POLYLINE': return bool(entity.dxf.flags & 1)
        if etype == 'ELLIPSE':
            span = abs(entity.dxf.end_param - entity.dxf.start_param)
            return abs(span - 2 * math.pi) < 0.01
        return False
    except: return False

# ==================== КАЛЬКУЛЯТОРЫ ДЛИНЫ ====================

def calc_line_length(entity: Any) -> float:
    x1, y1 = safe_coordinate(entity.dxf.start)
    x2, y2 = safe_coordinate(entity.dxf.end)
    if None in (x1, y1, x2, y2): return 0.0
    return math.hypot(x2 - x1, y2 - y1)

def calc_circle_length(entity: Any) -> float:
    r = safe_float(entity.dxf.radius)
    return 2 * math.pi * r if r else 0.0

def calc_arc_length(entity: Any) -> float:
    r = safe_float(entity.dxf.radius)
    if not r: return 0.0
    sa = math.radians(entity.dxf.start_angle)
    ea = math.radians(entity.dxf.end_angle)
    angle = ea - sa
    while angle < 0: angle += 2 * math.pi
    return r * angle

def calc_lwpolyline_length(entity: Any) -> float:
    try:
        points = list(entity.points('xyb'))
        if len(points) < 2: return 0.0
        length = 0.0
        is_closed = entity.close if hasattr(entity, 'close') else bool(entity.dxf.flags & 1)
        num = len(points) if is_closed else len(points) - 1
        for i in range(num):
            p1 = points[i]
            p2 = points[(i + 1) % len(points)]
            chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            bulge = p1[2]
            if abs(bulge) < BULGE_EPSILON:
                length += chord
            else:
                angle = 4 * math.atan(abs(bulge))
                radius = chord / (2 * math.sin(angle / 2))
                length += radius * angle
        return length
    except: return 0.0

def calc_spline_length(entity: Any) -> float:
    try:
        points = list(entity.flattening(SPLINE_FLATTENING))
        if len(points) < 2: return 0.0
        return sum(math.hypot(points[i+1][0]-points[i][0], points[i+1][1]-points[i][1]) 
                   for i in range(len(points)-1))
    except: return 0.0

def calc_ellipse_length(entity: Any) -> float:
    try:
        major = entity.dxf.major_axis
        a = math.sqrt(major.x**2 + major.y**2)
        b = a * entity.dxf.ratio
        span = abs(entity.dxf.end_param - entity.dxf.start_param)
        if abs(span - 2*math.pi) < 0.01:
            h = ((a-b)**2) / ((a+b)**2)
            return math.pi * (a+b) * (1 + 3*h/(10 + math.sqrt(4-3*h)))
        return a * span 
    except: return 0.0

calculators = {
    'LINE': calc_line_length,
    'CIRCLE': calc_circle_length,
    'ARC': calc_arc_length,
    'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE': calc_lwpolyline_length,
    'SPLINE': calc_spline_length,
    'ELLIPSE': calc_ellipse_length,
    'POINT': lambda e: 0.0,
    'TEXT': lambda e: 0.0,
    'INSERT': lambda e: 0.0
}

# ==================== АНАЛИЗ СВЯЗНОСТИ ====================

def get_entity_endpoints(entity: Any):
    etype = entity.dxftype()
    try:
        if etype == 'LINE': 
            return (entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)
        if etype == 'ARC':
            cx, cy = entity.dxf.center.x, entity.dxf.center.y
            r = entity.dxf.radius
            s, e = math.radians(entity.dxf.start_angle), math.radians(entity.dxf.end_angle)
            return (cx + r*math.cos(s), cy + r*math.sin(s)), (cx + r*math.cos(e), cy + r*math.sin(e))
        if etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            return (pts[0][0], pts[0][1]), (pts[-1][0], pts[-1][1])
    except: pass
    return None, None

def find_connected_chain(start_idx: int, objects: List[DXFObject], tolerance: float) -> Set[int]:
    chain = {start_idx}
    queue = [start_idx]
    endpoints = {i: get_entity_endpoints(objects[i].entity) for i in range(len(objects)) if objects[i].entity}
    while queue:
        curr = queue.pop(0)
        p_curr = endpoints.get(curr)
        if not p_curr or not p_curr[0]: continue
        for i, obj in enumerate(objects):
            if i in chain or obj.status == ObjectStatus.ERROR: continue
            p_next = endpoints.get(i)
            if not p_next or not p_next[0]: continue
            if any(math.hypot(a[0]-b[0], a[1]-b[1]) < tolerance for a in p_curr for b in p_next):
                chain.add(i)
                queue.append(i)
    return chain

def count_piercings_advanced(objects_data: List[DXFObject], collector: ErrorCollector, tolerance: float = PIERCING_TOLERANCE):
    valid = [obj for obj in objects_data if obj.status in (ObjectStatus.NORMAL, ObjectStatus.WARNING)]
    visited = set()
    chain_count = 0
    details = []
    for idx, obj in enumerate(valid):
        if idx in visited: continue
        if obj.is_closed or obj.entity_type in ('CIRCLE', 'ELLIPSE'):
            chain_count += 1
            visited.add(idx)
            obj.chain_id = chain_count
            details.append({'chain_id': chain_count, 'type': 'closed', 'length': obj.length, 'objects': [obj.num]})
        else:
            indices = find_connected_chain(idx, valid, tolerance)
            visited.update(indices)
            chain_count += 1
            c_len = 0
            c_nums = []
            for i in indices:
                valid[i].chain_id = chain_count
                c_len += valid[i].length
                c_nums.append(valid[i].num)
            details.append({'chain_id': chain_count, 'type': 'open', 'length': c_len, 'objects': c_nums})
    return chain_count, details

def calc_entity_safe(entity_type, entity, entity_num, calculators, collector):
    if entity_type not in calculators:
        return 0.0, ObjectStatus.SKIPPED, "Not supported"
    try:
        length = calculators[entity_type](entity)
        return length, ObjectStatus.NORMAL, ""
    except Exception as e:
        collector.add_error(entity_type, entity_num, str(e))
        return 0.0, ObjectStatus.ERROR, str(e)

def get_entity_center(entity):
    try:
        if hasattr(entity.dxf, 'center'): return entity.dxf.center.x, entity.dxf.center.y
        if hasattr(entity.dxf, 'start'): return (entity.dxf.start.x + entity.dxf.end.x)/2, (entity.dxf.start.y + entity.dxf.end.y)/2
        pts = list(entity.points())
        if pts: return pts[0][0], pts[0][1]
    except: pass
    return (0.0, 0.0)
