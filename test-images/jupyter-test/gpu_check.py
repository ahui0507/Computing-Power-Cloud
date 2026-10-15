"""仅依赖 Python 与注入的 CUDA 驱动，执行一次真实 GPU 加法。"""
import ctypes as c
import json


def run(device_index=0):
    cuda = c.CDLL("libcuda.so.1")

    def bind(name, arguments):
        function = getattr(cuda, name)
        function.argtypes = arguments
        function.restype = c.c_int
        return function

    def call(function, *args):
        result = function(*args)
        if result != 0:
            raise RuntimeError(f"CUDA operation failed with code {result}")

    init = bind("cuInit", [c.c_uint])
    count = bind("cuDeviceGetCount", [c.POINTER(c.c_int)])
    device_get = bind("cuDeviceGet", [c.POINTER(c.c_int), c.c_int])
    attribute = bind("cuDeviceGetAttribute", [c.POINTER(c.c_int), c.c_int, c.c_int])
    create = bind("cuCtxCreate_v2", [c.POINTER(c.c_void_p), c.c_uint, c.c_int])
    destroy = bind("cuCtxDestroy_v2", [c.c_void_p])
    allocate = bind("cuMemAlloc_v2", [c.POINTER(c.c_uint64), c.c_size_t])
    free = bind("cuMemFree_v2", [c.c_uint64])
    to_device = bind("cuMemcpyHtoD_v2", [c.c_uint64, c.c_void_p, c.c_size_t])
    to_host = bind("cuMemcpyDtoH_v2", [c.c_void_p, c.c_uint64, c.c_size_t])
    load = bind("cuModuleLoadData", [c.POINTER(c.c_void_p), c.c_void_p])
    unload = bind("cuModuleUnload", [c.c_void_p])
    function_get = bind(
        "cuModuleGetFunction", [c.POINTER(c.c_void_p), c.c_void_p, c.c_char_p]
    )
    launch = bind(
        "cuLaunchKernel",
        [c.c_void_p]
        + [c.c_uint] * 7
        + [
            c.c_void_p,
            c.POINTER(c.c_void_p),
            c.POINTER(c.c_void_p),
        ],
    )
    synchronize = bind("cuCtxSynchronize", [])
    call(init, 0)
    visible = c.c_int()
    call(count, c.byref(visible))
    if visible.value < 1:
        raise RuntimeError("No CUDA GPU is visible inside the container")
    if device_index < 0 or device_index >= visible.value:
        raise ValueError("CUDA device index is outside the visible GPU range")
    device, major = c.c_int(), c.c_int()
    call(device_get, c.byref(device), device_index)
    call(attribute, c.byref(major), 75, device)
    target, version = (
        (80, "7.0")
        if major.value >= 8
        else (70, "6.0")
        if major.value >= 7
        else (60, "6.0")
        if major.value >= 6
        else (37, "6.0")
    )
    ptx = f""".version {version}
.target sm_{target}
.address_size 64
.visible .entry add_one(.param .u64 pointer) {{
 .reg .u64 %rd<2>;
 .reg .u32 %r<3>;
 ld.param.u64 %rd1, [pointer];
 ld.global.u32 %r1, [%rd1];
 add.u32 %r2, %r1, 1;
 st.global.u32 [%rd1], %r2;
 ret;
}}
"""
    context, module, function = c.c_void_p(), c.c_void_p(), c.c_void_p()
    memory = c.c_uint64()
    call(create, c.byref(context), 0, device)
    try:
        call(allocate, c.byref(memory), 4)
        value = c.c_uint32(41)
        call(to_device, memory, c.byref(value), 4)
        program = c.create_string_buffer(ptx.encode("ascii"))
        call(load, c.byref(module), program)
        call(function_get, c.byref(function), module, b"add_one")
        parameters = (c.c_void_p * 1)(c.cast(c.byref(memory), c.c_void_p))
        call(launch, function, 1, 1, 1, 1, 1, 1, 0, None, parameters, None)
        call(synchronize)
        call(to_host, c.byref(value), memory, 4)
        if value.value != 42:
            raise RuntimeError("CUDA kernel returned an incorrect result")
        return {"visible_gpus": visible.value, "computed": value.value}
    finally:
        if module.value:
            unload(module)
        if memory.value:
            free(memory)
        destroy(context)


if __name__ == "__main__":
    print(json.dumps(run()))
