import sys
import os
import math
import warnings
import io
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Устанавливаем backend ДО импорта pyplot
from PIL import Image

# Импорт Streamlit
import streamlit as st

# Импорты для работы с DXF
try:
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
except ImportError:
    st.error("❌ Библиотека ezdxf не найдена. Убедитесь, что все зависимости установлены.")
    st.stop()

warnings.filterwarnings('ignore', category=UserWarning)

# ==================== РАСЧЁТ ДЛИНЫ — БАЗОВЫЕ ====================

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
    """LWPOLYLINE: лёгкая полилиния с bulge (дугами)."""
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
    """POLYLINE: старая полилиния."""
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
    """SPLINE: B-сплайн."""
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

# ==================== РАСЧЁТ ДЛИНЫ — ДОПОЛНИТЕЛЬНЫЕ ====================

def calc_point(entity):
    return 0.1

def calc_mline_length(entity):
    try:
        vertices = entity.vertices
        if len(vertices) < 2:
            return 0.0
        length = 0.0
        for i in range(len(vertices) - 1):
            v1 = vertices[i]
            v2 = vertices[i + 1]
            length += math.hypot(v2.x - v1.x, v2.y - v1.y)
        num_lines = len(entity.style.elements) if hasattr(entity, 'style') else 1
        return length * max(num_lines, 1)
    except:
        return 0.0

def calc_helix_length(entity):
    return 0.0

def calc_3dface(entity):
    try:
        p0 = entity.dxf.vtx0
        p1 = entity.dxf.vtx1
        p2 = entity.dxf.vtx2
        p3 = entity.dxf.vtx3
        d01 = math.hypot(p1.x - p0.x, p1.y - p0.y)
        d12 = math.hypot(p2.x - p1.x, p2.y - p1.y)
        d23 = math.hypot(p3.x - p2.x, p3.y - p2.y)
        d30 = math.hypot(p0.x - p3.x, p0.y - p3.y)
        if abs(p2.x - p3.x) < 0.001 and abs(p2.y - p3.y) < 0.001:
            return d01 + d12 + d30
        return d01 + d12 + d23 + d30
    except:
        return 0.0

def calc_solid(entity):
    try:
        p0 = entity.dxf.vtx0
        p1 = entity.dxf.vtx1
        p2 = entity.dxf.vtx2
        p3 = entity.dxf.vtx3
        d01 = math.hypot(p1.x - p0.x, p1.y - p0.y)
        d13 = math.hypot(p3.x - p1.x, p3.y - p1.y)
        d32 = math.hypot(p2.x - p3.x, p2.y - p3.y)
        d20 = math.hypot(p0.x - p2.x, p0.y - p2.y)
        return d01 + d13 + d32 + d20
    except:
        return 0.0

def calc_hatch_length(entity):
    try:
        total = 0.0
        for path in entity.paths:
            if hasattr(path, 'vertices'):
                vertices = list(path.vertices)
                for i in range(len(vertices) - 1):
                    v1 = vertices[i]
                    v2 = vertices[i + 1]
                    total += math.hypot(v2[0] - v1[0], v2[1] - v1[1])
                if path.is_closed and len(vertices) > 1:
                    total += math.hypot(vertices[0][0] - vertices[-1][0], 
                                       vertices[0][1] - vertices[-1][1])
            elif hasattr(path, 'edges'):
                for edge in path.edges:
                    edge_type = type(edge).__name__
                    if edge_type == 'LineEdge':
                        total += math.hypot(edge.end[0] - edge.start[0], 
                                           edge.end[1] - edge.start[1])
                    elif edge_type == 'ArcEdge':
                        radius = edge.radius
                        start_angle = math.radians(edge.start_angle)
                        end_angle = math.radians(edge.end_angle)
                        angle = end_angle - start_angle
                        if edge.ccw and angle < 0:
                            angle += 2 * math.pi
                        elif not edge.ccw and angle > 0:
                            angle -= 2 * math.pi
                        total += abs(radius * angle)
        return total
    except:
        return 0.0

def calc_region(entity):
    return 0.0

