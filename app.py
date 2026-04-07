import subprocess
import sys
import os
import math
import warnings
import io
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import streamlit as st

# ==================== АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ ====================
def install_dependencies():
    """Устанавливает необходимые библиотеки."""
    required = {
        'ezdxf': 'ezdxf>=1.3.0',
        'matplotlib': 'matplotlib>=3.8.0',
        'pandas': 'pandas>=2.2.0',
        'plotly': 'plotly>=5.0.0'
    }
    
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            print(f"📦 Установка {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--no-cache-dir", "--quiet"])

install_dependencies()

# ==================== ИМПОРТЫ ====================
try:
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    import plotly.graph_objects as go
except ImportError as e:
    st.error(f"❌ Ошибка загрузки библиотек: {e}")
    st.info("🔄 Попробуйте перезагрузить страницу")
    st.stop()

warnings.filterwarnings('ignore')

# ==================== РАСЧЁТ ДЛИНЫ ====================

def calc_line_length(entity):
    """LINE: прямая линия."""
    start = entity.dxf.start
    end = entity.dxf.end
    return math.hypot(end.x - start.x, end.y - start.y)

def calc_circle_length(entity):
    """CIRCLE: окружность."""
    return 2 * math.pi * entity.dxf.radius

def calc_arc_length(entity):
    """ARC: дуга окружности."""
    radius = entity.dxf.radius
    start_angle = math.radians(entity.dxf.start_angle)
    end_angle = math.radians(entity.dxf.end_angle)
    angle = end_angle - start_angle
    if angle < 0:
        angle += 2 * math.pi
    return radius * angle

def calc_ellipse_length(entity):
    """ELLIPSE: эллипс или его дуга."""
    try:
        major_axis = entity.dxf.major_axis
        ratio = entity.dxf.ratio
        start_param = entity.dxf.start_param
        end_param = entity.dxf.end_param
        
        a = math.sqrt(major_axis.x**2 + major_axis.y**2 + major_axis.z**2)
        b = a * ratio
        
        angle_span = end_param - start_param
        if angle_span < 0:
            angle_span += 2 * math.pi
        
        if abs(angle_span - 2 * math.pi) < 0.01:
            h = ((a - b) ** 2) / ((a + b) ** 2)
            return math.pi * (a + b) * (1 + 3*h / (10 + math.sqrt(4 - 3*h)))
        
        N = 1000
        length = 0.0
        for i in range(N):
            t1 = start_param + angle_span * i / N
            t2 = start_param + angle_span * (i + 1) / N
            x1, y1 = a * math.cos(t1), b * math.sin(t1)
            x2, y2 = a * math.cos(t2), b * math.sin(t2)
            length += math.hypot(x2 - x1, y2 - y1)
        return length
    except:
        return 0.0

def calc_lwpolyline_length(entity):
    """LWPOLYLINE: лёгкая полилиния с bulge."""
    try:
        points = []
        with entity.points('xyb') as pts:
            for p in pts:
                points.append(p)
        
        if len(points) < 2:
            return 0.0
        
        length = 0.0
        
        for i in range(len(points) - 1):
            x1, y1, bulge1 = points[i][:3] if len(points[i]) >= 3 else (*points[i], 0)
            x2, y2, _ = points[i+1][:3] if len(points[i+1]) >= 3 else (*points[i+1], 0)
            
            if abs(bulge1) < 0.0001:
                length += math.hypot(x2 - x1, y2 - y1)
            else:
                chord = math.hypot(x2 - x1, y2 - y1)
                angle = 4 * math.atan(abs(bulge1))
                radius = chord / (2 * math.sin(angle / 2)) if angle > 0 else 0
                length += radius * angle if radius > 0 else chord
        
        if entity.closed and len(points) > 0:
            x1, y1, bulge1 = points[-1][:3] if len(points[-1]) >= 3 else (*points[-1], 0)
            x2, y2, _ = points[0][:3] if len(points[0]) >= 3 else (*points[0], 0)
            
            if abs(bulge1) < 0.0001:
                length += math.hypot(x2 - x1, y2 - y1)
            else:
                chord = math.hypot(x2 - x1, y2 - y1)
                angle = 4 * math.atan(abs(bulge1))
                radius = chord / (2 * math.sin(angle / 2)) if angle > 0 else 0
                length += radius * angle if radius > 0 else chord
        
        return length
    except:
        return 0.0

