"""
Визуализация DXF объектов с индикацией статусов и цепей.
"""

import math
import colorsys
from typing import Any, Tuple, Optional, List, Dict
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from .config import (
    logger, MAX_CENTER_POINTS, get_aci_color, get_layer_info,
    COLOR_ERROR_OVERLAY, COLOR_WARNING_OVERLAY,
    MARKER_COLOR_NORMAL, MARKER_BG_NORMAL,
    MARKER_COLOR_WARNING, MARKER_BG_WARNING,
    MARKER_COLOR_ERROR, MARKER_BG_ERROR
)
from .models import DXFObject, ObjectStatus
from .errors import ErrorCollector
from .utils import safe_float, safe_coordinate
from .calculators import calculators
from .geometry import get_entity_center, get_entity_center_with_offset


def normalize_angle(angle_deg: float) -> float:
    """Нормализует угол в диапазон [0, 360)."""
    return angle_deg % 360.0


def draw_entity_manually(ax: Any, entity: Any, color: str = '#000000',
                         linewidth: float = 1.5, use_original_color: bool = False) -> bool:
    """Рисует объект вручную с указанным цветом."""
    entity_type = entity.dxftype()
    
    if use_original_color:
        _, original_color = get_layer_info(entity)
        color = get_aci_color(original_color)
    
    try:
        if entity_type == 'LINE':
            x1, y1 = safe_coordinate(entity.dxf.start)
            x2, y2 = safe_coordinate(entity.dxf.end)
            if None not in (x1, y1, x2, y2):
                ax.plot([x1, x2], [y1, y2], color=color, linewidth=linewidth, zorder=1)
                return True
        
        elif entity_type == 'CIRCLE':
            x, y = safe_coordinate(entity.dxf.center)
            radius = safe_float(entity.dxf.radius)
            if x is not None and y is not None and radius and radius > 0:
                ax.add_patch(plt.Circle((x, y), radius, fill=False,
                                       edgecolor=color, linewidth=linewidth, zorder=1))
                return True
        
        elif entity_type == 'ARC':
            x, y = safe_coordinate(entity.dxf.center)
            radius = safe_float(entity.dxf.radius)
            start_angle = safe_float(entity.dxf.start_angle)
            end_angle = safe_float(entity.dxf.end_angle)
            
            if any(v is None for v in (x, y, radius, start_angle, end_angle)):
                return False
            
            start_norm, end_norm = normalize_angle(start_angle), normalize_angle(end_angle)
            angle_diff = end_norm - start_norm if start_norm <= end_norm else 360 - (start_norm - end_norm)
            
            if angle_diff < 0.001:
                return False
            
            theta = [start_norm + i * angle_diff / 50 for i in range(51)]
            xs = [x + radius * math.cos(math.radians(t)) for t in theta]
            ys = [y + radius * math.sin(math.radians(t)) for t in theta]
            ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
            return True
        
        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
            return _draw_polyline(ax, entity, color, linewidth)
        
        elif entity_type == 'SPLINE':
            return _draw_spline(ax, entity, color, linewidth)
        
        elif entity_type == 'ELLIPSE':
            return _draw_ellipse(ax, entity, color, linewidth)
    
    except Exception as e:
        logger.debug(f"Ошибка при рисовании: {e}")
    
    return False


def _draw_polyline(ax: Any, entity: Any, color: str, linewidth: float) -> bool:
    """Отрисовка полилинии."""
    try:
        if entity.dxftype() == 'LWPOLYLINE':
            with entity.points('xy') as pts:
                points = [(x, y) for p in pts 
                         if (x := safe_float(p[0])) is not None 
                         and (y := safe_float(p[1])) is not None]
        else:
            points = [(x, y) for p in entity.points()
                     if (x := safe_float(p[0])) is not None
                     and (y := safe_float(p[1])) is not None]
        
        if len(points) >= 2:
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            
            try:
                is_closed = (entity.close if hasattr(entity, 'close') 
                           else bool(entity.dxf.flags & 1))
            except:
                is_closed = False
            
            if is_closed:
                xs.append(xs[0])
                ys.append(ys[0])
            
            ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
            return True
    except Exception as e:
        logger.debug(f"Ошибка при рисовании полилинии: {e}")
    return False