def calc_trace_length(entity):
    try:
        p0 = entity.dxf.vtx0
        p1 = entity.dxf.vtx1
        p2 = entity.dxf.vtx2
        p3 = entity.dxf.vtx3
        mid1 = ((p0.x + p1.x) / 2, (p0.y + p1.y) / 2)
        mid2 = ((p2.x + p3.x) / 2, (p2.y + p3.y) / 2)
        return math.hypot(mid2[0] - mid1[0], mid2[1] - mid1[1])
    except:
        return 0.0

_current_doc = None

def calc_insert_length(entity):
    global _current_doc
    try:
        if _current_doc is None:
            return 0.0
        block_name = entity.dxf.name
        block = _current_doc.blocks.get(block_name)
        if block is None:
            return 0.0
        x_scale = entity.dxf.xscale
        y_scale = entity.dxf.yscale
        scale = (abs(x_scale) + abs(y_scale)) / 2
        total = 0.0
        for block_entity in block:
            etype = block_entity.dxftype()
            if etype in calculators:
                length = calculators[etype](block_entity)
                total += length * scale
        return total
    except:
        return 0.0

def calc_text_length(entity):
    try:
        text = entity.dxf.text
        height = entity.dxf.height
        strokes_per_char = 3
        return len(text) * height * strokes_per_char
    except:
        return 0.0

def calc_mtext_length(entity):
    try:
        text = entity.plain_text()
        height = entity.dxf.char_height
        text_clean = text.replace('\n', '').replace('\r', '')
        strokes_per_char = 3
        return len(text_clean) * height * strokes_per_char
    except:
        return 0.0

# ==================== ЦЕНТР ОБЪЕКТА ====================

def get_entity_center(entity):
    entity_type = entity.dxftype()
    try:
        if entity_type == 'LINE':
            s, en = entity.dxf.start, entity.dxf.end
            return ((s.x + en.x) / 2, (s.y + en.y) / 2)
        elif entity_type == 'CIRCLE':
            return (entity.dxf.center.x, entity.dxf.center.y)
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = math.radians(entity.dxf.start_angle)
            end_angle = math.radians(entity.dxf.end_angle)
            mid_angle = (start_angle + end_angle) / 2
            if end_angle < start_angle:
                mid_angle += math.pi
            return (center.x + radius * 0.5 * math.cos(mid_angle),
                    center.y + radius * 0.5 * math.sin(mid_angle))
        elif entity_type == 'ELLIPSE':
            return (entity.dxf.center.x, entity.dxf.center.y)
        elif entity_type == 'POINT':
            return (entity.dxf.location.x, entity.dxf.location.y)
        elif entity_type in ('LWPOLYLINE', 'POLYLINE'):
            if entity_type == 'LWPOLYLINE':
                with entity.points('xy') as pts:
                    points = list(pts)
            else:
                points = [(p[0], p[1]) for p in entity.points()]
            if points:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        elif entity_type == 'SPLINE':
            points = list(entity.flattening(0.1))
            if points:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        elif entity_type in ('SOLID', '3DFACE', 'TRACE'):
            p0 = entity.dxf.vtx0
            p1 = entity.dxf.vtx1
            p2 = entity.dxf.vtx2
            p3 = entity.dxf.vtx3
            return ((p0.x + p1.x + p2.x + p3.x) / 4,
                    (p0.y + p1.y + p2.y + p3.y) / 4)
        elif entity_type == 'INSERT':
            return (entity.dxf.insert.x, entity.dxf.insert.y)
        elif entity_type in ('TEXT', 'MTEXT'):
            return (entity.dxf.insert.x, entity.dxf.insert.y)
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
    'HELIX': calc_helix_length,
    '3DFACE': calc_3dface,
    'SOLID': calc_solid,
    'HATCH': calc_hatch_length,
    'REGION': calc_region,
    'TRACE': calc_trace_length,
    'INSERT': calc_insert_length,
    'TEXT': calc_text_length,
    'MTEXT': calc_mtext_length,
}

# ==================== ВИЗУАЛИЗАЦИЯ ====================

