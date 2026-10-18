// Verify every transferred word, including pairs that advertise peer support.
#include <cuda_runtime.h>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

static void check(cudaError_t error, const char* operation) {
  if (error != cudaSuccess) {
    std::fprintf(stderr, "%s: %s\n", operation, cudaGetErrorString(error));
    std::exit(3);
  }
}

int main(int argc, char** argv) {
  bool all = argc > 1 && std::string(argv[1]) == "--all";
  int count = 0;
  check(cudaGetDeviceCount(&count), "device count");
  if (count < 2) return 4;
  const size_t words = 2 * 1024 * 1024;
  const size_t bytes = words * sizeof(uint32_t);
  std::vector<uint32_t*> sources(count), targets(count);
  std::vector<std::vector<uint32_t>> expected(count, std::vector<uint32_t>(words));
  for (int device = 0; device < count; ++device) {
    check(cudaSetDevice(device), "select device");
    char bus[32] = {};
    check(cudaDeviceGetPCIBusId(bus, sizeof(bus), device), "PCI address");
    std::printf("GPU %d PCI %s\n", device, bus);
    for (size_t index = 0; index < words; ++index)
      expected[device][index] = (0x9e3779b9u * uint32_t(index + 1)) ^ (uint32_t(device + 1) * 0xa5a5a5a5u);
    check(cudaMalloc(&sources[device], bytes), "allocate source");
    check(cudaMalloc(&targets[device], bytes), "allocate target");
    check(cudaMemcpy(sources[device], expected[device].data(), bytes, cudaMemcpyHostToDevice), "initialize source");
  }
  std::vector<uint32_t> result(words);
  int pairs = 0;
  for (int src = 0; src < count; ++src) {
    for (int dst = 0; dst < count; ++dst) {
      if (src == dst || (!all && (src > 1 || dst > 1))) continue;
      int possible = 0;
      check(cudaDeviceCanAccessPeer(&possible, dst, src), "peer capability");
      if (!possible) { std::fprintf(stderr, "Unsupported peer %d -> %d\n", src, dst); return 5; }
      check(cudaSetDevice(dst), "select target");
      cudaError_t enabled = cudaDeviceEnablePeerAccess(src, 0);
      if (enabled == cudaErrorPeerAccessAlreadyEnabled) cudaGetLastError();
      else check(enabled, "enable peer access");
      check(cudaMemset(targets[dst], 0xcd, bytes), "clear target");
      check(cudaMemcpyPeer(targets[dst], dst, sources[src], src, bytes), "peer copy");
      check(cudaDeviceSynchronize(), "synchronize target");
      check(cudaMemcpy(result.data(), targets[dst], bytes, cudaMemcpyDeviceToHost), "read target");
      size_t mismatch = 0;
      for (size_t index = 0; index < words; ++index) mismatch += result[index] != expected[src][index];
      std::printf("{\"src\":%d,\"dst\":%d,\"bytes\":%zu,\"mismatched_words\":%zu,\"first_expected\":%u,\"first_actual\":%u}\n", src, dst, bytes, mismatch, expected[src][0], result[0]);
      std::fflush(stdout);
      if (mismatch) return 2;
      ++pairs;
    }
  }
  for (int device = 0; device < count; ++device) {
    check(cudaSetDevice(device), "select cleanup device");
    check(cudaFree(sources[device]), "free source");
    check(cudaFree(targets[device]), "free target");
  }
  std::printf("{\"all_verified\":true,\"gpu_count\":%d,\"directed_pairs\":%d}\n", count, pairs);
  return 0;
}
