"""Native CPU and device-generated OpenCL combinations with full-key lookup."""
import ctypes
import os
import numpy as np
from .hashing import native, pack,ALGORITHMS
from .generated_registry import OPENCL_DEFINES

KERNEL = OPENCL_DEFINES + r'''
ulong step_hash(ulong h, uchar c, ulong prime, uint alg, ulong index) {
    if(alg==ALG_BO4_SCRIPT) {uint v=(uint)h+(uint)c;uint m=v^(v<<10);return (ulong)(m+(m>>6));}
    if(alg==ALG_PRIME32) return (ulong)((uint)h*(uint)prime+(uint)c);
    if(alg==ALG_DJB2XOR) return (ulong)(((uint)h*(uint)prime)^(uint)c);
    if(alg==ALG_KVP) return h+(prime+index)*(ulong)c;
    return (h^(ulong)c)*prime;
}
__kernel void scan(__global const uchar *data, __global const uint *offsets,
 __global const uint *starts, __global const uint *radices, uint slots,
 ulong base, ulong seed, ulong prime, ulong mask, uint alg,
 __global const uchar *secret, uint secret_len, __global const ulong *targets,
 uint target_count, __global uchar *hits) {
    size_t gid = get_global_id(0);
    ulong idx = base + gid;
    uint digits[32];
    for (int s=(int)slots-1;s>=0;--s) {
        digits[s]=(uint)(idx % radices[s]); idx /= radices[s];
    }
    ulong h=seed;
    ulong counter=0;
    for(uint s=0;s<slots;++s) {
        uint v=starts[s]+digits[s];
        for(uint j=offsets[v];j<offsets[v+1];++j) {
            h=step_hash(h,data[j],prime,alg,counter);
            if(alg==ALG_SECURE && counter==0) for(uint k=0;k<secret_len;++k) h=step_hash(h,secret[k],prime,alg,0);
            ++counter;
        }
    }
    if(alg==ALG_SUFFIX) for(uint k=0;k<secret_len;++k) h=step_hash(h,secret[k],prime,alg,0);
    if(alg==ALG_BO4_SCRIPT) {uint v=9*(uint)h;h=(ulong)((uint)0x8001*(v^(v>>11)));}
    if(alg==ALG_T7_SCRIPT) h*=prime;
    if(alg==ALG_KVP) h^=((h^(h>>10))>>10);
    h &= mask;
    uint lo=0,hi=target_count;
    while(lo<hi) {uint m=lo+(hi-lo)/2; if(targets[m]<h)lo=m+1;else hi=m;}
    hits[gid]=(uchar)(lo<target_count && targets[lo]==h);
}
'''

def devices():
    try:
        import pyopencl as cl
        return [{'platform':p.name,'name':d.name,'vendor':d.vendor,
                 'memory':int(d.global_mem_size),'driver':d.driver_version}
                for p in cl.get_platforms() for d in p.get_devices(device_type=cl.device_type.GPU)]
    except Exception as e:
        return [{'error':str(e)}]

