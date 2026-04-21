import math
from core.geometry import safe_float, safe_coordinate
from utils.constants import BULGE_EPSILON, SPLINE_FLATTENING

def calc_line_length(e):
    p1, p2 = safe_coordinate(e.dxf.start), safe_coordinate(e.dxf.end)
    return math.hypot(p2[0]-p1[0], p2[1]-p1[1])

def calc_circle_length(e):
    return 2 * math.pi * safe_float(e.dxf.radius)

def calc_arc_length(e):
    r = safe_float(e.dxf.radius)
    ang = (e.dxf.end_angle - e.dxf.start_angle) % 360
    return r * math.radians(ang)

def calc_lwpolyline_length(e):
    pts = list(e.points('xyb'))
    length = 0.0
    closed = e.close or bool(e.dxf.flags & 1)
    for i in range(len(pts) if closed else len(pts)-1):
        p1 = pts[i]; p2 = pts[(i+1)%len(pts)]
        chord = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
        if abs(p1[2]) < BULGE_EPSILON: length += chord
        else:
            angle = 4 * math.atan(abs(p1[2]))
            length += (chord / math.sin(angle/2)) * (angle/2)
    return length

def calc_spline_length(e):
    pts = list(e.flattening(SPLINE_FLATTENING))
    return sum(math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1))

calculators = {
    'LINE': calc_line_length, 'CIRCLE': calc_circle_length,
    'ARC': calc_arc_length, 'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE': calc_lwpolyline_length, 'SPLINE': calc_spline_length,
    'ELLIPSE': lambda e: 0.0, 'POINT': lambda e: 0.0, 'TEXT': lambda e: 0.0
}