def calc_polyline_length(entity):
    """POLYLINE: полилиния."""
    try:
        points = list(entity.points())
        if len(points) < 2:
            return 0.0
        
        length = sum(
            math.hypot(points[i+1][0] - points[i][0], points[i+1][1] - points[i][1])
            for i in range(len(points) - 1)
        )
        
        if entity.is_closed:
            length += math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1])
        
        return length
    except:
        return 0.0

def calc_spline_length(entity):
    """SPLINE: сплайн."""
    try:
        points = list(entity.flattening(0.001))
        if len(points) < 2:
            return 0.0
        return sum(
            math.hypot(points[i+1][0] - points[i][0], points[i+1][1] - points[i][1])
            for i in range(len(points) - 1)
        )
    except:
        return 0.0

def calc_point(entity):
    return 0.1

def calc_mline_length(entity):
    return 0.0

def calc_insert_length(entity):
    return 0.0

def calc_text_length(entity):
    return 0.0

# ==================== ЦЕНТР ОБЪЕКТА С ПЕРПЕНДИКУЛЯРНЫМ СМЕЩЕНИЕМ ====================

def get_entity_center_with_offset(entity, offset_distance):
    """Возвращает центр объекта СО СМЕЩЕНИЕМ от линии."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            s, e = entity.dxf.start, entity.dxf.end
            center_x = (s.x + e.x) / 2
            center_y = (s.y + e.y) / 2
            
            dx = e.x - s.x
            dy = e.y - s.y
            line_length = math.hypot(dx, dy)
            
            if line_length > 0:
                perp_x = -dy / line_length
                perp_y = dx / line_length
                
                offset_x = center_x + perp_x * offset_distance
                offset_y = center_y + perp_y * offset_distance
                
                return (offset_x, offset_y)
            
            return (center_x, center_y)
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = entity.dxf.radius
            return (center.x + radius + offset_distance, center.y)
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = math.radians(entity.dxf.start_angle)
            end_angle = math.radians(entity.dxf.end_angle)
            
            mid_angle = (start_angle + end_angle) / 2
            if end_angle < start_angle:
                mid_angle += math.pi
            
            arc_x = center.x + (radius + offset_distance) * math.cos(mid_angle)
            arc_y = center.y + (radius + offset_distance) * math.sin(mid_angle)
            
            return (arc_x, arc_y)
        
        elif entity_type == 'ELLIPSE':
            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            a = math.sqrt(major_axis.x**2 + major_axis.y**2)
            return (center.x + a + offset_distance, center.y)
        
        elif entity_type == 'POINT':
            loc = entity.dxf.location
            return (loc.x + offset_distance, loc.y + offset_distance)
        
        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
            if entity_type == 'LWPOLYLINE':
                with entity.points('xy') as pts:
                    points = list(pts)
            else:
                points = [(p[0], p[1]) for p in entity.points()]
            
            if points and len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                center_x = (min(xs) + max(xs)) / 2
                center_y = (min(ys) + max(ys)) / 2
                
                dx = points[1][0] - points[0][0]
                dy = points[1][1] - points[0][1]
                seg_length = math.hypot(dx, dy)
                
                if seg_length > 0:
                    perp_x = -dy / seg_length
                    perp_y = dx / seg_length
                    
                    offset_x = center_x + perp_x * offset_distance
                    offset_y = center_y + perp_y * offset_distance
                    
                    return (offset_x, offset_y)
                
                return (center_x, center_y)
        
        elif entity_type == 'SPLINE':
            points = list(entity.flattening(0.1))
            if points and len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                center_x = (min(xs) + max(xs)) / 2
                center_y = (min(ys) + max(ys)) / 2
                
                mid_idx = len(points) // 2
                if mid_idx + 1 < len(points):
                    dx = points[mid_idx + 1][0] - points[mid_idx][0]
                    dy = points[mid_idx + 1][1] - points[mid_idx][1]
                    seg_length = math.hypot(dx, dy)
                    
                    if seg_length > 0:
                        perp_x = -dy / seg_length
                        perp_y = dx / seg_length
                        
                        offset_x = center_x + perp_x * offset_distance
                        offset_y = center_y + perp_y * offset_distance
                        
                        return (offset_x, offset_y)
                
                return (center_x, center_y)
        
        elif entity_type == 'INSERT':
            pos = entity.dxf.insert
            return (pos.x + offset_distance, pos.y + offset_distance)
        
    except:
        pass
    
    return (0, 0)

# ==================== СЛОВАРЬ КАЛЬКУЛЯТОРОВ ====================

calculators = {
    'LINE': calc_line_length,
    'CIRCLE': calc_circle_length,
    'ARC': calc_arc_length,
    'ELLIPSE': calc_ellipse_length,
    'LWPOLYLINE': calc_lwpolyline_length,
    'POLYLINE': calc_polyline_length,
    'SPLINE': calc_spline_length,
    'POINT': calc_point,
    'MLINE': calc_mline_length,
    'INSERT': calc_insert_length,
    'TEXT': calc_text_length,
}

# ==================== ВИЗУАЛИЗАЦИЯ С PLOTLY (ИНТЕРАКТИВНАЯ) ====================

def get_entity_geometry(entity):
    """Извлекает геометрию объекта для отрисовки."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start = entity.dxf.start
            end = entity.dxf.end
            return {'type': 'line', 'x': [start.x, end.x], 'y': [start.y, end.y]}
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = entity.dxf.radius
            theta = [i * 2 * math.pi / 100 for i in range(101)]
            x = [center.x + radius * math.cos(t) for t in theta]
            y = [center.y + radius * math.sin(t) for t in theta]
            return {'type': 'circle', 'x': x, 'y': y}
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = math.radians(entity.dxf.start_angle)
            end_angle = math.radians(entity.dxf.end_angle)
            
            if end_angle < start_angle:
                end_angle += 2 * math.pi
            
            theta = [start_angle + i * (end_angle - start_angle) / 50 for i in range(51)]
            x = [center.x + radius * math.cos(t) for t in theta]
            y = [center.y + radius * math.sin(t) for t in theta]
            return {'type': 'arc', 'x': x, 'y': y}
        
        elif entity_type == 'LWPOLYLINE':
            with entity.points('xy') as points:
                pts = list(points)
                if len(pts) >= 2:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    if entity.closed:
                        xs.append(xs[0])
                        ys.append(ys[0])
                    return {'type': 'polyline', 'x': xs, 'y': ys}
        
        elif entity_type == 'POLYLINE':
            points = list(entity.points())
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                if entity.is_closed:
                    xs.append(xs[0])
                    ys.append(ys[0])
                return {'type': 'polyline', 'x': xs, 'y': ys}
        
        elif entity_type == 'SPLINE':
            points = list(entity.flattening(0.01))
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return {'type': 'spline', 'x': xs, 'y': ys}
        
        elif entity_type == 'ELLIPSE':
            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            ratio = entity.dxf.ratio
            
            a = math.sqrt(major_axis.x**2 + major_axis.y**2)
            b = a * ratio
            angle = math.atan2(major_axis.y, major_axis.x)
            
            t = [i * 2 * math.pi / 100 for i in range(101)]
            x = [center.x + a * math.cos(ti) * math.cos(angle) - b * math.sin(ti) * math.sin(angle) for ti in t]
            y = [center.y + a * math.cos(ti) * math.sin(angle) + b * math.sin(ti) * math.cos(angle) for ti in t]
            return {'type': 'ellipse', 'x': x, 'y': y}
    
    except:
        pass
    
    return None

