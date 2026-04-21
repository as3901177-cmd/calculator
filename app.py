import streamlit as st
import ezdxf
import tempfile
import os
from core.errors import ErrorCollector, DXFObject, ObjectStatus
from core.calculators import calculators
from core.geometry import get_entity_center
from core.piercing import count_piercings_advanced
from utils.dxf_utils import get_layer_info, check_is_closed

st.title("📐 CAD Pro v24.0")
up = st.file_uploader("Загрузите DXF", type="dxf")

if up:
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as tmp:
        tmp.write(up.getbuffer()); t_path = tmp.name
    
    doc = ezdxf.readfile(t_path)
    msp = doc.modelspace()
    collector = ErrorCollector()
    objs = []
    
    for i, entity in enumerate(msp):
        etype = entity.dxftype()
        if etype in calculators:
            length = calculators[etype](entity)
            layer, color = get_layer_info(entity)
            objs.append(DXFObject(
                num=len(objs)+1, real_num=i, entity_type=etype,
                length=length, center=get_entity_center(entity),
                entity=entity, layer=layer, color=color,
                status=ObjectStatus.NORMAL, is_closed=check_is_closed(entity)
            ))
    
    p_count, p_details = count_piercings_advanced(objs, collector)
    st.metric("Итоговая длина (мм)", f"{sum(o.length for o in objs):.2f}")
    st.metric("Кол-во врезок", p_count)
    os.remove(t_path)