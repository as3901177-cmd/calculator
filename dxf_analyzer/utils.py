import math
from typing import Any, Tuple, Optional
from decimal import Decimal

def safe_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, str):
            lower_val = value.lower().strip()
            if lower_val in ('inf', '+inf', '-inf', 'nan', 'infinity'):
                return None
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    except:
        return None

def safe_coordinate(coord: Any) -> Tuple[Optional[float], Optional[float]]:
    try:
        return safe_float(coord.x), safe_float(coord.y)
    except:
        return None, None

def normalize_angle(angle_deg: float) -> float:
    return angle_deg % 360.0

def points_close(p1: Tuple[float, float], p2: Tuple[float, float], tolerance: float) -> bool:
    try:
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) < tolerance
    except:
        return False