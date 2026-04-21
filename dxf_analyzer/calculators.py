import math
import logging
import pandas as pd
from typing import List, Dict, Tuple, Any, Set
from collections import defaultdict
from .models import DXFObject, ProcessingIssue, ErrorSeverity, ObjectStatus
from .config import MAX_LENGTH, PIERCING_TOLERANCE, COORD_EPSILON
from .utils import safe_float, safe_coordinate, points_close
from .geometry import CALCULATORS

logger = logging.getLogger(__name__)

class ErrorCollector:
    def __init__(self):
        self.issues: List[ProcessingIssue] = []
        self.object_issues: Dict[int, List[ProcessingIssue]] = {}
    
    def add_issue(self, issue: ProcessingIssue, object_num: int = 0):
        self.issues.append(issue)
        if object_num > 0:
            if object_num not in self.object_issues: self.object_issues[object_num] = []
            self.object_issues[object_num].append(issue)

    def add_error(self, t, n, m, c=""): self.add_issue(ProcessingIssue(t, n, m, c, ErrorSeverity.ERROR), n)
    def add_warning(self, t, n, m, c=""): self.add_issue(ProcessingIssue(t, n, m, c, ErrorSeverity.WARNING), n)
    def add_skipped(self, t, n, r): self.add_issue(ProcessingIssue(t, n, r, "", ErrorSeverity.SKIPPED), n)
    def add_info(self, t, n, m): self.add_issue(ProcessingIssue(t, n, m, "", ErrorSeverity.INFO), n)

    @property
    def errors(self): return [i for i in self.issues if i.severity == ErrorSeverity.ERROR]
    @property
    def warnings(self): return [i for i in self.issues if i.severity == ErrorSeverity.WARNING]
    @property
    def skipped(self): return [i for i in self.issues if i.severity == ErrorSeverity.SKIPPED]
    @property
    def has_errors(self): return bool(self.errors)
    @property
    def has_issues(self): return bool(self.issues)
    @property
    def total_issues(self): return len(self.issues)

    def get_summary(self):
        parts = []
        if self.errors: parts.append(f"🔴 Ошибок: {len(self.errors)}")
        if self.warnings: parts.append(f"🟡 Предупреждений: {len(self.warnings)}")
        return " | ".join(parts) if parts else "✅ Ошибок нет"

    def get_all_as_dataframe(self):
        return pd.DataFrame([i.to_dict() for i in self.issues])

def validate_length_result(length: Any, entity_type: str, entity_num: int, collector: ErrorCollector):
    try:
        val = float(length)
        if not math.isfinite(val): return 0.0, False, "Non-finite result"
        if val < 0: return abs(val), True, "Negative length corrected"
        if val > MAX_LENGTH: return val, True, "ScaleWarning: Very large"
        return val, True, ""
    except: return 0.0, False, "TypeError"

def calc_entity_safe(etype, entity, enum, collector):
    if etype not in CALCULATORS:
        collector.add_skipped(etype, enum, "Тип не поддерживается")
        return 0.0, ObjectStatus.SKIPPED, "Not supported"
    try:
        raw = CALCULATORS[etype](entity)
        val, success, desc = validate_length_result(raw, etype, enum, collector)
        if not success: return 0.0, ObjectStatus.ERROR, desc
        status = ObjectStatus.WARNING if "Warning" in desc else ObjectStatus.NORMAL
        return val, status, desc
    except Exception as e:
        collector.add_error(etype, enum, str(e), type(e).__name__)
        return 0.0, ObjectStatus.ERROR, str(e)

def get_entity_endpoints(entity: Any):
    etype = entity.dxftype()
    try:
        if etype == 'LINE':
            p1, p2 = safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
            return p1, p2
        elif etype == 'ARC':
            cx, cy = safe_coordinate(entity.dxf.center)
            r = entity.dxf.radius
            s, e = math.radians(entity.dxf.start_angle), math.radians(entity.dxf.end_angle)
            return (cx+r*math.cos(s), cy+r*math.sin(s)), (cx+r*math.cos(e), cy+r*math.sin(e))
        elif etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            return (pts[0][0], pts[0][1]), (pts[-1][0], pts[-1][1])
        elif etype == 'SPLINE':
            pts = list(entity.flattening(0.1))
            return (pts[0][0], pts[0][1]), (pts[-1][0], pts[-1][1])
    except: pass
    return None, None

def find_connected_chain(start_idx: int, objects: List[DXFObject], tolerance: float) -> Set[int]:
    chain, queue = {start_idx}, [start_idx]
    cache = {i: get_entity_endpoints(obj.entity) for i, obj in enumerate(objects) if obj.entity}
    while queue:
        curr = queue.pop(0)
        p1, p2 = cache.get(curr, (None, None))
        if not p1 or not p2: continue
        for idx, obj in enumerate(objects):
            if idx in chain or obj.status == ObjectStatus.ERROR: continue
            np1, np2 = cache.get(idx, (None, None))
            if not np1 or not np2: continue
            if any(points_close(a, b, tolerance) for a in (p1, p2) for b in (np1, np2)):
                chain.add(idx)
                queue.append(idx)
    return chain

def count_piercings_advanced(objects: List[DXFObject], collector: ErrorCollector, tolerance=PIERCING_TOLERANCE):
    valid = [obj for obj in objects if obj.status in (ObjectStatus.NORMAL, ObjectStatus.WARNING)]
    visited, count, details = set(), 0, []
    for idx, obj in enumerate(valid):
        if idx in visited: continue
        if obj.is_closed or obj.entity_type in ('CIRCLE', 'ELLIPSE'):
            count += 1
            visited.add(idx)
            obj.chain_id = count
            details.append({'chain_id': count, 'type': 'closed', 'objects': [obj.num], 'length': obj.length})
        else:
            chain_indices = find_connected_chain(idx, valid, tolerance)
            visited.update(chain_indices)
            count += 1
            c_objs = [valid[i] for i in chain_indices]
            for i in chain_indices: valid[i].chain_id = count
            details.append({
                'chain_id': count, 
                'type': 'open' if len(chain_indices) > 1 else 'isolated',
                'objects': [o.num for o in c_objs], 
                'length': sum(o.length for o in c_objs)
            })
    return count, details

def get_piercing_statistics(objects: List[DXFObject]):
    stats = {'total': 0, 'closed': 0, 'open': 0, 'isolated': 0, 'by_type': defaultdict(int)}
    unique_ids = {obj.chain_id for obj in objects if obj.chain_id > 0}
    stats['total'] = len(unique_ids)
    for cid in unique_ids:
        c_objs = [o for o in objects if o.chain_id == cid]
        if any(o.is_closed for o in c_objs) or c_objs[0].entity_type == 'CIRCLE': stats['closed'] += 1
        elif len(c_objs) == 1: stats['isolated'] += 1
        else: stats['open'] += 1
    return stats