from typing import List, Set
from core.errors import DXFObject, ErrorCollector
from core.geometry import get_entity_endpoints, points_close
from utils.constants import PIERCING_TOLERANCE

def find_connected_chain(start_idx: int, objects: List[DXFObject], tolerance: float) -> Set[int]:
    chain = {start_idx}
    queue = [start_idx]
    endpoints = {i: get_entity_endpoints(obj.entity) for i, obj in enumerate(objects) if obj.entity}
    
    while queue:
        curr = queue.pop(0)
        curr_pts = endpoints.get(curr)
        if not curr_pts: continue
        
        for idx, obj in enumerate(objects):
            if idx in chain: continue
            neighbor_pts = endpoints.get(idx)
            if not neighbor_pts: continue
            if any(points_close(curr_pts[i], neighbor_pts[j], tolerance) for i in (0,1) for j in (0,1)):
                chain.add(idx)
                queue.append(idx)
    return chain

def count_piercings_advanced(objects_data, collector, tolerance=PIERCING_TOLERANCE):
    valid_objs = [o for o in objects_data if o.status.value != 'error']
    visited = set()
    chain_count = 0
    details = []

    for idx, obj in enumerate(valid_objs):
        if idx in visited: continue
        if obj.is_closed or obj.entity_type in ('CIRCLE', 'ELLIPSE'):
            chain = {idx}; c_type = 'closed'
        else:
            chain = find_connected_chain(idx, valid_objs, tolerance); c_type = 'open' if len(chain)>1 else 'isolated'
        
        visited.update(chain)
        chain_count += 1
        for o_idx in chain: valid_objs[o_idx].chain_id = chain_count
        details.append({'chain_id': chain_count, 'type': c_type, 'objects_count': len(chain)})
        
    return chain_count, details