def _draw_spline(ax: Any, entity: Any, color: str, linewidth: float) -> bool:
    """Отрисовка сплайна."""
    try:
        points = []
        for i, pt in enumerate(entity.flattening(0.01)):
            if i >= 5000:
                break
            if (x := safe_float(pt[0])) is not None and (y := safe_float(pt[1])) is not None:
                points.append((x, y))
        
        if len(points) >= 2:
            ax.plot([p[0] for p in points], [p[1] for p in points],
                   color=color, linewidth=linewidth, zorder=1)
            return True
    except Exception as e:
        logger.debug(f"Ошибка при рисовании сплайна: {e}")
    return False


def _draw_ellipse(ax: Any, entity: Any, color: str, linewidth: float) -> bool:
    """Отрисовка эллипса."""
    try:
        x, y = safe_coordinate(entity.dxf.center)
        ratio = safe_float(entity.dxf.ratio)
        major_axis = entity.dxf.major_axis
        
        if x is None or y is None or ratio is None:
            return False
        
        mx, my = safe_float(major_axis.x), safe_float(major_axis.y)
        if mx is None or my is None:
            return False
        
        a = math.sqrt(mx**2 + my**2)
        b = a * ratio
        angle = math.atan2(my, mx)
        
        if a <= 0 or b <= 0:
            return False
        
        t = [i * 2 * math.pi / 100 for i in range(101)]
        xs = [x + a * math.cos(ti) * math.cos(angle) - b * math.sin(ti) * math.sin(angle) for ti in t]
        ys = [y + a * math.cos(ti) * math.sin(angle) + b * math.sin(ti) * math.cos(angle) for ti in t]
        ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=1)
        return True
    except Exception as e:
        logger.debug(f"Ошибка при рисовании эллипса: {e}")
    return False


def _generate_chain_colors(unique_chains: set) -> Dict[int, str]:
    """Генерирует уникальные цвета для цепей."""
    colors = {}
    for i, chain_id in enumerate(sorted(unique_chains)):
        hue = i / max(len(unique_chains), 1)
        rgb = colorsys.hsv_to_rgb(hue, 0.7, 0.9)
        colors[chain_id] = '#{:02x}{:02x}{:02x}'.format(
            int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255)
        )
    return colors


