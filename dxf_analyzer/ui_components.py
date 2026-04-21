import streamlit as st
import pandas as pd
from .calculators import ErrorCollector

def show_info_headers():
    with st.expander("ℹ️ Информация о подсчёте врезок"):
        st.markdown("Каждая **связанная цепь объектов** = **1 врезка**. Допуск: 0.1 мм.")
    with st.expander("ℹ️ Информация о цветах"):
        st.markdown("**Красный оверлей**: Ошибка. **Оранжевый**: Предупреждение.")

def show_error_report(collector: ErrorCollector):
    if not collector.has_issues:
        st.success("✅ Ошибок нет")
        return
    st.warning(collector.get_summary())
    with st.expander("🔍 Детальный лог"):
        st.dataframe(collector.get_all_as_dataframe(), use_container_width=True)