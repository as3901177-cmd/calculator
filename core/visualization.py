import matplotlib.pyplot as plt
import matplotlib.patches as patches
from core.geometry import get_entity_center_with_offset, normalize_angle, safe_coordinate, safe_float
from utils.constants import ACI_COLORS
import math

def get_aci_color(color_id):
    return ACI_COLORS.get(color_id, '#000000')

def draw_entity_manually(ax, entity, color='#000000', linewidth=1.5):
    etype = entity.dxftype()
    try:
        if etype == 'LINE':
            p1, p2 = safe_coordinate(entity.dxf.start), safe_coordinate(entity.dxf.end)
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=color, linewidth=linewidth)
        elif etype == 'CIRCLE':
            c = safe_coordinate(entity.dxf.center)
            r = safe_float(entity.dxf.radius)
            ax.add_patch(plt.Circle(c, r, fill=False, edgecolor=color, linewidth=linewidth))
        elif etype == 'ARC':
            c = safe_coordinate(entity.dxf.center)
            r = safe_float(entity.dxf.radius)
            s, e = entity.dxf.start_angle, entity.dxf.end_angle
            ax.add_patch(patches.Arc(c, r*2, r*2, theta1=s, theta2=e, edgecolor=color, linewidth=linewidth))
        elif etype in ('LWPOLYLINE', 'POLYLINE'):
            pts = list(entity.points())
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if entity.is_closed: 
                xs.append(xs[0]); ys.append(ys[0])
            ax.plot(xs, ys, color=color, linewidth=linewidth)
    except: pass

def visualize_dxf_with_status_indicators(doc, objects_data, collector, show_markers=True, multiplier=1.0, use_orig=False, show_chains=False):
    fig, ax = plt.subplots(figsize=(12, 10))
    msp = doc.modelspace()
    
    status_map = {obj.real_num: obj for obj in objects_data}
    
    import colorsys
    chain_colors = {}
    if show_chains:
        u_chains = set(o.chain_id for o in objects_data if o.chain_id > 0)
        for i, c_id in enumerate(u_chains):
            rgb = colorsys.hsv_to_rgb(i/max(len(u_chains),1), 0.8, 0.9)
            chain_colors[c_id] = '#%02x%02x%02x' % (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))

    real_idx = 0
    for entity in msp:
        real_idx += 1
        obj = status_map.get(real_idx)
        if not obj:
            draw_entity_manually(ax, entity, color='#CCCCCC', linewidth=0.5)
            continue
            
        color = '#000000'
        if show_chains and obj.chain_id > 0: color = chain_colors.get(obj.chain_id)
        elif obj.status.value == 'error': color = '#FF0000'
        elif obj.status.value == 'warning': color = '#FF8800'
        elif use_orig: color = get_aci_color(obj.original_color)
        
        draw_entity_manually(ax, entity, color=color, linewidth=1.5)
        
        if show_markers:
            c = obj.center
            ax.text(c[0], c[1], str(obj.num), fontsize=8*multiplier, bbox=dict(facecolor='white', alpha=0.5))

    ax.set_aspect('equal')
    ax.axis('off')
    return fig, None