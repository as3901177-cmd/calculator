import math
import pandas as pd
from typing import List, Dict, Set
from .models import DXFObject, ProcessingIssue, ErrorSeverity, ObjectStatus
from .config import MAX_LENGTH, PIERCING_TOLERANCE
from .utils import points_close
from .geometry import (calc_line_length, calc_circle_length, calc_arc_length, 
                       calc_ellipse_length, calc_lwpolyline_length, 
                       calc_polyline_length, calc_spline_length, get_entity_endpoints)

CALCULATORS = {
    'LINE': calc_line_length, 'CIRCLE': calc_circle_length, 'ARC': calc_arc_length,
    'ELLIPSE': calc_ellipse_length, 'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE': calc_polyline_length, 'SPLINE': calc_spline_length
}

class ErrorCollector:
    def __init__(self):
        self.issues = []
        self.object_issues = {}

    def add_issue(self, issue, obj_num=0):
        self.issues.append(issue)
        if obj_num > 0:
            if obj_num not in self.object_issues: self.object_issues[obj_num] = []
            self.object_issues[obj_num].append(issue)

    def add_error(self, t, n, m, c=""): self.add_issue(ProcessingIssue(t, n, m, c, ErrorSeverity.ERROR), n)
    def add_warning(self, t, n, m, c=""): self.add_issue(ProcessingIssue(t, n, m, c, ErrorSeverity.WARNING), n)
    def add_skipped(self, t, n, r): self.add_issue(ProcessingIssue(t, n, r, "", ErrorSeverity.SKIPPED), n)
    def add_info(self, t, n, m): self.add_issue(ProcessingIssue(t, n, m, "", ErrorSeverity.INFO), n)

    @property
    def errors(self): return [i for i in self.issues if i.severity == ErrorSeverity.ERROR]
    @property
    def warnings(self): return [i for i in self.issues if i.severity == ErrorSeverity.WARNING]
    @property
    def has_errors(self): return bool(self.errors)
    
    def get_summary(self):
        parts = []
        if self.errors: parts.append(f"🔴 Ошибок: {len(self.errors)}")
        if self.warnings: parts.append(f"🟡 Предупреждений: {len(self.warnings)}")
        return " | ".join(parts) if parts else "✅ Ошибок нет"

def find_connected_chain(start_idx: int, objects: List[DXFObject], tolerance: float) -> Set[int]:
    chain, queue = {start_idx}, [start_idx]
    endpoints = {i: get_entity_endpoints(obj.entity) for i, obj in enumerate(objects)}
    while queue:
        curr = queue.pop(0)
        p1, p2 = endpoints.get(curr, (None, None))
        if not p1 or not p2: continue
        for idx, obj in enumerate(objects):
            if idx in chain or obj.status == ObjectStatus.ERROR: continue
            np1, np2 = endpoints.get(idx, (None, None))
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
            chain_idx = find_connected_chain(idx, valid, tolerance)
            visited.update(chain_idx)
            count += 1
            c_objs = [valid[i] for i in chain_idx]
            for i in chain_idx: valid[i].chain_id = count
            details.append({
                'chain_id': count, 'type': 'open' if len(chain_idx) > 1 else 'isolated',
                'objects': [o.num for o in c_objs], 'length': sum(o.length for o in c_objs)
            })
    return count, details