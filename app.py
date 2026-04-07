import sys
import os
import math
import warnings
import io
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image

# Импорт библиотек для потока данных
import streamlit as st

# Импорты вашего логики
try:
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
except ImportError:
    st.error("Библиотека ezdxf не найдена. Убедитесь, что все зависимости установлены.")
    st.stop()

warnings.filterwarnings('ignore', category=UserWarning)

# --- НАЧАЛО ВАШЕГО КОДА (Расчеты и функции) ---
# Я сохранил всю логику расчетов, но убрал лишние проверки для Web-версии

def calc_line_length(entity):
    start = entity.dxf.start
    end = entity.dxf.end
    return math.hypot(end.x - start.x, end.y - start.y)

def calc_circle_length(entity):
    return 2 * math.pi * entity.dxf.radius

def calc_arc_length(entity):
    radius = entity.dxf.radius
    start_angle = math.radians(entity.dxf.start_angle)
    end_angle = math.radians(entity.dxf.end_angle)
    angle = end_angle - start_angle
    if angle < 0:
        angle += 2 * math.pi
    return radius * angle

def calc_ellipse_length(entity):
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

# Остальные вспомогательные функции расчета
def calc_point(e): 
    return 0.1

def calc_mline_length(e): 
    return 0.0

def calc_helix_length(e): 
    return 0.0

def calc_3dface(e): 
    return 0.0

def calc_solid(e): 
    return 0.0

def calc_hatch_length(e): 
    return 0.0

def calc_region(e): 
    return 0.0

def calc_trace_length(e): 
    return 0.0

# Глобальная переменная для хранения текущего документа
_current_doc = None

def calc_insert_length(e):
    global _current_doc  # ✅ ИСПРАВЛЕНО: объявление в начале функции
    try:
        if _current_doc is None: 
            return 0.0
        bn = e.dxf.name
        blk = _current_doc.blocks.get(bn)
        if not blk: 
            return 0.0
        sc = abs(e.dxf.xscale)
        tot = 0
        for be in blk:
            if be.dxftype() in calculators:
                tot += calculators[be.dxftype()](be) * sc
        return tot
    except: 
        return 0.0

def calc_text_length(e): 
    return 0.0

def calc_mtext_length(e): 
    return 0.0

def get_entity_center(entity):
    entity_type = entity.dxftype()
    try:
        if entity_type == 'LINE':
            s, en = entity.dxf.start, entity.dxf.end
            return ((s.x + en.x) / 2, (s.y + en.y) / 2)
        elif entity_type == 'CIRCLE': 
            return (entity.dxf.center.x, entity.dxf.center.y)
        elif entity_type == 'POINT': 
            return (entity.dxf.location.x, entity.dxf.location.y)
        elif entity_type == 'INSERT': 
            return (entity.dxf.insert.x, entity.dxf.insert.y)
    except: 
        pass
    return (0, 0)

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

def visualize_dxf_with_numbers(doc, objects_data):
    fig, ax = plt.subplots(figsize=(14, 11))
    try:
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        Frontend(ctx, backend).draw_layout(doc.modelspace(), finalize=True)
        
        all_x = [obj['center'][0] for obj in objects_data if obj['center'][0] != 0]
        all_y = [obj['center'][1] for obj in objects_data if obj['center'][1] != 0]
        
        drawing_size = 10
        if all_x and all_y:
            drawing_size = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
        
        marker_size = drawing_size * 0.015
        
        for obj in objects_data:
            num = obj['num']
            x, y = obj['center']
            if x == 0 and y == 0: 
                continue
            
            circle = plt.Circle((x, y), marker_size, color='red', alpha=0.8, zorder=10)
            ax.add_patch(circle)
            ax.annotate(str(num), (x, y), fontsize=7, fontweight='bold', 
                       ha='center', va='center', color='white', zorder=11)
        
        ax.set_aspect('equal')
        ax.autoscale()
        ax.axis('off')
        plt.tight_layout()
        
        # Сохраняем в память
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        img = Image.open(buf)
        plt.close(fig)
        return img
    except Exception as e:
        st.error(f"Ошибка визуализации: {e}")
        return None

# --- КОНЕЦ ВАШЕГО КОДА ---

# --- ИНТЕРФЕЙС САЙТА ---

st.set_page_config(page_title="DXF Calculator Pro", layout="wide")
st.title("📐 Калькулятор Длины Реза (DXF)")
st.markdown("**Загрузите файл**, получите таблицу размеров, общую сумму и схему с нумерацией объектов.")

uploaded_file = st.file_uploader("Выберите файл .dxf", type=["dxf"])

if uploaded_file is not None:
    with st.spinner('⏳ Анализ DXF файла...'):
        try:
            # Временная загрузка в файл, т.к. ezdxf читает путь
            temp_path = f"temp_{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Запуск анализа
            doc = ezdxf.readfile(temp_path)
            _current_doc = doc  # ✅ ИСПРАВЛЕНО: используем напрямую
            msp = doc.modelspace()
            
            objects_data = []
            stats = {}
            total_length = 0.0
            num = 0
            skipped_types = set()
            
            for entity in msp:
                etype = entity.dxftype()
                if etype not in calculators:
                    skipped_types.add(etype)
                    continue
                
                try:
                    length = calculators[etype](entity)
                    if length > 0.0001:
                        num += 1
                        center = get_entity_center(entity)
                        
                        objects_data.append({
                            'num': num, 
                            'type': etype, 
                            'length': length, 
                            'center': center
                        })
                        
                        if etype not in stats:
                            stats[etype] = {'count': 0, 'length': 0.0}
                        
                        stats[etype]['count'] += 1
                        stats[etype]['length'] += length
                        total_length += length
                except:
                    pass
            
            _current_doc = None  # ✅ ИСПРАВЛЕНО: сброс без del
            os.remove(temp_path)
            
            # Сбор результатов
            if not objects_data:
                st.warning("⚠️ Похоже, в файле нет поддерживаемых объектов для расчета.")
            else:
                # 1. Сводная таблица
                rows = []
                for key, val in stats.items():
                    avg = val['length']/val['count'] if val['count'] else 0
                    rows.append({
                        'Тип': key, 
                        'Кол-во': val['count'], 
                        'Длина (мм)': round(val['length'], 2), 
                        'Ср. длина': round(avg, 2)
                    })
                
                df = pd.DataFrame(rows).set_index('Тип')
                
                # 2. Графика
                fig_img = visualize_dxf_with_numbers(doc, objects_data)
                
                # 3. Отрисовка интерфейса
                st.success(f"✅ Успешно обработано: **{len(objects_data)}** объектов")
                st.info(f"📏 **ИТОГОВАЯ ДЛИНА РЕЗА**: {total_length:.2f} мм ({total_length/1000:.3f} м)")
                
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.subheader("Статистика по типам")
                    st.dataframe(df.style.format({
                        "Длина (мм)": "{:.2f}", 
                        "Ср. длина": "{:.2f}"
                    }))
                    if skipped_types:
                        st.caption(f"Пропущено необрабатываемых типов: {', '.join(skipped_types)}")
                
                with col2:
                    st.subheader("Визуализация чертежа")
                    if fig_img:
                        st.image(fig_img, use_container_width=True)
                    else:
                        st.error("Ошибка построения схемы")

        except Exception as e:
            st.error(f"❌ Произошла критическая ошибка: {e}")
            import traceback
            st.code(traceback.format_exc())
else:
    st.info("👈 Жду загрузки файла DXF...")
