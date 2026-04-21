def get_layer_info(entity):
    return getattr(entity.dxf, 'layer', '0'), getattr(entity.dxf, 'color', 256)

def check_is_closed(entity):
    etype = entity.dxftype()
    if etype == 'CIRCLE': return True
    if etype == 'LWPOLYLINE': return entity.close or bool(entity.dxf.flags & 1)
    return False