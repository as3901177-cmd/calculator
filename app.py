import streamlit as st
import ezdxf
import tempfile
import os
import pandas as pd
from dxf_analyzer.config import MAX_FILE_SIZE_MB, PIERCING_TOLERANCE, get_color_name, get_aci_color
from dxf_analyzer.models import DXFObject, ObjectStatus
from dxf_analyzer.geometry import check_is_closed
from dxf_analyzer.calculators import ErrorCollector, CALCULATORS, count_piercings_advanced
from dxf_analyzer.visualization import get_entity_center, create_visual

st.set_page_config(page_title="CAD Analyzer Pro v24.0", layout="wide")
st.title("📐 Анализатор Чертежей CAD Pro v24.0")

up = st.file_uploader("📂 Загрузите DXF", type="dxf")

if up:
    if up.size / 1024**2 > MAX_FILE_SIZE_MB: st.error("Файл слишком большой"); st.stop()
    
    collector = ErrorCollector()
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
        tmp.write(up.getbuffer())
        path = tmp.name

    try:
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        objs, total_len = [], 0.0
        stats, color_stats = {}, {}

        for i, ent in enumerate(msp, 1):
            etype = ent.dxftype()
            if etype not in CALCULATORS: continue
            
            try:
                length = CALCULATORS[etype](ent)
                status = ObjectStatus.NORMAL
                desc = ""
            except Exception as e:
                length, status, desc = 0.0, ObjectStatus.ERROR, str(e)
                collector.add_error(etype, i, desc)

            obj = DXFObject(
                num=len(objs)+1, real_num=i, entity_type=etype, length=length,
                center=get_entity_center(ent), entity=ent, status=status,
                layer=getattr(ent.dxf, 'layer', '0'), color=getattr(ent.dxf, 'color', 256),
                is_closed=check_is_closed(ent)
            )
            objs.append(obj)
            if status != ObjectStatus.ERROR: total_len += length

            # Статистика типов
            if etype not in stats: stats[etype] = {'count': 0, 'len': 0.0}
            stats[etype]['count'] += 1; stats[etype]['len'] += length

            # Статистика цветов
            c = obj.color
            if c not in color_stats: color_stats[c] = {'count': 0, 'len': 0.0, 'name': get_color_name(c), 'hex': get_aci_color(c)}
            color_stats[c]['count'] += 1; color_stats[c]['len'] += length

        p_count, p_details = count_piercings_advanced(objs, collector)

        # Вывод результатов
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Общая длина (мм)", f"{total_len:.2f}")
        col2.metric("Объектов", len(objs))
        col3.metric("Врезок", p_count)
        col4.metric("Допуск", f"{PIERCING_TOLERANCE} мм")

        c_l, c_r = st.columns([1, 1.5])
        with c_l:
            st.subheader("Спецификация")
            st.dataframe(pd.DataFrame([{'Тип': k, 'Кол-во': v['count'], 'Длина': round(v['len'], 2)} for k, v in stats.items()]))
            
            st.subheader("По цветам")
            html = "".join([f"<div style='color:{v['hex']}'>● {v['name']}: {v['count']} шт. ({v['len']:.1f} мм)</div>" for v in color_stats.values()])
            st.markdown(html, unsafe_allow_html=True)

        with c_r:
            mode = st.radio("Режим:", ["Исходные цвета", "Индикация ошибок", "Визуализация цепей"], horizontal=True)
            st.pyplot(create_visual(doc, objs, mode=mode))
            
        if collector.has_errors:
            with st.expander("Ошибки"): st.dataframe(pd.DataFrame([i.to_dict() for i in collector.issues]))

    finally: os.remove(path)
