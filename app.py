import subprocess
import sys
import os

# ==================== АВТОУСТАНОВКА ЗАВИСИМОСТЕЙ ====================
def install_dependencies():
    """Устанавливает необходимые библиотеки при первом запуске."""
    required_packages = {
        'ezdxf': 'ezdxf>=1.3.0',
        'matplotlib': 'matplotlib>=3.9.0',
        'pandas': 'pandas>=2.2.0',
        'PIL': 'pillow>=10.3.0'
    }
    
    for module_name, package_name in required_packages.items():
        try:
            if module_name == 'PIL':
                __import__('PIL')
            else:
                __import__(module_name)
        except ImportError:
            print(f"📦 Установка {package_name}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name, "--quiet"])
            print(f"✅ {package_name} установлен")

# Устанавливаем зависимости перед импортом
install_dependencies()

# ==================== ИМПОРТЫ ====================
import math
import warnings
import io
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from PIL import Image
import streamlit as st

# Импорт ezdxf с обработкой ошибок
try:
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    EZDXF_AVAILABLE = True
except ImportError as e:
    EZDXF_AVAILABLE = False
    st.error(f"❌ Не удалось загрузить ezdxf: {str(e)}")
    st.info("🔄 Попробуйте перезагрузить страницу или обратитесь к администратору")
    st.stop()

warnings.filterwarnings('ignore', category=UserWarning)

# ==================== РАСЧЁТ ДЛИНЫ ====================

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

def calc_point(entity):
    return 0.1

def calc_mline_length(entity):
    return 0.0

def calc_helix_length(entity):
    return 0.0

def calc_3dface(entity):
    return 0.0

def calc_solid(entity):
    return 0.0

def calc_hatch_length(entity):
    return 0.0

def calc_region(entity):
    return 0.0

def calc_trace_length(entity):
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
        scale = abs(entity.dxf.xscale)
        total = 0.0
        for block_entity in block:
            etype = block_entity.dxftype()
            if etype in calculators:
                total += calculators[etype](block_entity) * scale
        return total
    except:
        return 0.0

def calc_text_length(entity):
    return 0.0

def calc_mtext_length(entity):
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
            return (center.x, center.y)
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
        elif entity_type == 'INSERT':
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

def draw_entity_manually(ax, entity):
    """Рисует объект вручную черным цветом."""
    entity_type = entity.dxftype()
    
    try:
        if entity_type == 'LINE':
            start = entity.dxf.start
            end = entity.dxf.end
            ax.plot([start.x, end.x], [start.y, end.y], 'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'CIRCLE':
            center = entity.dxf.center
            radius = entity.dxf.radius
            circle = plt.Circle((center.x, center.y), radius, fill=False, 
                               edgecolor='black', linewidth=1.5, zorder=1)
            ax.add_patch(circle)
        
        elif entity_type == 'ARC':
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = entity.dxf.start_angle
            end_angle = entity.dxf.end_angle
            
            theta = []
            if end_angle > start_angle:
                theta = [start_angle + i * (end_angle - start_angle) / 50 for i in range(51)]
            else:
                theta = [start_angle + i * (360 + end_angle - start_angle) / 50 for i in range(51)]
            
            x = [center.x + radius * math.cos(math.radians(t)) for t in theta]
            y = [center.y + radius * math.sin(math.radians(t)) for t in theta]
            ax.plot(x, y, 'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'LWPOLYLINE':
            with entity.points('xy') as points:
                pts = list(points)
                if len(pts) >= 2:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    if entity.closed:
                        xs.append(xs[0])
                        ys.append(ys[0])
                    ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'POLYLINE':
            points = list(entity.points())
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                if entity.is_closed:
                    xs.append(xs[0])
                    ys.append(ys[0])
                ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
        
        elif entity_type == 'SPLINE':
            points = list(entity.flattening(0.01))
            if len(points) >= 2:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                ax.plot(xs, ys, 'k-', linewidth=1.5, zorder=1)
        
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
            ax.plot(x, y, 'k-', linewidth=1.5, zorder=1)
        
    except Exception as e:
        pass

def visualize_dxf_with_numbers(doc, objects_data):
    """Создает изображение с черными линиями на сером фоне."""
    try:
        fig, ax = plt.subplots(figsize=(20, 16), dpi=100)
        
        # Серый фон
        fig.patch.set_facecolor('#E5E5E5')
        ax.set_facecolor('#F0F0F0')
        
        # Рисуем все объекты вручную
        msp = doc.modelspace()
        for entity in msp:
            draw_entity_manually(ax, entity)
        
        # Вычисляем размер для маркеров
        all_x = [obj['center'][0] for obj in objects_data if obj['center'][0] != 0]
        all_y = [obj['center'][1] for obj in objects_data if obj['center'][1] != 0]
        
        if all_x and all_y:
            drawing_size = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
            marker_size = max(drawing_size * 0.015, 5)
            font_size = max(int(drawing_size * 0.004), 8)
        else:
            marker_size = 10
            font_size = 9
        
        # Добавляем красные номера
        for obj in objects_data:
            num = obj['num']
            x, y = obj['center']
            
            if x == 0 and y == 0:
                continue
            
            circle = plt.Circle((x, y), marker_size, 
                               color='#FF0000', alpha=0.95, zorder=100,
                               edgecolor='white', linewidth=2.5)
            ax.add_patch(circle)
            
            ax.annotate(str(num), (x, y), 
                       fontsize=font_size, fontweight='bold',
                       ha='center', va='center',
                       color='white', zorder=101)
        
        ax.set_aspect('equal')
        ax.autoscale()
        ax.margins(0.05)
        ax.axis('off')
        plt.tight_layout(pad=0.3)
        
        # Сохраняем в изображение
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', 
                   facecolor='#E5E5E5', edgecolor='none', pad_inches=0.3)
        buf.seek(0)
        
        img = Image.open(buf)
        
        # Добавляем рамку
        bordered = Image.new('RGB', (img.width + 30, img.height + 30), color='#CCCCCC')
        bordered.paste(img, (15, 15))
        
        plt.close(fig)
        
        return bordered
        
    except Exception as e:
        st.error(f"Ошибка визуализации: {str(e)}")
        plt.close('all')
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
Загрузите DXF-чертеж и получите точный анализ с визуализацией.
""")

with st.expander("ℹ️ Поддерживаемые типы геометрии"):
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Базовые:** LINE, CIRCLE, ARC, ELLIPSE")
    with col2:
        st.markdown("**Контуры:** LWPOLYLINE, POLYLINE, SPLINE")
    with col3:
        st.markdown("**Специальные:** INSERT (блоки), POINT")

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
            _current_doc = doc
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
                        center = get_entity_center(entity)
                        
                        objects_data.append({
                            'num': num,
                            'type': entity_type,
                            'length': length,
                            'center': center
                        })
                        
                        if entity_type not in stats:
                            stats[entity_type] = {'count': 0, 'length': 0.0, 'items': []}
                        
                        stats[entity_type]['count'] += 1
                        stats[entity_type]['length'] += length
                        stats[entity_type]['items'].append({'num': num, 'length': length})
                        
                        total_length += length
                except:
                    pass
            
            _current_doc = None
            os.remove(temp_path)
            
            if not objects_data:
                st.warning("⚠️ В чертеже не найдено объектов для расчета.")
            else:
                st.success(f"✅ Обработано: **{len(objects_data)}** объектов")
                
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
                
                with col_right:
                    st.markdown("### 🎨 Чертеж с маркировкой")
                    st.caption("⬛ Черные линии | 🔴 Красные номера | Серый фон")
                    
                    with st.spinner('Генерация изображения...'):
                        img = visualize_dxf_with_numbers(doc, objects_data)
                        
                        if img:
                            st.image(img, use_container_width=True)
                        else:
                            st.error("❌ Не удалось создать визуализацию")
                
                st.markdown("---")
                st.markdown("### 📋 Детальная спецификация")
                
                detail_rows = []
                for obj in objects_data:
                    detail_rows.append({
                        '№': obj['num'],
                        'Тип': obj['type'],
                        'Длина (мм)': round(obj['length'], 2)
                    })
                
                df_detail = pd.DataFrame(detail_rows)
                st.dataframe(df_detail, use_container_width=True, hide_index=True, height=400)
                
                csv = df_detail.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 Скачать спецификацию (CSV)",
                    data=csv,
                    file_name=f"spec_{uploaded_file.name}.csv",
                    mime="text/csv"
                )
                
        except Exception as e:
            st.error(f"❌ Ошибка: {str(e)}")
            import traceback
            with st.expander("Детали ошибки"):
                st.code(traceback.format_exc())

else:
    st.info("👈 Загрузите DXF-чертеж для начала анализа")

st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; font-size: 12px;'>
    ✂️ CAD Analyzer Pro v12.2 | Поддержка DXF/AutoCAD
</div>
""", unsafe_allow_html=True)