def visualize_dxf_with_numbers(doc, objects_data):
    """Создает изображение с визуализацией DXF и нумерацией объектов."""
    try:
        # Создаем фигуру
        fig, ax = plt.subplots(figsize=(18, 14), dpi=100)
        
        # Рисуем DXF
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        Frontend(ctx, backend).draw_layout(doc.modelspace(), finalize=True)
        
        # Вычисляем размер чертежа для масштабирования меток
        all_x = [obj['center'][0] for obj in objects_data if obj['center'][0] != 0]
        all_y = [obj['center'][1] for obj in objects_data if obj['center'][1] != 0]
        
        if all_x and all_y:
            drawing_size = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
            marker_size = drawing_size * 0.012
            font_size = max(6, min(10, int(drawing_size * 0.003)))
        else:
            marker_size = 5
            font_size = 8
        
        # Добавляем номера объектов
        for obj in objects_data:
            num = obj['num']
            x, y = obj['center']
            
            if x == 0 and y == 0:
                continue
            
            # Кружок с номером
            circle = plt.Circle((x, y), marker_size, 
                                color='#FF4444', alpha=0.85, zorder=10,
                                edgecolor='white', linewidth=0.5)
            ax.add_patch(circle)
            
            # Номер
            ax.annotate(str(num), (x, y), 
                       fontsize=font_size, fontweight='bold',
                       ha='center', va='center',
                       color='white', zorder=11)
        
        ax.set_aspect('equal')
        ax.autoscale()
        ax.axis('off')
        plt.tight_layout(pad=0.1)
        
        # Конвертируем в изображение
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        buf.seek(0)
        
        # Открываем как PIL Image
        img = Image.open(buf)
        
        # Закрываем фигуру
        plt.close(fig)
        
        return img
        
    except Exception as e:
        st.error(f"❌ Ошибка визуализации: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
        plt.close('all')  # Закрываем все фигуры
        return None

# ==================== STREAMLIT ИНТЕРФЕЙС ====================

st.set_page_config(
    page_title="Анализатор Чертежей CAD Pro",
    page_icon="✂️",
    layout="wide"
)

# Заголовок
st.title("✂️ Анализатор Чертежей CAD Pro")
st.markdown("""
**Профессиональный расчет длины реза для станков ЧПУ и лазерной резки**  
Загрузите DXF-чертеж и получите точный анализ с визуализацией и детальной спецификацией.
""")

# Информация о поддерживаемых типах
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
        - MLINE (мультилиния)
        """)
    with col3:
        st.markdown("""
        **Специальные объекты:**
        - HATCH (штриховка)
        - INSERT (блоки/вставки)
        - TEXT/MTEXT (текст)
        - 3DFACE, SOLID, TRACE
        """)

st.markdown("---")

# Загрузка файла
uploaded_file = st.file_uploader(
    "📂 Загрузите чертеж в формате DXF",
    type=["dxf"],
    help="Выберите файл DXF для автоматического расчета длины реза"
)

if uploaded_file is not None:
    with st.spinner('⏳ Обработка чертежа...'):
        try:
            # Сохраняем временно
            temp_path = f"temp_{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Читаем документ
            doc = ezdxf.readfile(temp_path)
            _current_doc = doc
            msp = doc.modelspace()
            
            # Анализ объектов
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
                        center = get_entity_center(entity)
                        
                        objects_data.append({
                            'num': num,
                            'type': entity_type,
                            'length': length,
                            'center': center
                        })
                        
                        if entity_type not in stats:
                            stats[entity_type] = {
                                'count': 0,
                                'length': 0.0,
                                'items': []
                            }
                        
                        stats[entity_type]['count'] += 1
                        stats[entity_type]['length'] += length
                        stats[entity_type]['items'].append({
                            'num': num,
                            'length': length
                        })
                        
                        total_length += length
                except Exception as err:
                    st.warning(f"⚠️ Пропущен объект {entity_type}: {str(err)}")
            
            _current_doc = None
            os.remove(temp_path)
            
            # ==================== ОТОБРАЖЕНИЕ РЕЗУЛЬТАТОВ ====================
            
            if not objects_data:
                st.warning("⚠️ В чертеже не найдено объектов для расчета.")
                if skipped_types:
                    st.info(f"Необрабатываемые типы: {', '.join(sorted(skipped_types))}")
            else:
                # Основная информация
                st.success(f"✅ Успешно обработано: **{len(objects_data)}** объектов")
                
                # Итоговая длина
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
                
                # Две колонки: Таблицы и Визуализация
                col_left, col_right = st.columns([1, 1.5])
                
                with col_left:
                    st.markdown("### 📊 Сводная спецификация")
                    
                    # Создаем сводную таблицу
                    summary_rows = []
                    for entity_type in sorted(stats.keys()):
                        count = stats[entity_type]['count']
                        length = stats[entity_type]['length']
                        avg = length / count if count > 0 else 0
                        summary_rows.append({
                            'Тип геометрии': entity_type,
                            'Кол-во': count,
                            'Длина (мм)': round(length, 2),
                            'Средняя (мм)': round(avg, 2)
                        })
                    
                    df_summary = pd.DataFrame(summary_rows)
                    st.dataframe(
                        df_summary,
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    if skipped_types:
                        st.caption(f"⚠️ Пропущено: {', '.join(sorted(skipped_types))}")
                    
                    # Группировка одинаковых
                    st.markdown("### 🔄 Повторяющиеся элементы")
                    length_groups = {}
                    for obj in objects_data:
                        key = round(obj['length'], 1)
                        if key not in length_groups:
                            length_groups[key] = {
                                'type': obj['type'],
                                'nums': [],
                                'length': obj['length']
                            }
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
                        st.dataframe(
                            df_groups,
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.info("Повторяющихся элементов не обнаружено")
                
                with col_right:
                    st.markdown("### 🎨 Чертеж с маркировкой")
                    
                    # Создаем визуализацию
                    with st.spinner('Генерация изображения...'):
                        try:
                            img = visualize_dxf_with_numbers(doc, objects_data)
                            
                            if img:
                                st.image(img, use_container_width=True, 
                                        caption="Красные маркеры с номерами соответствуют объектам в таблице ниже")
                            else:
                                st.error("❌ Не удалось создать визуализацию")
                        except Exception as viz_err:
                            st.error(f"❌ Ошибка визуализации: {str(viz_err)}")
                            import traceback
                            with st.expander("Детали ошибки"):
                                st.code(traceback.format_exc())
                
                # Детальный список объектов
                st.markdown("---")
                st.markdown("### 📋 Полная спецификация деталей")
                
                # Создаем полный список
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
                
                # Фильтр по типу
                selected_types = st.multiselect(
                    "🔍 Фильтр по типу геометрии:",
                    options=sorted(stats.keys()),
                    default=sorted(stats.keys())
                )
                
                if selected_types:
                    df_filtered = df_detail[df_detail['Тип'].isin(selected_types)]
                    st.dataframe(
                        df_filtered,
                        use_container_width=True,
                        hide_index=True,
                        height=400
                    )
                    
                    # Скачать CSV
                    csv = df_filtered.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 Экспорт спецификации (CSV)",
                        data=csv,
                        file_name=f"specification_{uploaded_file.name}.csv",
                        mime="text/csv"
                    )
                
        except Exception as e:
            st.error(f"❌ Критическая ошибка при обработке: {str(e)}")
            import traceback
            with st.expander("Показать технические детали"):
                st.code(traceback.format_exc())

else:
    # Инструкция при отсутствии файла
    st.info("👈 Загрузите DXF-чертеж для начала анализа")
    
    st.markdown("""
    ### 🚀 Руководство пользователя:
    
    1. **Загрузите чертеж** в формате DXF (AutoCAD, LibreCAD, QCAD и др.)
    2. **Получите детальный анализ:**
       - ✅ Общая длина реза в разных единицах измерения
       - ✅ Разбивка по типам геометрических объектов
       - ✅ Группировка одинаковых деталей
       - ✅ Интерактивная таблица с фильтрацией
       - ✅ Визуализация чертежа с нумерацией элементов
    3. **Экспортируйте результаты** в формате CSV для дальнейшей обработки
    
    ### 💡 Ключевые возможности:
    
    - ⚙️ Поддержка 18+ типов CAD-объектов
    - 📐 Точный расчет дуговых сегментов (bulge в полилиниях)
    - 🔲 Автоматическая обработка вложенных блоков с учетом масштаба
    - 🎨 Наглядная визуализация с цветной маркировкой
    - 📊 Экспорт детальной спецификации в CSV
    - ⚡ Быстрая обработка больших чертежей
    
    ### 🎯 Применение:
    - Лазерная резка металла
    - ЧПУ фрезеровка
    - Плазменная резка
    - Гидроабразивная резка
    - Расчет расхода материала
    """)

# Футер
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; font-size: 12px;'>
    ✂️ CAD Analyzer Pro v12.0 | Точные расчеты для производства | Поддержка DXF/AutoCAD
</div>
""", unsafe_allow_html=True)
