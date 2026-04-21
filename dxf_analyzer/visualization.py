import matplotlib.pyplot as plt
import math
from .config import get_aci_color, MARKER_BG_ERROR, MARKER_BG_WARNING, MARKER_BG_NORMAL, COLOR_ERROR_OVERLAY
from .models import ObjectStatus
from .utils import safe_coordinate

def get_entity_center(entity):
    etype = entity.dxftype()
    try:
        if etype == 'LINE':
            p1, p2 = safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
            return (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
        if etype in ('CIRCLE', 'ARC', 'ELLIPSE'): return safe_coordinate(entity.dxf.center)
        pts = list(entity.points())
        return (min(p[0] for p in pts)+max(p[0] for p in pts))/2, (min(p[1] for p in pts)+max(p[1] for p in pts))/2
    except: return (0, 0)

def draw_entity(ax, entity, color='#000000', lw=1.5, use_orig=False):
    etype = entity.dxftype()
    if use_orig: color = get_aci_color(getattr(entity.dxf, 'color', 256))
    try:
        if etype == 'LINE':
            p1, p2 = safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=color, lw=lw)
        elif etype == 'CIRCLE':
            c, r = safe_coordinate(entity.dxf.center), entity.dxf.radius
            ax.add_patch(plt.Circle(c, r, fill=False, edgecolor=color, lw=lw))
        elif etype == 'ARC':
            c, r = safe_coordinate(entity.dxf.center), entity.dxf.radius
            s, e = entity.dxf.start_angle, entity.dxf.end_angle
            span = (e - s) % 360
            theta = [math.radians(s + span*i/50) for i in range(51)]
            ax.plot([c[0]+r*math.cos(t) for t in theta], [c[1]+r*math.sin(t) for t in theta], color=color, lw=lw)
        elif etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if entity.is_closed: xs.append(xs[0]); ys.append(ys[0])
            ax.plot(xs, ys, color=color, lw=lw)
    except: pass

def create_visual(doc, objects_data, mode="Исходные цвета", markers=True, font_size=1.0):
    fig, ax = plt.subplots(figsize=(12, 8))
    msp = doc.modelspace()
    status_map = {obj.real_num: obj for obj in objects_data}
    
    for i, ent in enumerate(msp, 1):
        obj = status_map.get(i)
        if not obj:
            draw_entity(ax, ent, color='#DDDDDD', lw=0.5)
            continue
        
        if mode == "Визуализация цепей":
            import colorsys
            color = colorsys.hsv_to_rgb((obj.chain_id * 0.618) % 1.0, 0.8, 0.8)
            draw_entity(ax, ent, color=color, lw=2.0)
        elif mode == "Исходные цвета":
            draw_entity(ax, ent, use_orig=True)
            if obj.status == ObjectStatus.ERROR: draw_entity(ax, ent, color=COLOR_ERROR_OVERLAY, lw=2.5)
        else:
            c = '#FF0000' if obj.status == ObjectStatus.ERROR else '#FF8800' if obj.status == ObjectStatus.WARNING else '#000000'
            draw_entity(ax, ent, color=c, lw=1.5)

        if markers:
            bg = MARKER_BG_ERROR if obj.status == ObjectStatus.ERROR else MARKER_BG_WARNING if obj.status == ObjectStatus.WARNING else MARKER_BG_NORMAL
            ax.text(obj.center[0], obj.center[1], str(obj.num), fontsize=8*font_size, bbox=dict(facecolor=bg, color='white', boxstyle='circle'))

    ax.set_aspect('equal'); ax.axis('off')
    return fig