def visualize_dxf_with_status_indicators(
    doc: Any,
    objects_data: List[DXFObject],
    collector: ErrorCollector,
    show_markers: bool = True,
    font_size_multiplier: float = 1.0,
    use_original_colors: bool = False,
    show_chains: bool = False
) -> Tuple[Optional[Any], Optional[str]]:
    """
    Создает визуализацию с цветовой индикацией статуса объектов.
    """
    fig = None
    try:
        fig, ax = plt.subplots(figsize=(20, 16), dpi=100)
        fig.patch.set_facecolor('#E5E5E5')
        ax.set_facecolor('#F0F0F0')
        
        msp = doc.modelspace()
        
        # Карта статусов
        status_by_real_num = {
            obj.real_num: (obj.status, obj.issue_description, obj.chain_id)
            for obj in objects_data
        }
        
        # Цвета для цепей
        chain_colors = _generate_chain_colors(
            {obj.chain_id for obj in objects_data if obj.chain_id > 0}
        ) if show_chains else {}
        
        # Рисуем объекты
        real_object_num = 0
        for entity in msp:
            real_object_num += 1
            entity_type = entity.dxftype()
            
            if entity_type not in calculators:
                continue
            
            if real_object_num in status_by_real_num:
                status, _, chain_id = status_by_real_num[real_object_num]
                
                if show_chains and chain_id > 0:
                    color = chain_colors.get(chain_id, '#000000')
                    draw_entity_manually(ax, entity, color=color, linewidth=2.0)
                elif use_original_colors:
                    draw_entity_manually(ax, entity, use_original_color=True, linewidth=1.5)
                    if status == ObjectStatus.ERROR:
                        draw_entity_manually(ax, entity, color=COLOR_ERROR_OVERLAY, linewidth=2.5)
                    elif status == ObjectStatus.WARNING:
                        draw_entity_manually(ax, entity, color=COLOR_WARNING_OVERLAY, linewidth=2.5)
                else:
                    color_map = {
                        ObjectStatus.ERROR: '#FF0000',
                        ObjectStatus.WARNING: '#FF8800',
                        ObjectStatus.NORMAL: '#000000'
                    }
                    color = color_map.get(status, '#000000')
                    lw = 2.0 if status != ObjectStatus.NORMAL else 1.5
                    draw_entity_manually(ax, entity, color=color, linewidth=lw)
            else:
                draw_entity_manually(ax, entity, color='#CCCCCC', linewidth=1.0)
        
        # Маркеры
        if show_markers and objects_data:
            _draw_markers(ax, objects_data, show_chains, chain_colors, font_size_multiplier)
        
        # Легенда
        if show_chains:
            ax.legend(handles=[Patch(facecolor='#888888', edgecolor='black',
                                    label=f'Цепей найдено: {len(chain_colors)}')],
                     loc='lower left', fontsize=10, framealpha=0.95, fancybox=True, shadow=True)
        elif not use_original_colors:
            ax.legend(handles=[
                Patch(facecolor='#000000', edgecolor='black', label='✓ Нормальные'),
                Patch(facecolor='#FF8800', edgecolor='black', label='⚠ Коррекция'),
                Patch(facecolor='#FF0000', edgecolor='black', label='✗ Ошибки'),
                Patch(facecolor='#CCCCCC', edgecolor='black', label='- Пропущены'),
            ], loc='lower left', fontsize=10, framealpha=0.95, fancybox=True, shadow=True)
        
        ax.set_aspect('equal')
        ax.autoscale()
        ax.margins(0.05)
        ax.axis('off')
        
        title = f"Анализ чертежа | Объектов обработано: {len(objects_data)}"
        if collector.has_errors:
            title += f" | Ошибок: {len(collector.errors)}"
        fig.suptitle(title, fontsize=12, fontweight='bold')
        plt.tight_layout(pad=0.3)
        
        return fig, None
    
    except MemoryError as e:
        return None, f"Недостаточно памяти для визуализации: {e}"
    except Exception as e:
        return None, f"Ошибка визуализации: {e}"


def _draw_markers(ax: Any, objects_data: List[DXFObject], show_chains: bool,
                  chain_colors: Dict[int, str], font_size_multiplier: float):
    """Рисует маркеры с номерами объектов."""
    valid_objects = [obj for obj in objects_data if obj.center[0] != 0 or obj.center[1] != 0]
    if not valid_objects:
        return
    
    all_x, all_y = [obj.center[0] for obj in valid_objects], [obj.center[1] for obj in valid_objects]
    if not all_x or not all_y:
        return
    
    drawing_size = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
    if drawing_size > 0:
        base_font_size = max(int(drawing_size * 0.003), 7)
        font_size = int(base_font_size * font_size_multiplier)
        offset_distance = drawing_size * 0.015
    else:
        font_size = int(8 * font_size_multiplier)
        offset_distance = 10
    
    for obj in objects_data:
        if obj.entity is None:
            continue
        
        x, y = get_entity_center_with_offset(obj.entity, offset_distance)
        if x == 0 and y == 0:
            continue
        
        if show_chains and obj.chain_id > 0:
            marker_color, marker_bg = '#FFFFFF', chain_colors.get(obj.chain_id, '#000000')
        elif obj.status == ObjectStatus.ERROR:
            marker_color, marker_bg = MARKER_COLOR_ERROR, MARKER_BG_ERROR
        elif obj.status == ObjectStatus.WARNING:
            marker_color, marker_bg = MARKER_COLOR_WARNING, MARKER_BG_WARNING
        else:
            marker_color, marker_bg = MARKER_COLOR_NORMAL, MARKER_BG_NORMAL
        
        ax.annotate(str(obj.num), (x, y), fontsize=font_size, fontweight='bold',
                   ha='center', va='center', color=marker_color, zorder=101,
                   bbox=dict(boxstyle='circle,pad=0.35', facecolor=marker_bg,
                            edgecolor='white', linewidth=1.5, alpha=0.95))