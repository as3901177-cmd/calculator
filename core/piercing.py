from typing import List, Set, Dict, Any, Tuple
from core.errors import DXFObject, ObjectStatus, ErrorCollector
from core.geometry import get_entity_endpoints, points_close
from utils.constants import PIERCING_TOLERANCE

def find_connected_chain(start_idx: int, objects: List[DXFObject], tolerance: float) -> Set[int]:
    chain = {start_idx}
    queue = [start_idx]
    endpoints = {i: get_entity_endpoints(obj.entity) for i, obj in enumerate(objects) if obj.entity}
    
    while queue:
        curr = queue.pop(0)
        curr_pts = endpoints.get(curr)
        if not curr_pts or None in curr_pts: continue
        
        for idx, obj in enumerate(objects):
            if idx in chain or obj.status == ObjectStatus.ERROR: continue
            neighbor_pts = endpoints.get(idx)
            if not neighbor_pts or None in neighbor_pts: continue
            
            if any(points_close(curr_pts[i], neighbor_pts[j], tolerance) for i in (0,1) for j in (0,1)):
                chain.add(idx)
                queue.append(idx)
    return chain

def count_piercings_advanced(objects_data: List[DXFObject], collector: ErrorCollector, tolerance: float = PIERCING_TOLERANCE):
    valid_objs = [obj for obj in objects_data if obj.status != ObjectStatus.ERROR]
    visited = set()
    chains_details = []
    chain_count = 0

    for idx, obj in enumerate(valid_objs):
        if idx in visited: continue
        
        if obj.is_closed or obj.entity_type in ('CIRCLE', 'ELLIPSE'):
            chain = {idx}
            c_type = 'closed'
        else:
            chain = find_connected_chain(idx, valid_objs, tolerance)
            c_type = 'open' if len(chain) > 1 else 'isolated'
            
        visited.update(chain)
        chain_count += 1
        
        chain_objs = [valid_objs[i] for i in chain]
        for o in chain_objs: o.chain_id = chain_count
        
        chains_details.append({
            'chain_id': chain_count,
            'type': c_type,
            'objects_count': len(chain),
            'objects': [o.num for o in chain_objs],
            'total_length': sum(o.length for o in chain_objs)
        })
        
    return chain_count, {'total': chain_count, 'chains': chains_details, 'tolerance_used': tolerance}

def get_piercing_statistics(objects_data: List[DXFObject]):
    # Упрощенная версия для примера
    chains = set(obj.chain_id for obj in objects_data if obj.chain_id > 0)
    return {'total': len(chains)}