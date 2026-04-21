"""
Геометрические функции и анализ связности
"""

import math
from typing import Tuple, Optional, List, Dict, Any
from collections import defaultdict
from .models import DXFObject
from .errors import ErrorCollector
from .config import TOLERANCE

def get_entity_center(entity: Any) -> Optional[Tuple[float, float]]:
    """
    Получение центра объекта
    
    Args:
        entity: Объект ezdxf
        
    Returns:
        Optional[Tuple[float, float]]: Координаты центра (x, y) или None
    """
    try:
        entity_type = entity.dxftype()
        
        if entity_type == 'LINE':
            start = entity.dxf.start
            end = entity.dxf.end
            return ((start.x + end.x) / 2, (start.y + end.y) / 2)
        
        elif entity_type in ('CIRCLE', 'ARC'):
            center = entity.dxf.center
            return (center.x, center.y)
        
        elif entity_type == 'ELLIPSE':
            center = entity.dxf.center
            return (center.x, center.y)
        
        elif entity_type in ('POLYLINE', 'LWPOLYLINE'):
            points = list(entity.points() if entity_type == 'POLYLINE' 
                         else entity.get_points('xy'))
            if not points:
                return None
            
            if entity_type == 'POLYLINE':
                avg_x = sum(p.x for p in points) / len(points)
                avg_y = sum(p.y for p in points) / len(points)
            else:
                avg_x = sum(p[0] for p in points) / len(points)
                avg_y = sum(p[1] for p in points) / len(points)
            
            return (avg_x, avg_y)
        
        elif entity_type == 'SPLINE':
            points = list(entity.control_points)
            if not points:
                return None
            avg_x = sum(p.x for p in points) / len(points)
            avg_y = sum(p.y for p in points) / len(points)
            return (avg_x, avg_y)
        
        return None
        
    except Exception:
        return None

def check_is_closed(entity: Any) -> bool:
    """
    Проверка, является ли объект замкнутым
    
    Args:
        entity: Объект ezdxf
        
    Returns:
        bool: True если объект замкнут
    """
    try:
        entity_type = entity.dxftype()
        
        # Круги и эллипсы всегда замкнуты (если это полный круг/эллипс)
        if entity_type == 'CIRCLE':
            return True
        
        if entity_type == 'ELLIPSE':
            start = entity.dxf.start_param if hasattr(entity.dxf, 'start_param') else 0
            end = entity.dxf.end_param if hasattr(entity.dxf, 'end_param') else 2 * math.pi
            return abs(abs(end - start) - 2 * math.pi) < 0.01
        
        # Полилинии могут быть замкнутыми
        if entity_type == 'POLYLINE':
            return entity.is_closed
        
        if entity_type == 'LWPOLYLINE':
            return entity.closed
        
        # Линии и дуги всегда открыты
        return False
        
    except Exception:
        return False

def get_endpoints(entity: Any) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    Получение конечных точек незамкнутого объекта
    
    Args:
        entity: Объект ezdxf
        
    Returns:
        Optional[Tuple[point1, point2]]: Кортеж из двух точек или None
    """
    try:
        entity_type = entity.dxftype()
        
        if entity_type == 'LINE':
            start = entity.dxf.start
            end = entity.dxf.end
            return ((start.x, start.y), (end.x, end.y))
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = math.radians(entity.dxf.start_angle)
            end_angle = math.radians(entity.dxf.end_angle)
            
            start_point = (
                center.x + radius * math.cos(start_angle),
                center.y + radius * math.sin(start_angle)
            )
            end_point = (
                center.x + radius * math.cos(end_angle),
                center.y + radius * math.sin(end_angle)
            )
            
            return (start_point, end_point)
        
        elif entity_type == 'LWPOLYLINE':
            if entity.closed:
                return None
            points = list(entity.get_points('xy'))
            if len(points) < 2:
                return None
            return ((points[0][0], points[0][1]), (points[-1][0], points[-1][1]))
        
        elif entity_type == 'POLYLINE':
            if entity.is_closed:
                return None
            points = list(entity.points())
            if len(points) < 2:
                return None
            p1, p2 = points[0], points[-1]
            return ((p1.x, p1.y), (p2.x, p2.y))
        
        elif entity_type == 'SPLINE':
            try:
                flat_points = list(entity.flattening(0.01))
                if len(flat_points) < 2:
                    return None
                return (flat_points[0], flat_points[-1])
            except Exception:
                return None
        
        return None
        
    except Exception:
        return None

def distance_between_points(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Расстояние между двумя точками"""
    return math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)

