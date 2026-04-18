import subprocess
import sys
import os

# ==================== АВТОУСТАНОВКА ПАКЕТОВ ====================
def install_packages():
    required = {
        'ezdxf': 'ezdxf>=1.1.0',
        'pandas': 'pandas',
        'matplotlib': 'matplotlib',
        'streamlit': 'streamlit'
    }
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            print(f"Установка {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

install_packages()

# ==================== ИМПОРТЫ ====================
import streamlit as st
import ezdxf
from ezdxf import units
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Для работы на серверах без экрана
import math
import tempfile

# ==================== ГЕОМЕТРИЧЕСКИЙ ДВИЖОК ====================

def get_entity_length(entity) -> float:
    """Расчет длины объекта с учетом вложенности и кривизны."""
    etype = entity.dxftype()
    try:
        if etype in ('LINE', 'CIRCLE', 'ARC', 'LWPOLYLINE', 'POLYLINE', 'SPLINE', 'ELLIPSE'):
            # flattening(0.1) универсально превращает кривые в отрезки для замера длины
            path = entity.flattening(distance=0.1)
            return sum(p1.distance(p2) for p1, p2 in zip(path, path[1:]))
            
        elif etype == 'INSERT':
            # Рекурсивный обход блоков (важно для сложных чертежей)
            return sum(get_entity_length(e) for e in entity.virtual_entities() 
                       if e.dxftype() in SUPPORTED_TYPES)
    except Exception:
        return 0.0
    return 0.0

SUPPORTED_TYPES = {'LINE', 'CIRCLE', 'ARC', 'LWPOLYLINE', 'POLYLINE', 'SPLINE', 'ELLIPSE', 'INSERT'}

# ==================== ОБРАБОТКА ДАННЫХ ====================

@st.cache_data(show_spinner=False)
def process_dxf(file_bytes):
    """Парсинг и расчеты (кэшируется для скорости)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.dxf') as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        doc = ezdxf.readfile(tmp_path)
        msp = doc.modelspace()
        
        # Единицы измерения чертежа
        u_code = doc.header.get('$INSUNITS', 0)
        unit_name = units.decode(u_code)
        
        results = []
        for i, entity in enumerate(msp):
            if entity.dxftype() not in SUPPORTED_TYPES:
                continue
                
            length = get_entity_length(entity)
            if length > 0.001:
                # Центр объекта для маркера
                try:
                    bbox = ezdxf.bbox.extents([entity])
                    cx, cy = bbox.center.x, bbox.center.y
                except:
                    cx, cy = 0, 0

                results.append({
                    'id': i + 1,
                    'type': entity.dxftype(),
                    'length': length,
                    'cx': cx, 'cy': cy
                })
        
        return results, unit_name, tmp_path
    except Exception as e:
        return None, str(e), None

# ==================== ВИЗУАЛИЗАЦИЯ ====================

def draw_cad(dxf_path, objects_data, show_markers, font_scale):
    """Профессиональная отрисовка DXF через Matplotlib Backend."""
    doc = ezdxf.readfile(dxf_path)
    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_axes([0, 0, 1, 1])
    
    # Отрисовка геометрии библиотекой ezdxf
    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(doc.modelspace(), finalize=True)
    
    # Наложение маркеров
    if show_markers and objects_data:
        for obj in objects_data:
            ax.text(obj['cx'], obj['cy'], str(obj['id']),
                    color='white', fontsize=7 * font_scale,
                    fontweight='bold', ha='center', va='center',
                    bbox=dict(facecolor='red', alpha=0.8, edgecolor='none', boxstyle='circle,pad=0.2'))
    
    ax.set_aspect('equal')
    ax.axis('off')
    return fig

# ==================== ИНТЕРФЕЙС STREAMLIT ====================

def main():
    st.title("📐 CAD Analyzer Pro")
    st.markdown("### Универсальный расчет длины реза (DXF)")

    uploaded_file = st.file_uploader("Загрузите чертеж .dxf", type=['dxf'])

    if uploaded_file:
        file_bytes = uploaded_file.read()
        
        with st.spinner("Анализируем геометрию..."):
            data, unit_info, temp_path = process_dxf(file_bytes)
        
        if data is None:
            st.error(f"Ошибка: {unit_info}")
            return

        # Метрики
        total_len = sum(d['length'] for d in data)
        c1, c2, c3 = st.columns(3)
        c1.metric("Общая длина", f"{total_len:.2f}")
        c2.metric("Кол-во элементов", len(data))
        c3.metric("Единицы", unit_info)

        if unit_info not in ["Millimeters", "Unitless"]:
            st.warning(f"⚠️ Чертеж в '{unit_info}'. Результат может требовать конвертации.")

        # Вкладки
        tab_draw, tab_data = st.tabs(["🎨 Визуализация", "📊 Данные и Экспорт"])

        with tab_draw:
            col_ui, col_plot = st.columns([1, 4])
            with col_ui:
                markers = st.checkbox("Показать ID", value=True)
                scale = st.slider("Размер шрифта", 0.5, 3.0, 1.0)
                
            with col_plot:
                fig = draw_cad(temp_path, data, markers, scale)
                st.pyplot(fig)
                plt.close(fig)

        with tab_data:
            df = pd.DataFrame(data)
            
            st.subheader("Сводка по типам линий")
            summary = df.groupby('type').agg({'id':'count', 'length':'sum'}).rename(columns={'id':'Кол-во', 'length':'Суммарная длина'})
            st.table(summary)

            st.subheader("Полная спецификация")
            st.dataframe(df[['id', 'type', 'length']], use_container_width=True)
            
            csv = df[['id', 'type', 'length']].to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Скачать спецификацию (CSV)", csv, "specification.csv", "text/csv")

        # Удаление временного файла
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    else:
        st.info("Ожидание загрузки файла...")
        st.markdown("""
        **Что умеет этот инструмент:**
        - Считать длину **линий, дуг, полилиний, сплайнов и эллипсов**.
        - Заходить внутрь **блоков** (вложенные детали).
        - Автоматически помечать детали номерами на чертеже.
        - Экспортировать данные в Excel/CSV.
        """)

if __name__ == "__main__":
    main()
