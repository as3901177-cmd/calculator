"""
Геометрические вычисления: центры, концы, анализ связности, подсчёт врезок.
"""

import math
from typing import Any, Tuple, Optional, Set, List, Dict
from collections import defaultdict

from .config import logger, MAX_CENTER_POINTS, PIERCING_TOLERANCE, COORD_EPSILON
from .models import DXFObject, ObjectStatus
from .errors import ErrorCollector
from .utils import safe_float, safe_coordinate


# ==================== ЦЕНТРЫ ОБЪЕКТОВ ====================

def get_entity_center(entity: Any) -> Tuple[float, float]:
    """Возвращает центр объекта."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            x1, y1 = safe_coordinate(entity.dxf.start)
            x2, y2 = safe_coordinate(entity.dxf.end)
            if None in (x1, y1, x2, y2):
                return (0.0, 0.0)
            return ((x1 + x2) / 2, (y1 + y2) / 2)
        
        elif entity_type in ('CIRCLE', 'ARC', 'ELLIPSE'):
            x, y = safe_coordinate(entity.dxf.center)
            return (x or 0.0, y or 0.0)
        
        elif entity_type == 'POINT':
            x, y = safe_coordinate(entity.dxf.location)
            return (x or 0.0, y or 0.0)
        
        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
            points = _get_polyline_points(entity)
            if points:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        
        elif entity_type == 'SPLINE':
            points = _get_spline_points(entity)
            if points:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        
        elif entity_type == 'INSERT':
            x, y = safe_coordinate(entity.dxf.insert)
            return (x or 0.0, y or 0.0)
    
    except Exception as e:
        logger.debug(f"Ошибка получения центра: {e}")
    
    return (0.0, 0.0)


def get_entity_center_with_offset(entity: Any, offset_distance: float) -> Tuple[float, float]:
    """Возвращает центр объекта со смещением для маркеров."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            x1, y1 = safe_coordinate(entity.dxf.start)
            x2, y2 = safe_coordinate(entity.dxf.end)
            
            if None in (x1, y1, x2, y2):
                return (0.0, 0.0)
            
            center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
            dx, dy = x2 - x1, y2 - y1
            line_length = math.hypot(dx, dy)
            
            if line_length > COORD_EPSILON:
                return (center_x + (-dy / line_length) * offset_distance,
                       center_y + (dx / line_length) * offset_distance)
            return (center_x, center_y)
        
        elif entity_type == 'CIRCLE':
            x, y = safe_coordinate(entity.dxf.center)
            radius = safe_float(entity.dxf.radius)
            if x is not None and y is not None and radius is not None:
                return (x + radius + offset_distance, y)
        
        elif entity_type == 'ARC':
            x, y = safe_coordinate(entity.dxf.center)
            radius = safe_float(entity.dxf.radius)
            start_angle = safe_float(entity.dxf.start_angle)
            end_angle = safe_float(entity.dxf.end_angle)
            
            if all(v is not None for v in (x, y, radius, start_angle, end_angle)):
                mid_angle = (math.radians(start_angle) + math.radians(end_angle)) / 2
                if end_angle < start_angle:
                    mid_angle += math.pi
                return (x + (radius + offset_distance) * math.cos(mid_angle),
                       y + (radius + offset_distance) * math.sin(mid_angle))
        
        elif entity_type in ('LWPOLYLINE', 'POLYLINE', 'SPLINE'):
            center = get_entity_center(entity)
            points = _get_polyline_points(entity) if entity_type != 'SPLINE' else _get_spline_points(entity)
            
            if points and len(points) >= 2:
                mid_idx = len(points) // 2
                if mid_idx + 1 < len(points):
                    dx = points[mid_idx + 1][0] - points[mid_idx][0]
                    dy = points[mid_idx + 1][1] - points[mid_idx][1]
                    seg_length = math.hypot(dx, dy)
                    
                    if seg_length > COORD_EPSILON:
                        return (center[0] + (-dy / seg_length) * offset_distance,
                               center[1] + (dx / seg_length) * offset_distance)
            return center
        
        elif entity_type == 'INSERT':
            x, y = safe_coordinate(entity.dxf.insert)
            if x is not None and y is not None:
                return (x + offset_distance, y + offset_distance)
    
    except Exception as e:
        logger.debug(f"Ошибка получения центра со смещением: {e}")
        return get_entity_center(entity)
    
    return (0.0, 0.0)