def count_piercings_advanced(
    objects: List[DXFObject],
    collector: ErrorCollector,
    tolerance: float = TOLERANCE
) -> Tuple[int, Dict[str, Any]]:
    """
    Подсчёт врезок с использованием алгоритма поиска связных компонент
    
    Args:
        objects: Список объектов DXF
        collector: Коллектор ошибок
        tolerance: Допуск для определения связности (мм)
        
    Returns:
        Tuple[int, dict]: (количество врезок, детальная статистика)
    """
    # Разделяем объекты на замкнутые и открытые
    closed_objects = []
    open_objects = []
    
    for obj in objects:
        if obj.is_closed:
            closed_objects.append(obj)
        else:
            open_objects.append(obj)
    
    # Каждый замкнутый объект = отдельная цепь
    num_closed = len(closed_objects)
    
    # Для открытых объектов строим граф связности
    n = len(open_objects)
    if n == 0:
        chains = []
        for i, obj in enumerate(closed_objects):
            obj.chain_id = i
            chains.append({
                'chain_id': i,
                'type': 'closed',
                'objects': [obj.num],
                'entity_types': [obj.entity_type],
                'objects_count': 1,
                'total_length': obj.length
            })
        
        return num_closed, {
            'total': num_closed,
            'closed_objects': num_closed,
            'open_chains': 0,
            'isolated_objects': 0,
            'tolerance_used': tolerance,
            'chains': chains
        }
    
    # Создаём граф смежности для открытых объектов
    graph = defaultdict(list)
    endpoints_map = {}
    
    for i, obj in enumerate(open_objects):
        endpoints = get_endpoints(obj.entity)
        if endpoints:
            endpoints_map[i] = endpoints
    
    # Строим рёбра графа
    for i in range(n):
        if i not in endpoints_map:
            continue
        
        start_i, end_i = endpoints_map[i]
        
        for j in range(i + 1, n):
            if j not in endpoints_map:
                continue
            
            start_j, end_j = endpoints_map[j]
            
            # Проверяем все комбинации конечных точек
            min_dist = min(
                distance_between_points(start_i, start_j),
                distance_between_points(start_i, end_j),
                distance_between_points(end_i, start_j),
                distance_between_points(end_i, end_j)
            )
            
            if min_dist < tolerance:
                graph[i].append(j)
                graph[j].append(i)
    
    # Поиск связных компонент (DFS)
    visited = set()
    chains = []
    chain_id = num_closed
    
    def dfs(node, component):
        visited.add(node)
        component.append(node)
        for neighbor in graph[node]:
            if neighbor not in visited:
                dfs(neighbor, component)
    
    # Находим все компоненты
    open_chains_count = 0
    isolated_count = 0
    
    for i in range(n):
        if i not in visited:
            component = []
            dfs(i, component)
            
            # Назначаем chain_id всем объектам в компоненте
            for idx in component:
                open_objects[idx].chain_id = chain_id
            
            # Собираем статистику по цепи
            chain_length = sum(open_objects[idx].length for idx in component)
            chain_types = [open_objects[idx].entity_type for idx in component]
            chain_nums = [open_objects[idx].num for idx in component]
            
            if len(component) == 1:
                chain_type = 'isolated'
                isolated_count += 1
            else:
                chain_type = 'open'
                open_chains_count += 1
            
            chains.append({
                'chain_id': chain_id,
                'type': chain_type,
                'objects': chain_nums,
                'entity_types': chain_types,
                'objects_count': len(component),
                'total_length': chain_length
            })
            
            chain_id += 1
    
    # Добавляем замкнутые объекты в список цепей
    for i, obj in enumerate(closed_objects):
        obj.chain_id = i
        chains.append({
            'chain_id': i,
            'type': 'closed',
            'objects': [obj.num],
            'entity_types': [obj.entity_type],
            'objects_count': 1,
            'total_length': obj.length
        })
    
    num_open_chains = len(visited) if n > 0 else 0
    num_open_chains = open_chains_count + isolated_count
    
    total_piercings = num_closed + open_chains_count + isolated_count
    
    return total_piercings, {
        'total': total_piercings,
        'closed_objects': num_closed,
        'open_chains': open_chains_count,
        'isolated_objects': isolated_count,
        'tolerance_used': tolerance,
        'chains': sorted(chains, key=lambda x: x['chain_id'])
    }

def get_piercing_statistics(piercing_details: Dict[str, Any]) -> str:
    """
    Форматирование статистики врезок для вывода
    
    Args:
        piercing_details: Словарь с деталями врезок
        
    Returns:
        str: Отформатированная строка статистики
    """
    return f"""
    Всего цепей: {piercing_details['total']}
    - Замкнутые контуры: {piercing_details['closed_objects']}
    - Открытые цепи: {piercing_details['open_chains']}
    - Изолированные объекты: {piercing_details['isolated_objects']}
    Допуск: {piercing_details['tolerance_used']} мм
    """