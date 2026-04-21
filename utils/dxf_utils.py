from typing import Tuple, Any
from core.errors import ErrorCollector, ObjectStatus
from core.calculators import calculators
import math

def get_layer_info(entity) -> Tuple[str, int]:
    try:
        return entity.dxf.layer, entity.dxf.color
    except: return "0", 256

def check_is_closed(entity) -> bool:
    etype = entity.dxftype()
    if etype == 'CIRCLE': return True
    if etype == 'LWPOLYLINE': return entity.close or bool(entity.dxf.flags & 1)
    if etype == 'POLYLINE': return entity.is_closed
    return False

def validate_length_result(length: Any, etype: str, enum: int, collector: ErrorCollector):
    if length is None or not math.isfinite(length):
        collector.add_error(etype, enum, "Ошибка вычисления длины")
        return 0.0, False
    if length < 0: return abs(length), True
    return length, True

def calc_entity_safe(etype, entity, enum, collector):
    if etype not in calculators:
        collector.add_skipped(etype, enum, "Тип не поддерживается")
        return 0.0, ObjectStatus.SKIPPED, "Not supported"
    try:
        val = calculators[etype](entity)
        length, ok = validate_length_result(val, etype, enum, collector)
        return length, (ObjectStatus.NORMAL if ok else ObjectStatus.ERROR), ""
    except Exception as e:
        collector.add_error(etype, enum, str(e))
        return 0.0, ObjectStatus.ERROR, str(e)