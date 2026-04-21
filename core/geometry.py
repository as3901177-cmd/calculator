import math
from typing import Tuple, Optional, Any
from utils.constants import COORD_EPSILON, MAX_CENTER_POINTS

def safe_float(value: Any) -> Optional[float]:
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except: return None

def safe_coordinate(coord: Any) -> Tuple[Optional[float], Optional[float]]:
    try: return safe_float(coord.x), safe_float(coord.y)
    except: return None, None

def points_close(p1, p2, tolerance) -> bool:
    return math.hypot(p1[0]-p2[0], p1[1]-p2[1]) < tolerance

def get_entity_endpoints(entity):
    etype = entity.dxftype()
    try:
        if etype == 'LINE':
            return safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
        elif etype == 'ARC':
            c = safe_coordinate(entity.dxf.center)
            r = safe_float(entity.dxf.radius)
            s = math.radians(entity.dxf.start_angle)
            e = math.radians(entity.dxf.end_angle)
            return (c[0]+r*math.cos(s), c[1]+r*math.sin(s)), (c[0]+r*math.cos(e), c[1]+r*math.sin(e))
        elif etype in ('LWPOLYLINE', 'POLYLINE', 'SPLINE'):
            pts = list(entity.flattening(0.1)) if etype=='SPLINE' else list(entity.points())
            if len(pts) >= 2: return (pts[0][0], pts[0][1]), (pts[-1][0], pts[-1][1])
    except: pass
    return None, None

def get_entity_center(entity):
    etype = entity.dxftype()
    try:
        if etype in ('CIRCLE', 'ARC', 'ELLIPSE'):
            return safe_coordinate(entity.dxf.center)
        if etype == 'LINE':
            p1, p2 = safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
            return ((p1[0]+p2[0])/2, (p1[1]+p2[1])/2)
        pts = list(entity.points())
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return ((min(xs)+max(xs))/2, (min(ys)+max(ys))/2)
    except: return (0,0)