class CPU:
    name = 'Rust CPU'
    def __init__(self,plan,profile,targets,threads=0):
        self.profile=profile
        self.threads=threads or max(1,(os.cpu_count() or 2)//2)
        flat=[profile.normalize(v) if v else '' for s in plan.slots for v in s]
        self.data,self.offsets=pack(flat)
        self.radices=np.array([len(s) for s in plan.slots],dtype=np.uint32)
        self.starts=np.array([sum(len(s) for s in plan.slots[:i]) for i in range(len(plan.slots))],dtype=np.uint32)
        self.targets=np.array(sorted(targets),dtype=np.uint64)
        self.secret=np.frombuffer(profile.secret.encode('ascii') or b'\0',dtype=np.uint8)
        native()

    def scan(self,base,count):
        hits=np.zeros(count,dtype=np.uint8)
        def ptr(a,t): return a.ctypes.data_as(ctypes.POINTER(t))
        native().hash_combinations(ptr(self.data,ctypes.c_uint8),ptr(self.offsets,ctypes.c_uint32),
            len(self.offsets)-1,ptr(self.starts,ctypes.c_uint32),ptr(self.radices,ctypes.c_uint32),
            len(self.radices),base,count,self.profile.seed,self.profile.prime,self.profile.mask,
            ALGORITHMS[self.profile.algorithm],ptr(self.secret,ctypes.c_uint8),len(self.profile.secret),
            ptr(self.targets,ctypes.c_uint64),len(self.targets),ptr(hits,ctypes.c_uint8),self.threads)
        return np.flatnonzero(hits).tolist()

class GPU(CPU):
    def __init__(self,plan,profile,targets,threads=0,device_index=0):
        super().__init__(plan,profile,targets,threads)
        import pyopencl as cl
        self.cl=cl
        all_devices=[d for p in cl.get_platforms() for d in p.get_devices(device_type=cl.device_type.GPU)]
        if not all_devices:
            raise RuntimeError('没有 OpenCL GPU')
        d=all_devices[device_index]
        self.name='OpenCL · '+d.name
        self.context=cl.Context([d])
        self.queue=cl.CommandQueue(self.context)
        self.program=cl.Program(self.context,KERNEL).build()
        self.kernel=cl.Kernel(self.program,'scan')
        mf=cl.mem_flags
        self.buffers=[cl.Buffer(self.context,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=a)
                      for a in (self.data,self.offsets,self.starts,self.radices,
                                self.targets if len(self.targets) else np.zeros(1,dtype=np.uint64),self.secret)]

    def scan(self,base,count):
        cl=self.cl
        hits=np.zeros(count,dtype=np.uint8)
        output=cl.Buffer(self.context,cl.mem_flags.WRITE_ONLY,hits.nbytes)
        self.kernel(self.queue,(count,),None,*self.buffers[:4],np.uint32(len(self.radices)),
            np.uint64(base),np.uint64(self.profile.seed),np.uint64(self.profile.prime),np.uint64(self.profile.mask),
            np.uint32(ALGORITHMS[self.profile.algorithm]),self.buffers[5],np.uint32(len(self.profile.secret)),
            self.buffers[4],np.uint32(len(self.targets)),output)
        cl.enqueue_copy(self.queue,hits,output).wait()
        return np.flatnonzero(hits).tolist()

def choose_backend(mode,plan,profile,targets,threads=0,device_index=0):
    import time
    init=time.perf_counter()
    cpu=CPU(plan,profile,targets,threads)
    calibration_hashes=0
    cpu_setup=time.perf_counter()-init
    if mode=='cpu':
        return cpu,{'selected':cpu.name}
    if mode=='auto' and plan.total<=4096:
        return cpu,{'selected':cpu.name,'reason':'small candidate space; avoid GPU initialization'}
    try:
        init=time.perf_counter()
        gpu=GPU(plan,profile,targets,threads,device_index)
        gpu_setup=time.perf_counter()-init
        if mode=='gpu':
            # Startup self-test is checked against the native CPU independently.
            n=min(plan.total,4096)
            gpu_hits=gpu.scan(0,n);calibration_hashes+=n
            cpu_hits=cpu.scan(0,n);calibration_hashes+=n
            if gpu_hits!=cpu_hits:
                raise RuntimeError('GPU 自检结果与 CPU 不同')
            return gpu,{'selected':gpu.name,'successful_calibration_forward_hashes':calibration_hashes}
        n=min(plan.total,65536)
        timings={}
        results=[]
        for b in (cpu,gpu):
            start=time.perf_counter()
            results.append(b.scan(0,n))
            calibration_hashes+=n
            timings[b.name]=time.perf_counter()-start
        if results[0]!=results[1]:
            raise RuntimeError('GPU 校准结果与 CPU 不同')
        estimates={cpu.name:cpu_setup+timings[cpu.name]*plan.total/n,
                   gpu.name:gpu_setup+timings[gpu.name]*plan.total/n}
        chosen=min((cpu,gpu),key=lambda b:estimates[b.name])
        return chosen,{'selected':chosen.name,'calibration_seconds':timings,'samples':n,
                       'estimated_total_seconds':estimates,'gpu_setup_seconds':gpu_setup,
                       'successful_calibration_forward_hashes':calibration_hashes}
    except Exception as e:
        if mode=='gpu':
            raise RuntimeError('GPU 初始化失败：'+str(e)) from e
        return cpu,{'selected':cpu.name,'fallback':str(e),
                   'successful_calibration_forward_hashes':calibration_hashes}
