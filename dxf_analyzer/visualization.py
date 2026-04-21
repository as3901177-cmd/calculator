import math
import matplotlib.pyplot as plt
import logging
from typing import List, Tuple, Any
from .config import get_aci_color, COLOR_ERROR_OVERLAY, COLOR_WARNING_OVERLAY, MARKER_BG_ERROR, MARKER_BG_WARNING, MARKER_BG_NORMAL, MARKER_COLOR_ERROR, MARKER_COLOR_WARNING, MARKER_COLOR_NORMAL
from .models import DXFObject, ObjectStatus
from .utils import safe_coordinate, safe_float, normalize_angle
from .geometry import check_is_closed

logger = logging.getLogger(__name__)

def get_entity_center(entity: Any) -> Tuple[float, float]:
    etype = entity.dxftype()
    try:
        if etype == 'LINE':
            p1, p2 = safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
            return (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
        elif etype in ('CIRCLE', 'ARC', 'ELLIPSE'):
            return safe_coordinate(entity.dxf.center)
        elif etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    except: pass
    return (0.0, 0.0)

def draw_entity_manually(ax, entity, color='#000000', linewidth=1.5, use_orig=False):
    etype = entity.dxftype()
    if use_orig: color = get_aci_color(getattr(entity.dxf, 'color', 256))
    try:
        if etype == 'LINE':
            p1, p2 = safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=color, lw=linewidth)
        elif etype == 'CIRCLE':
            c, r = safe_coordinate(entity.dxf.center), entity.dxf.radius
            ax.add_patch(plt.Circle(c, r, fill=False, edgecolor=color, lw=linewidth))
        elif etype == 'ARC':
            c, r = safe_coordinate(entity.dxf.center), entity.dxf.radius
            s, e = entity.dxf.start_angle, entity.dxf.end_angle
            span = e - s
            if span < 0: span += 360
            theta = [math.radians(s + span * i / 50) for i in range(51)]
            ax.plot([c[0]+r*math.cos(t) for t in theta], [c[1]+r*math.sin(t) for t in theta], color=color, lw=linewidth)
        elif etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if check_is_closed(entity):
                xs.append(xs[0]); ys.append(ys[0])
            ax.plot(xs, ys, color=color, lw=linewidth)
        return True
    except: return False

def visualize_dxf_with_status_indicators(doc, objects_data, collector, show_markers=True, font_mult=1.0, mode="Исходные цвета"):
    try:
        fig, ax = plt.subplots(figsize=(15, 10))
        msp = doc.modelspace()
        status_map = {obj.real_num: obj for obj in objects_data}
        
        for i, entity in enumerate(msp, 1):
            obj = status_map.get(i)
            if not obj:
                draw_entity_manually(ax, entity, color='#CCCCCC', linewidth=0.5)
                continue
            
            if mode == "Визуализация цепей":
                import colorsys
                hue = (obj.chain_id * 0.618033) % 1.0
                color = colorsys.hsv_to_rgb(hue, 0.8, 0.8)
                draw_entity_manually(ax, entity, color=color, linewidth=2.0)
            elif mode == "Исходные цвета":
                draw_entity_manually(ax, entity, use_orig=True)
                if obj.status == ObjectStatus.ERROR: draw_entity_manually(ax, entity, color=COLOR_ERROR_OVERLAY, linewidth=2.0)
            else:
                color = '#FF0000' if obj.status == ObjectStatus.ERROR else '#FF8800' if obj.status == ObjectStatus.WARNING else '#000000'
                draw_entity_manually(ax, entity, color=color, linewidth=1.5)

            if show_markers:
                c = obj.center
                bg = MARKER_BG_ERROR if obj.status == ObjectStatus.ERROR else MARKER_BG_WARNING if obj.status == ObjectStatus.WARNING else MARKER_BG_NORMAL
                txt = MARKER_COLOR_ERROR if obj.status == ObjectStatus.ERROR else MARKER_COLOR_WARNING if obj.status == ObjectStatus.WARNING else MARKER_COLOR_NORMAL
                ax.text(c[0], c[1], str(obj.num), fontsize=8*font_mult, color=txt, bbox=dict(facecolor=bg, edgecolor='none', boxstyle='circle'))

        ax.set_aspect('equal'); ax.axis('off')
        return fig, None
    except Exception as e: return None, str(e)