def visualize_dxf_interactive(doc, objects_data):
    """Создает ИНТЕРАКТИВНУЮ визуализацию с Plotly."""
    try:
        fig = go.Figure()
        
        # Вычисляем размеры для смещения
        all_x = [obj['center'][0] for obj in objects_data if obj['center'][0] != 0]
        all_y = [obj['center'][1] for obj in objects_data if obj['center'][1] != 0]
        
        if all_x and all_y:
            drawing_size = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
            offset_distance = drawing_size * 0.015
            marker_size = max(drawing_size * 0.006, 12)
        else:
            offset_distance = 10
            marker_size = 15
        
        # Рисуем все объекты ЧЕРНЫМ цветом
        msp = doc.modelspace()
        for entity in msp:
            geom = get_entity_geometry(entity)
            if geom:
                fig.add_trace(go.Scatter(
                    x=geom['x'],
                    y=geom['y'],
                    mode='lines',
                    line=dict(color='black', width=2),
                    showlegend=False,
                    hoverinfo='skip'
                ))
        
        # Добавляем ИНТЕРАКТИВНЫЕ маркеры
        marker_x = []
        marker_y = []
        marker_text = []
        marker_hover = []
        
        for obj in objects_data:
            num = obj['num']
            
            # Находим соответствующий entity
            entity = None
            for ent in msp:
                if ent.dxftype() in calculators:
                    try:
                        if ent.dxftype() == 'LINE':
                            s, e = ent.dxf.start, ent.dxf.end
                            cx = (s.x + e.x) / 2
                            cy = (s.y + e.y) / 2
                        elif ent.dxftype() in ('CIRCLE', 'ARC', 'ELLIPSE'):
                            cx = ent.dxf.center.x
                            cy = ent.dxf.center.y
                        else:
                            continue
                        
                        if abs(cx - obj['center'][0]) < 0.1 and abs(cy - obj['center'][1]) < 0.1:
                            entity = ent
                            break
                    except:
                        continue
            
            if entity:
                x, y = get_entity_center_with_offset(entity, offset_distance)
            else:
                x, y = obj['center']
            
            if x == 0 and y == 0:
                continue
            
            marker_x.append(x)
            marker_y.append(y)
            marker_text.append(str(num))
            marker_hover.append(
                f"<b>№ {num}</b><br>" +
                f"Тип: {obj['type']}<br>" +
                f"Длина: {obj['length']:.2f} мм<br>" +
                f"Координаты: ({obj['center'][0]:.2f}, {obj['center'][1]:.2f})"
            )
        
        # ✅ ИНТЕРАКТИВНЫЕ МАРКЕРЫ с подсказками при наведении
        fig.add_trace(go.Scatter(
            x=marker_x,
            y=marker_y,
            mode='markers+text',
            marker=dict(
                size=marker_size,
                color='red',
                line=dict(color='white', width=2),
                opacity=0.95
            ),
            text=marker_text,
            textposition='middle center',
            textfont=dict(
                size=10,
                color='white',
                family='Arial Black'
            ),
            hovertemplate='%{hovertext}<extra></extra>',
            hovertext=marker_hover,
            showlegend=False
        ))
        
        # Настройки графика
        fig.update_layout(
            plot_bgcolor='#F0F0F0',
            paper_bgcolor='#E5E5E5',
            xaxis=dict(
                showgrid=False,
                zeroline=False,
                showticklabels=False,
                scaleanchor="y",
                scaleratio=1
            ),
            yaxis=dict(
                showgrid=False,
                zeroline=False,
                showticklabels=False
            ),
            margin=dict(l=20, r=20, t=40, b=20),
            height=700,
            title=dict(
                text="🎨 Интерактивный чертеж (наведите на номер для подробностей)",
                x=0.5,
                xanchor='center',
                font=dict(size=14)
            ),
            hovermode='closest'
        )
        
        return fig
        
    except Exception as e:
        st.error(f"Ошибка визуализации: {e}")
        return None

