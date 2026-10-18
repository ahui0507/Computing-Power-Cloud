// Read-only hardware diagnosis: reused allocations, pinned staging, peer copies.
#include <cuda_runtime.h>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

static void check(cudaError_t result, const char* operation) {
  if (result != cudaSuccess) {
    std::fprintf(stderr, "%s: %s\n", operation, cudaGetErrorString(result));
    std::exit(3);
  }
}

int main() {
  int count=0;
  check(cudaGetDeviceCount(&count), "device count");
  if (count != 2) return 4;
  constexpr size_t max_words=2*1024*1024;
  constexpr size_t max_bytes=max_words*sizeof(uint32_t);
  uint32_t *input=nullptr, *output=nullptr, *staging=nullptr;
  check(cudaMallocHost(&input,max_bytes),"pinned input");
  check(cudaMallocHost(&output,max_bytes),"pinned output");
  check(cudaMallocHost(&staging,max_bytes),"pinned staging");
  std::vector<uint32_t*> sources(count), targets(count);
  for (int device=0;device<count;++device) {
    check(cudaSetDevice(device),"select GPU");
    char bus[32]={};
    check(cudaDeviceGetPCIBusId(bus,sizeof(bus),device),"PCI address");
    std::printf("{\"gpu\":%d,\"pci\":\"%s\"}\n",device,bus);
    check(cudaMalloc(&sources[device],max_bytes),"persistent source allocation");
    check(cudaMalloc(&targets[device],max_bytes),"persistent target allocation");
  }
  const size_t lengths[]={256,4096,max_bytes};
  int peer_failures=0,host_failures=0;
  for (int src=0;src<count;++src) {
    const int dst=1-src;
    int supported=0;
    check(cudaDeviceCanAccessPeer(&supported,dst,src),"peer capability");
    if (!supported) return 5;
    check(cudaSetDevice(dst),"select peer target");
    check(cudaDeviceEnablePeerAccess(src,0),"enable peer access");
    for (size_t bytes:lengths) {
      for (int iteration=0;iteration<3;++iteration) {
        const size_t words=bytes/sizeof(uint32_t);
        for (size_t i=0;i<words;++i)
          input[i]=uint32_t(i+1)*0x9e3779b9u ^ uint32_t(iteration+src*7+1)*0xa5a5a5a5u;
        check(cudaSetDevice(src),"select source");
        check(cudaMemcpy(sources[src],input,bytes,cudaMemcpyHostToDevice),"refresh reused source");
        for (int peer=0;peer<=1;++peer) {
          check(cudaSetDevice(dst),"select target");
          check(cudaMemset(targets[dst],0xcd,bytes),"reset reused target");
          check(cudaDeviceSynchronize(),"synchronize target reset");
          const auto begin=std::chrono::steady_clock::now();
          if (peer) {
            check(cudaMemcpyPeer(targets[dst],dst,sources[src],src,bytes),"peer copy");
            check(cudaDeviceSynchronize(),"synchronize peer");
          } else {
            check(cudaSetDevice(src),"select staging source");
            check(cudaMemcpy(staging,sources[src],bytes,cudaMemcpyDeviceToHost),"pinned staging read");
            check(cudaSetDevice(dst),"select staging target");
            check(cudaMemcpy(targets[dst],staging,bytes,cudaMemcpyHostToDevice),"pinned staging write");
            check(cudaDeviceSynchronize(),"synchronize staged copy");
          }
          const double elapsed=std::chrono::duration<double,std::micro>(std::chrono::steady_clock::now()-begin).count();
          check(cudaMemcpy(output,targets[dst],bytes,cudaMemcpyDeviceToHost),"read target");
          size_t mismatch=0;
          for (size_t i=0;i<words;++i) mismatch+=input[i]!=output[i];
          if (mismatch) {if (peer) ++peer_failures;else ++host_failures;}
          std::printf("{\"path\":\"%s\",\"src\":%d,\"dst\":%d,\"bytes\":%zu,\"reuse_iteration\":%d,\"mismatched_words\":%zu,\"copy_us\":%.3f}\n",
                      peer?"peer":"pinned_host",src,dst,bytes,iteration,mismatch,elapsed);
          std::fflush(stdout);
        }
      }
    }
  }
  for (int device=0;device<count;++device) {
    check(cudaSetDevice(device),"select cleanup GPU");
    check(cudaFree(sources[device]),"free source");
    check(cudaFree(targets[device]),"free target");
  }
  check(cudaFreeHost(input),"free input");
  check(cudaFreeHost(output),"free output");
  check(cudaFreeHost(staging),"free staging");
  std::printf("{\"peer_failed_cases\":%d,\"host_failed_cases\":%d,\"cases_per_path\":18,\"buffers_allocated_once\":true}\n",peer_failures,host_failures);
  return peer_failures||host_failures?2:0;
}
