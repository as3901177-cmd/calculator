import streamlit as st
import ezdxf
import tempfile
import os
import pandas as pd
from dxf_analyzer.config import MAX_FILE_SIZE_MB, PIERCING_TOLERANCE, get_color_name, get_aci_color
from dxf_analyzer.models import DXFObject, ObjectStatus
from dxf_analyzer.geometry import check_is_closed
from dxf_analyzer.calculators import ErrorCollector, calc_entity_safe, count_piercings_advanced, get_piercing_statistics
from dxf_analyzer.visualization import get_entity_center, visualize_dxf_with_status_indicators
from dxf_analyzer.ui_components import show_info_headers, show_error_report

st.set_page_config(page_title="CAD Analyzer Pro v24.0", layout="wide")
st.title("📐 Анализатор Чертежей CAD Pro v24.0")

uploaded_file = st.file_uploader("📂 Загрузите DXF", type=["dxf"])

if uploaded_file:
    if uploaded_file.size / 1024**2 > MAX_FILE_SIZE_MB:
        st.error("Файл слишком велик"); st.stop()

    collector = ErrorCollector()
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        doc = ezdxf.readfile(tmp_path)
        msp = doc.modelspace()
        objects_data, total_length = [], 0.0
        stats, color_stats = {}, {}

        for i, entity in enumerate(msp, 1):
            etype = entity.dxftype()
            length, status, desc = calc_entity_safe(etype, entity, i, collector)
            if status == ObjectStatus.SKIPPED: continue
            
            obj = DXFObject(
                num=len(objects_data)+1, real_num=i, entity_type=etype, length=length,
                center=get_entity_center(entity), entity=entity, status=status,
                issue_description=desc, is_closed=check_is_closed(entity),
                layer=getattr(entity.dxf, 'layer', '0'), color=getattr(entity.dxf, 'color', 256)
            )
            objects_data.append(obj)
            total_length += length
            
            # Статистика
            if etype not in stats: stats[etype] = {'count': 0, 'length': 0.0}
            stats[etype]['count'] += 1; stats[etype]['length'] += length
            
            c = obj.color
            if c not in color_stats: color_stats[c] = {'count': 0, 'length': 0.0, 'name': get_color_name(c), 'hex': get_aci_color(c)}
            color_stats[c]['count'] += 1; color_stats[c]['length'] += length

        p_count, p_details = count_piercings_advanced(objects_data, collector)
        
        # UI
        show_error_report(collector)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Длина (мм)", f"{total_length:.2f}")
        col2.metric("Объектов", len(objects_data))
        col3.metric("Врезок", p_count)
        col4.metric("Допуск", f"{PIERCING_TOLERANCE} мм")

        c_left, c_right = st.columns([1, 1.5])
        with c_left:
            st.subheader("Спецификация")
            st.dataframe(pd.DataFrame([{'Тип': k, 'Кол-во': v['count'], 'Длина': round(v['length'],2)} for k,v in stats.items()]))
        
        with c_right:
            mode = st.radio("Режим:", ["Исходные цвета", "Индикация ошибок", "Визуализация цепей"], horizontal=True)
            fig, err = visualize_dxf_with_status_indicators(doc, objects_data, collector, mode=mode)
            if fig: st.pyplot(fig)
            else: st.error(err)

    except Exception as e: st.error(f"Ошибка: {e}")
    finally: os.remove(tmp_path)
else:
    show_info_headers()