# ==================== STREAMLIT ИНТЕРФЕЙС ====================

st.set_page_config(
    page_title="Анализатор Чертежей CAD Pro",
    page_icon="✂️",
    layout="wide"
)

st.title("✂️ Анализатор Чертежей CAD Pro")
st.markdown("""
**Профессиональный расчет длины реза для станков ЧПУ и лазерной резки**  
Загрузите DXF-чертеж и получите точный анализ с **интерактивной** визуализацией.
""")

with st.expander("ℹ️ Поддерживаемые типы геометрии"):
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        **Базовые примитивы:**
        - LINE (отрезок)
        - CIRCLE (окружность)
        - ARC (дуга)
        - ELLIPSE (эллипс)
        """)
    with col2:
        st.markdown("""
        **Сложные контуры:**
        - LWPOLYLINE (легкая полилиния)
        - POLYLINE (полилиния)
        - SPLINE (сплайн)
        """)
    with col3:
        st.markdown("""
        **Дополнительно:**
        - POINT (точки)
        - INSERT (блоки)
        - TEXT (текст)
        """)

st.markdown("---")

uploaded_file = st.file_uploader(
    "📂 Загрузите чертеж в формате DXF",
    type=["dxf"],
    help="Выберите файл DXF для расчета"
)

if uploaded_file is not None:
    with st.spinner('⏳ Обработка чертежа...'):
        try:
            temp_path = f"temp_{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            doc = ezdxf.readfile(temp_path)
            msp = doc.modelspace()
            
            objects_data = []
            stats = {}
            total_length = 0.0
            num = 0
            skipped_types = set()
            
            for entity in msp:
                entity_type = entity.dxftype()
                
                if entity_type not in calculators:
                    skipped_types.add(entity_type)
                    continue
                
                try:
                    length = calculators[entity_type](entity)
                    
                    if length > 0.0001:
                        num += 1
                        center_x, center_y = 0, 0
                        
                        if entity_type == 'LINE':
                            s, e = entity.dxf.start, entity.dxf.end
                            center_x = (s.x + e.x) / 2
                            center_y = (s.y + e.y) / 2
                        elif entity_type in ('CIRCLE', 'ARC', 'ELLIPSE'):
                            center = entity.dxf.center
                            center_x, center_y = center.x, center.y
                        elif entity_type == 'POINT':
                            loc = entity.dxf.location
                            center_x, center_y = loc.x, loc.y
                        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
                            if entity_type == 'LWPOLYLINE':
                                with entity.points('xy') as pts:
                                    points = list(pts)
                            else:
                                points = [(p[0], p[1]) for p in entity.points()]
                            if points:
                                xs = [p[0] for p in points]
                                ys = [p[1] for p in points]
                                center_x = (min(xs) + max(xs)) / 2
                                center_y = (min(ys) + max(ys)) / 2
                        elif entity_type == 'SPLINE':
                            points = list(entity.flattening(0.1))
                            if points:
                                xs = [p[0] for p in points]
                                ys = [p[1] for p in points]
                                center_x = (min(xs) + max(xs)) / 2
                                center_y = (min(ys) + max(ys)) / 2
                        
                        objects_data.append({
                            'num': num,
                            'type': entity_type,
                            'length': length,
                            'center': (center_x, center_y)
                        })
                        
                        if entity_type not in stats:
                            stats[entity_type] = {'count': 0, 'length': 0.0, 'items': []}
                        
                        stats[entity_type]['count'] += 1
                        stats[entity_type]['length'] += length
                        stats[entity_type]['items'].append({'num': num, 'length': length})
                        
                        total_length += length
                except:
                    pass
            
            os.remove(temp_path)
            
            if not objects_data:
                st.warning("⚠️ В чертеже не найдено объектов для расчета.")
                if skipped_types:
                    st.info(f"Необрабатываемые типы: {', '.join(sorted(skipped_types))}")
            else:
                st.success(f"✅ Успешно обработано: **{len(objects_data)}** объектов")
                
                st.markdown("### 📏 Итоговая длина реза:")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Миллиметры", f"{total_length:.2f}")
                with col2:
                    st.metric("Сантиметры", f"{total_length/10:.2f}")
                with col3:
                    st.metric("Метры", f"{total_length/1000:.4f}")
                with col4:
                    st.metric("Объектов", f"{len(objects_data)}")
                
                st.markdown("---")
                
                col_left, col_right = st.columns([1, 1.5])
                
                with col_left:
                    st.markdown("### 📊 Сводная спецификация")
                    
                    summary_rows = []
                    for entity_type in sorted(stats.keys()):
                        count = stats[entity_type]['count']
                        length = stats[entity_type]['length']
                        avg = length / count if count > 0 else 0
                        summary_rows.append({
                            'Тип': entity_type,
                            'Кол-во': count,
                            'Длина (мм)': round(length, 2),
                            'Средняя': round(avg, 2)
                        })
                    
                    df_summary = pd.DataFrame(summary_rows)
                    st.dataframe(df_summary, use_container_width=True, hide_index=True)
                    
                    if skipped_types:
                        st.caption(f"⚠️ Пропущено: {', '.join(sorted(skipped_types))}")
                    
                    st.markdown("### 🔄 Повторяющиеся элементы")
                    length_groups = {}
                    for obj in objects_data:
                        key = round(obj['length'], 1)
                        if key not in length_groups:
                            length_groups[key] = {'type': obj['type'], 'nums': [], 'length': obj['length']}
                        length_groups[key]['nums'].append(obj['num'])
                    
                    group_rows = []
                    for key in sorted(length_groups.keys(), reverse=True):
                        group = length_groups[key]
                        count = len(group['nums'])
                        if count > 1:
                            group_rows.append({
                                'Тип': group['type'],
                                'Размер': f"{group['length']:.2f} мм",
                                'Кол-во': count,
                                'Итого': f"{group['length']*count:.2f} мм"
                            })
                    
                    if group_rows:
                        df_groups = pd.DataFrame(group_rows)
                        st.dataframe(df_groups, use_container_width=True, hide_index=True)
                    else:
                        st.info("Повторяющихся элементов не обнаружено")
                
                with col_right:
                    st.markdown("### 🎨 Интерактивный чертеж")
                    st.caption("🖱️ Наведите на номер для деталей | 🔍 Зум колесиком мыши | ✋ Перемещайте")
                    
                    with st.spinner('Генерация интерактивной визуализации...'):
                        fig = visualize_dxf_interactive(doc, objects_data)
                        
                        if fig:
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.error("❌ Не удалось создать визуализацию")
                
                st.markdown("---")
                st.markdown("### 📋 Детальная спецификация")
                
                detail_rows = []
                for obj in objects_data:
                    detail_rows.append({
                        '№': obj['num'],
                        'Тип': obj['type'],
                        'Длина (мм)': round(obj['length'], 2),
                        'X': round(obj['center'][0], 2),
                        'Y': round(obj['center'][1], 2)
                    })
                
                df_detail = pd.DataFrame(detail_rows)
                
                selected_types = st.multiselect(
                    "🔍 Фильтр по типу геометрии:",
                    options=sorted(stats.keys()),
                    default=sorted(stats.keys())
                )
                
                if selected_types:
                    df_filtered = df_detail[df_detail['Тип'].isin(selected_types)]
                    st.dataframe(df_filtered, use_container_width=True, hide_index=True, height=400)
                    
                    csv = df_filtered.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 Скачать спецификацию (CSV)",
                        data=csv,
                        file_name=f"specification_{uploaded_file.name}.csv",
                        mime="text/csv"
                    )
                
        except Exception as e:
            st.error(f"❌ Критическая ошибка: {e}")
            import traceback
            with st.expander("🔍 Детали ошибки"):
                st.code(traceback.format_exc())

else:
    st.info("👈 Загрузите DXF-чертеж для начала анализа")
    
    st.markdown("""
    ### 🚀 Руководство пользователя:
    
    1. **Загрузите чертеж** в формате DXF (AutoCAD, LibreCAD, QCAD)
    2. **Получите интерактивный анализ:**
       - ✅ Общая длина реза в мм/см/м
       - ✅ Статистика по типам объектов
       - ✅ Группировка одинаковых деталей
       - ✅ **ИНТЕРАКТИВНАЯ визуализация с подсказками**
    3. **Экспортируйте результаты** в CSV
    
    ### 💡 Особенности интерактивного чертежа:
    
    - 🖱️ **Наведите на номер** - увидите тип, длину и координаты
    - 🔍 **Зум** - колесико мыши для приближения/удаления
    - ✋ **Перемещение** - перетаскивайте чертеж мышью
    - 📐 Точный расчет дуг в полилиниях (bulge)
    - 📊 Экспорт в CSV
    """)

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; font-size: 12px;'>
    ✂️ CAD Analyzer Pro v13.0 | Интерактивная визуализация Plotly | Поддержка DXF
</div>
""", unsafe_allow_html=True)
