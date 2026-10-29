"""DXGI adapter enumeration. IDs match ONNX Runtime DirectML device_id."""
import ctypes as C
import os
import uuid
from functools import lru_cache


@lru_cache(maxsize=1)
def adapters():
    if os.name != 'nt':
        return []
    class Luid(C.Structure):
        _fields_ = [('low', C.c_uint32), ('high', C.c_int32)]
    class Desc(C.Structure):
        _fields_ = [('name', C.c_wchar * 128), ('vendor', C.c_uint32),
                    ('device', C.c_uint32), ('subsystem', C.c_uint32), ('revision', C.c_uint32),
                    ('dedicated', C.c_size_t), ('system', C.c_size_t), ('shared', C.c_size_t),
                    ('luid', Luid), ('flags', C.c_uint32)]
    def method(pointer, index, result, *args):
        address = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents[index]
        return C.WINFUNCTYPE(result, C.c_void_p, *args)(address)
    def release(pointer):
        if pointer:
            method(pointer, 2, C.c_ulong)(pointer)
    factory = C.c_void_p()
    found = []
    try:
        dxgi = C.WinDLL('dxgi.dll')
        d3d = C.WinDLL('d3d12.dll')
        create = dxgi.CreateDXGIFactory1
        create.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
        create.restype = C.c_long
        iid = C.create_string_buffer(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
        if create(iid, C.byref(factory)) < 0:
            return []
        create_device = d3d.D3D12CreateDevice
        create_device.argtypes = [C.c_void_p, C.c_uint, C.c_void_p, C.c_void_p]
        create_device.restype = C.c_long
        device_iid = C.create_string_buffer(uuid.UUID('189819f1-1db6-4b57-be54-1821339b85f7').bytes_le)
        enum = method(factory, 12, C.c_long, C.c_uint, C.POINTER(C.c_void_p))
        for index in range(32):
            adapter = C.c_void_p()
            if enum(factory, index, C.byref(adapter)) < 0:
                break
            try:
                desc = Desc()
                if method(adapter, 10, C.c_long, C.POINTER(Desc))(adapter, C.byref(desc)) < 0:
                    continue
                if desc.flags & 2:  # Microsoft software adapter is not a GPU.
                    continue
                supported = create_device(adapter, 0xb000, device_iid, None) >= 0
                found.append({'id': index, 'name': desc.name, 'vendor_id': desc.vendor,
                              'dedicated_bytes': desc.dedicated, 'shared_bytes': desc.shared,
                              'directml_capable': supported})
            finally:
                release(adapter)
    except (OSError, AttributeError):
        return []
    finally:
        release(factory)
    return found


def directml_adapters():
    return [a for a in adapters() if a['directml_capable'] and a['vendor_id'] in (0x10de, 0x8086, 0x1002)]


def directml_status():
    try:
        import onnxruntime as ort
        available = 'DmlExecutionProvider' in ort.get_available_providers()
        return {'version': ort.__version__, 'available': available,
                'adapters': directml_adapters() if available else []}
    except (ImportError, OSError) as exc:
        return {'version': None, 'available': False, 'adapters': [], 'error': str(exc)}


def select_directml(requested=-1):
    choices = directml_status()['adapters']
    if requested >= 0:
        return next((a for a in choices if a['id'] == requested), None)
    return max(choices, key=lambda a: a['dedicated_bytes'], default=None)
