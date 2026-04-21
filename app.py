import streamlit as st
import ezdxf
import tempfile
import os
import pandas as pd
from core.errors import ErrorCollector, DXFObject
from core.geometry import get_entity_center
from core.piercing import count_piercings_advanced
from core.visualization import visualize_dxf_with_status_indicators
from utils.dxf_utils import get_layer_info, check_is_closed, calc_entity_safe
from utils.constants import MAX_FILE_SIZE_MB, PIERCING_TOLERANCE

st.set_page_config(page_title="CAD Pro v24.0", layout="wide")
st.title("📐 Анализатор DXF Pro v24.0")

uploaded_file = st.file_uploader("Загрузите DXF", type=["dxf"])

if uploaded_file:
    collector = ErrorCollector()
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
        tmp.write(uploaded_file.getbuffer())
        t_path = tmp.name

    try:
        doc = ezdxf.readfile(t_path)
        msp = doc.modelspace()
        objects_data = []
        total_len = 0.0
        
        real_idx = 0
        calc_idx = 0
        
        for entity in msp:
            real_idx += 1
            etype = entity.dxftype()
            layer, color = get_layer_info(entity)
            
            length, status, desc = calc_entity_safe(etype, entity, real_idx, collector)
            if status.value == 'skipped': continue
            
            calc_idx += 1
            obj = DXFObject(
                num=calc_idx, real_num=real_idx, entity_type=etype,
                length=length, center=get_entity_center(entity),
                entity=entity, layer=layer, color=color, original_color=color,
                status=status, is_closed=check_is_closed(entity)
            )
            objects_data.append(obj)
            if status.value != 'error': total_len += length

        p_count, p_details = count_piercings_advanced(objects_data, collector)
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Длина (мм)", f"{total_len:.2f}")
        col2.metric("Объектов", len(objects_data))
        col3.metric("Врезок", p_count)

        mode = st.radio("Режим:", ["Стандарт", "Цепи"], horizontal=True)
        fig, _ = visualize_dxf_with_status_indicators(doc, objects_data, collector, show_chains=(mode=="Цепи"))
        st.pyplot(fig)

        if collector.has_issues:
            with st.expander("Лог ошибок"):
                st.dataframe(collector.get_all_as_dataframe())

    finally:
        os.remove(t_path)