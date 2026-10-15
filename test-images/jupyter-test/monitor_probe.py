"""在实例自己的 GPU 中保留 64 MiB，用于核对监控采集，60 秒后自动释放。"""
import ctypes as c
import time


def main():
    cuda = c.CDLL("libcuda.so.1")
    def bind(name, arguments):
        method = getattr(cuda, name)
        method.argtypes = arguments
        method.restype = c.c_int
        return method
    def call(method, *arguments):
        result = method(*arguments)
        if result:
            raise RuntimeError(f"CUDA failed: {result}")
    initialize = bind("cuInit", [c.c_uint])
    device_get = bind("cuDeviceGet", [c.POINTER(c.c_int), c.c_int])
    create = bind("cuCtxCreate_v2", [c.POINTER(c.c_void_p), c.c_uint, c.c_int])
    allocate = bind("cuMemAlloc_v2", [c.POINTER(c.c_uint64), c.c_size_t])
    free = bind("cuMemFree_v2", [c.c_uint64])
    destroy = bind("cuCtxDestroy_v2", [c.c_void_p])
    call(initialize, 0)
    device, context, pointer = c.c_int(), c.c_void_p(), c.c_uint64()
    call(device_get, c.byref(device), 0)
    call(create, c.byref(context), 0, device)
    try:
        call(allocate, c.byref(pointer), 64 * 1024 * 1024)
        print("GPU_MEMORY_ALLOCATED_64_MIB", flush=True)
        time.sleep(60)
    finally:
        if pointer.value:
            free(pointer)
        destroy(context)
    print("GPU_MEMORY_RELEASED", flush=True)


if __name__ == "__main__":
    main()