def _get_polyline_points(entity: Any) -> List[Tuple[float, float]]:
    """Вспомогательная функция получения точек полилинии."""
    try:
        if entity.dxftype() == 'LWPOLYLINE':
            with entity.points('xy') as pts:
                return [(x, y) for p in pts 
                       if (x := safe_float(p[0])) is not None 
                       and (y := safe_float(p[1])) is not None]
        else:
            return [(x, y) for p in entity.points() 
                   if (x := safe_float(p[0])) is not None 
                   and (y := safe_float(p[1])) is not None]
    except (AttributeError, TypeError, ValueError):
        return []


def _get_spline_points(entity: Any, max_points: int = MAX_CENTER_POINTS) -> List[Tuple[float, float]]:
    """Вспомогательная функция получения точек сплайна."""
    try:
        points = []
        for i, pt in enumerate(entity.flattening(0.1)):
            if i >= max_points:
                break
            if (x := safe_float(pt[0])) is not None and (y := safe_float(pt[1])) is not None:
                points.append((x, y))
        return points
    except (AttributeError, TypeError, ValueError):
        return []


# ==================== КОНЦЫ ОБЪЕКТОВ ====================

def get_entity_endpoints(entity: Any) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    """Извлекает начальную и конечную точки объекта."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            x1, y1 = safe_coordinate(entity.dxf.start)
            x2, y2 = safe_coordinate(entity.dxf.end)
            if None in (x1, y1, x2, y2):
                return None, None
            return (x1, y1), (x2, y2)
        
        elif entity_type == 'ARC':
            cx, cy = safe_coordinate(entity.dxf.center)
            radius = safe_float(entity.dxf.radius)
            start_angle = safe_float(entity.dxf.start_angle)
            end_angle = safe_float(entity.dxf.end_angle)
            
            if any(v is None for v in (cx, cy, radius, start_angle, end_angle)):
                return None, None
            
            return (
                (cx + radius * math.cos(math.radians(start_angle)),
                 cy + radius * math.sin(math.radians(start_angle))),
                (cx + radius * math.cos(math.radians(end_angle)),
                 cy + radius * math.sin(math.radians(end_angle)))
            )
        
        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
            points = _get_polyline_points(entity)
            if len(points) >= 2:
                return points[0], points[-1]
        
        elif entity_type == 'SPLINE':
            points = _get_spline_points(entity)
            if len(points) >= 2:
                return points[0], points[-1]
        
        # Замкнутые объекты не имеют концов
        elif entity_type in ('CIRCLE', 'ELLIPSE'):
            return None, None
    
    except Exception as e:
        logger.debug(f"Ошибка извлечения концов {entity_type}: {e}")
    
    return None, None


def points_close(p1: Tuple[float, float], p2: Tuple[float, float], tolerance: float) -> bool:
    """Проверяет близость двух точек."""
    try:
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) < tolerance
    except (TypeError, IndexError):
        return False


# ==================== АНАЛИЗ СВЯЗНОСТИ ====================

def find_connected_chain(start_idx: int, objects: List[DXFObject],
                        tolerance: float) -> Set[int]:
    """
    Находит все объекты, связанные в одну цепь (BFS алгоритм).
    """
    chain = {start_idx}
    queue = [start_idx]
    
    # Кэшируем концы
    endpoints_cache = {
        idx: get_entity_endpoints(obj.entity)
        for idx, obj in enumerate(objects)
        if obj.entity is not None
    }
    
    while queue:
        current_idx = queue.pop(0)
        current_endpoints = endpoints_cache.get(current_idx, (None, None))
        start_pt, end_pt = current_endpoints
        
        if start_pt is None or end_pt is None:
            continue
        
        for idx, obj in enumerate(objects):
            if idx in chain or obj.status not in (ObjectStatus.NORMAL, ObjectStatus.WARNING):
                continue
            
            neighbor_start, neighbor_end = endpoints_cache.get(idx, (None, None))
            if neighbor_start is None or neighbor_end is None:
                continue
            
            if any(points_close(a, b, tolerance) 
                   for a in (start_pt, end_pt) 
                   for b in (neighbor_start, neighbor_end)):
                chain.add(idx)
                queue.append(idx)
    
    return chain


def count_piercings_advanced(objects_data: List[DXFObject],
                             collector: ErrorCollector,
                             tolerance: float = PIERCING_TOLERANCE) -> Tuple[int, Dict[str, Any]]:
    """
    Подсчёт врезок с анализом связности контуров.
    """
    valid_objects = [
        obj for obj in objects_data
        if obj.status in (ObjectStatus.NORMAL, ObjectStatus.WARNING)
    ]
    
    if not valid_objects:
        return 0, {
            'total': 0, 'closed_objects': 0, 'open_chains': 0,
            'isolated_objects': 0, 'chains': [], 'tolerance_used': tolerance,
            'total_objects_analyzed': 0, 'total_objects_in_file': len(objects_data)
        }
    
    visited = set()
    chain_count = 0
    chains_details = []
    closed_count = open_chains_count = isolated_count = 0
    
    for idx, obj in enumerate(valid_objects):
        if idx in visited:
            continue
        
        entity_type = obj.entity.dxftype() if obj.entity else "UNKNOWN"
        
        # Замкнутые объекты - отдельные цепи
        if obj.is_closed or entity_type in ('CIRCLE', 'ELLIPSE'):
            chain_count += 1
            closed_count += 1
            visited.add(idx)
            obj.chain_id = chain_count
            
            chains_details.append({
                'chain_id': chain_count, 'type': 'closed', 'objects_count': 1,
                'objects': [obj.num], 'entity_types': [entity_type],
                'total_length': obj.length, 'is_closed': True
            })
            continue
        
        # Открытые объекты - ищем связанные
        chain = find_connected_chain(idx, valid_objects, tolerance)
        
        if len(chain) == 1:
            isolated_count += 1
        else:
            open_chains_count += 1
        
        visited.update(chain)
        chain_count += 1
        
        chain_objects = [valid_objects[i] for i in chain]
        for i in chain:
            valid_objects[i].chain_id = chain_count
        
        chains_details.append({
            'chain_id': chain_count,
            'type': 'open' if len(chain) > 1 else 'isolated',
            'objects_count': len(chain),
            'objects': [obj.num for obj in chain_objects],
            'entity_types': [o.entity.dxftype() if o.entity else "UNKNOWN" for o in chain_objects],
            'total_length': sum(o.length for o in chain_objects),
            'is_closed': False
        })
    
    collector.add_info('PIERCING', 0,
                      f"Анализ связности: найдено {chain_count} цепей "
                      f"({closed_count} замкнутых, {open_chains_count} групп, "
                      f"{isolated_count} изолированных) при допуске {tolerance} мм")
    
    return chain_count, {
        'total': chain_count, 'closed_objects': closed_count,
        'open_chains': open_chains_count, 'isolated_objects': isolated_count,
        'chains': chains_details, 'tolerance_used': tolerance,
        'total_objects_analyzed': len(valid_objects),
        'total_objects_in_file': len(objects_data)
    }


def get_piercing_statistics(objects_data: List[DXFObject]) -> Dict[str, Any]:
    """Возвращает детальную статистику врезок."""
    unique_chains = set()
    closed_chains = set()
    open_chains = set()
    isolated_chains = set()
    errors_excluded = skipped_count = 0
    by_type = defaultdict(int)
    by_status = defaultdict(int)
    
    chains_info = defaultdict(lambda: {
        'objects': [], 'types': set(), 'is_closed': False, 'total_length': 0.0
    })
    
    for obj in objects_data:
        if obj.status == ObjectStatus.ERROR:
            errors_excluded += 1
            continue
        if obj.status == ObjectStatus.SKIPPED:
            skipped_count += 1
            continue
        
        if obj.status in (ObjectStatus.NORMAL, ObjectStatus.WARNING):
            if obj.chain_id > 0:
                unique_chains.add(obj.chain_id)
                chains_info[obj.chain_id]['objects'].append(obj.num)
                chains_info[obj.chain_id]['types'].add(obj.entity_type)
                chains_info[obj.chain_id]['is_closed'] = obj.is_closed
                chains_info[obj.chain_id]['total_length'] += obj.length
                
                if obj.is_closed:
                    closed_chains.add(obj.chain_id)
                elif len(chains_info[obj.chain_id]['objects']) == 1:
                    isolated_chains.add(obj.chain_id)
                else:
                    open_chains.add(obj.chain_id)
            
            by_type[obj.entity_type] += 1
            by_status[obj.status.value] += 1
    
    chains_list = [
        {
            'chain_id': chain_id,
            'objects_count': len(info['objects']),
            'objects': info['objects'],
            'types': list(info['types']),
            'is_closed': info['is_closed'],
            'total_length': info['total_length']
        }
        for chain_id in sorted(unique_chains)
        for info in [chains_info[chain_id]]
    ]
    
    return {
        'total': len(unique_chains),
        'closed': len(closed_chains),
        'open': len(open_chains) - len(isolated_chains),
        'isolated': len(isolated_chains),
        'by_type': dict(by_type),
        'by_status': dict(by_status),
        'errors_excluded': errors_excluded,
        'skipped_count': skipped_count,
        'chains': chains_list
    }