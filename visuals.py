import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import math
import logging
from typing import Tuple, Optional, List, Dict, Any
from config import *
from models import ObjectStatus, DXFObject, ErrorCollector
from geometry import safe_coordinate, safe_float, normalize_angle, get_layer_info

logger = logging.getLogger(__name__)

def get_entity_center_with_offset(entity: Any, offset_distance: float) -> Tuple[float, float]:
    """Возвращает координаты для размещения маркера рядом с объектом."""
    etype = entity.dxftype()
    try:
        if etype == 'LINE':
            x1, y1 = safe_coordinate(entity.dxf.start)
            x2, y2 = safe_coordinate(entity.dxf.end)
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length > 0:
                return cx + (-dy/length)*offset_distance, cy + (dx/length)*offset_distance
            return cx, cy
        
        if etype in ('CIRCLE', 'ARC', 'ELLIPSE'):
            cx, cy = safe_coordinate(entity.dxf.center)
            r = safe_float(entity.dxf.radius) if etype != 'ELLIPSE' else 10.0
            return cx + r + offset_distance, cy
            
        if etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            if pts:
                return pts[0][0] + offset_distance, pts[0][1] + offset_distance
    except: pass
    return (0.0, 0.0)

def draw_entity_manually(ax: Any, entity: Any, color: str = '#000000', 
                         linewidth: float = 1.5, use_original_color: bool = False) -> bool:
    """Отрисовка объекта на осях Matplotlib."""
    etype = entity.dxftype()
    if use_original_color:
        _, original_color = get_layer_info(entity)
        color = get_aci_color(original_color)
    
    try:
        if etype == 'LINE':
            x1, y1 = safe_coordinate(entity.dxf.start)
            x2, y2 = safe_coordinate(entity.dxf.end)
            ax.plot([x1, x2], [y1, y2], color=color, linewidth=linewidth, zorder=1)
            return True
        
        elif etype == 'CIRCLE':
            cx, cy = safe_coordinate(entity.dxf.center)
            r = safe_float(entity.dxf.radius)
            circle = plt.Circle((cx, cy), r, fill=False, edgecolor=color, linewidth=linewidth)
            ax.add_patch(circle)
            return True
        
        elif etype == 'ARC':
            cx, cy = safe_coordinate(entity.dxf.center)
            r = safe_float(entity.dxf.radius)
            sa, ea = entity.dxf.start_angle, entity.dxf.end_angle
            # Аппроксимация дуги линиями
            span = (ea - sa) % 360
            if span == 0: span = 360
            num_pts = 50
            theta = [math.radians(sa + i * span / num_pts) for i in range(num_pts + 1)]
            xs = [cx + r * math.cos(t) for t in theta]
            ys = [cy + r * math.sin(t) for t in theta]
            ax.plot(xs, ys, color=color, linewidth=linewidth)
            return True

        elif etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            if len(pts) >= 2:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                if entity.closed:
                    xs.append(xs[0])
                    ys.append(ys[0])
                ax.plot(xs, ys, color=color, linewidth=linewidth)
                return True
                
        elif etype == 'SPLINE':
            pts = list(entity.flattening(0.1))
            if len(pts) >= 2:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, linewidth=linewidth)
                return True
    except: return False
    return False

def visualize_dxf_with_status_indicators(
    doc: Any, 
    objects_data: List[DXFObject],
    collector: ErrorCollector,
    show_markers: bool = True,
    font_size_multiplier: float = 1.0,
    use_original_colors: bool = False,
    show_chains: bool = False
):
    """Основная функция визуализации чертежа."""
    try:
        fig, ax = plt.subplots(figsize=(12, 10), dpi=100)
        fig.patch.set_facecolor('#E5E5E5')
        ax.set_facecolor('#F0F0F0')
        
        status_map = {obj.real_num: obj for obj in objects_data}
        
        # Генерация цветов для цепей (если нужно)
        chain_colors = {}
        if show_chains:
            import colorsys
            unique_chains = set(obj.chain_id for obj in objects_data if obj.chain_id > 0)
            for i, cid in enumerate(sorted(unique_chains)):
                rgb = colorsys.hsv_to_rgb(i / max(len(unique_chains), 1), 0.7, 0.9)
                chain_colors[cid] = '#{:02x}{:02x}{:02x}'.format(int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))

        msp = doc.modelspace()
        real_num = 0
        for entity in msp:
            real_num += 1
            if real_num not in status_map:
                draw_entity_manually(ax, entity, color='#CCCCCC', linewidth=0.5)
                continue
                
            obj = status_map[real_num]
            
            # Логика цвета
            if show_chains and obj.chain_id > 0:
                color = chain_colors.get(obj.chain_id, '#000000')
                lw = 2.0
            elif use_original_colors:
                draw_entity_manually(ax, entity, use_original_color=True, linewidth=1.5)
                if obj.status == ObjectStatus.ERROR:
                    draw_entity_manually(ax, entity, color=COLOR_ERROR_OVERLAY, linewidth=2.5)
                elif obj.status == ObjectStatus.WARNING:
                    draw_entity_manually(ax, entity, color=COLOR_WARNING_OVERLAY, linewidth=2.5)
                continue
            else:
                color = '#FF0000' if obj.status == ObjectStatus.ERROR else ('#FF8800' if obj.status == ObjectStatus.WARNING else '#000000')
                lw = 1.5 if obj.status == ObjectStatus.NORMAL else 2.0
            
            draw_entity_manually(ax, entity, color=color, linewidth=lw)

        # Рисование маркеров
        if show_markers:
            # Расчет динамического смещения в зависимости от размера чертежа
            x_lims = ax.get_xlim()
            offset = (x_lims[1] - x_lims[0]) * 0.02
            fsize = 8 * font_size_multiplier
            
            for obj in objects_data:
                if obj.entity:
                    mx, my = get_entity_center_with_offset(obj.entity, offset)
                    bg_color = MARKER_BG_ERROR if obj.status == ObjectStatus.ERROR else (MARKER_BG_WARNING if obj.status == ObjectStatus.WARNING else MARKER_BG_NORMAL)
                    
                    ax.text(mx, my, str(obj.num), fontsize=fsize, fontweight='bold',
                            color='white', ha='center', va='center',
                            bbox=dict(boxstyle='circle,pad=0.3', facecolor=bg_color, edgecolor='white', alpha=0.8))

        ax.set_aspect('equal')
        ax.axis('off')
        plt.tight_layout()
        return fig, None
    except Exception as e:
        return None, str(e)