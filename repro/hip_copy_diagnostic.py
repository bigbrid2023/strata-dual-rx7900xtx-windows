import argparse
import ctypes as C
import json
import mmap
import os
import random
import statistics
import time
from pathlib import Path

w=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
p.add_argument('--runtime',default='engine-upload')
p.add_argument('--base',default='baseline.json')
p.add_argument('--output',default='hip-copy-diagnostic.json')
p.add_argument('--source-file',default='hip-2d-source.bin')
p.add_argument('--skip-bandwidth',action='store_true')
a=p.parse_args()
runtime=w/a.runtime
cfg=json.loads((w/a.base).read_text(encoding='utf-8-sig'))
paths=[runtime]+[Path(p) for p in cfg['lib_dirs'] if Path(p).is_dir()]
dirs=[os.add_dll_directory(str(p)) for p in paths]
os.environ['PATH']=';'.join(str(p) for p in paths)+';'+os.environ['PATH']
hip=C.WinDLL(str(runtime/'amdhip64_7.dll'))
def function(name, argtypes):
    f=getattr(hip,name);f.argtypes=argtypes;f.restype=C.c_int;return f
count=function('hipGetDeviceCount',[C.POINTER(C.c_int)])
setdev=function('hipSetDevice',[C.c_int])
busid=function('hipDeviceGetPCIBusId',[C.c_void_p,C.c_int,C.c_int])
malloc=function('hipMalloc',[C.POINTER(C.c_void_p),C.c_size_t])
free=function('hipFree',[C.c_void_p])
hostalloc=function('hipHostMalloc',[C.POINTER(C.c_void_p),C.c_size_t,C.c_uint])
hostfree=function('hipHostFree',[C.c_void_p])
copy=function('hipMemcpy',[C.c_void_p,C.c_void_p,C.c_size_t,C.c_int])
copy2d=function('hipMemcpy2D',[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.c_size_t,C.c_size_t,C.c_int])
sync=function('hipDeviceSynchronize',[])
def check(code,name):
    if code:raise RuntimeError(name+': HIP status '+str(code))
rows,stride,width=6144,2720,1360
source=random.Random(12345).randbytes(rows*stride)
pageable=C.create_string_buffer(source)
path=w/a.source_file
path.write_bytes(b'H'*256+source)
fd=path.open('rb')
import msvcrt
k=C.WinDLL('kernel32',use_last_error=True)
k.CreateFileMappingW.argtypes=[C.c_void_p,C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_void_p];k.CreateFileMappingW.restype=C.c_void_p
k.MapViewOfFile.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_size_t];k.MapViewOfFile.restype=C.c_void_p
k.UnmapViewOfFile.argtypes=[C.c_void_p];k.CloseHandle.argtypes=[C.c_void_p]
mapping=k.CreateFileMappingW(msvcrt.get_osfhandle(fd.fileno()),None,2,0,0,None)
if not mapping:raise C.WinError(C.get_last_error())
view=k.MapViewOfFile(mapping,4,0,0,0)
if not view:raise C.WinError(C.get_last_error())
n=C.c_int();check(count(C.byref(n)),'count')
results=[]
try:
    for dev in range(n.value):
        check(setdev(dev),'set device')
        bus=C.create_string_buffer(64);check(busid(bus,64,dev),'PCI bus id')
        pinned=C.c_void_p();check(hostalloc(C.byref(pinned),len(source),1),'pin source')
        C.memmove(pinned,source,len(source))
        dst=C.c_void_p();check(malloc(C.byref(dst),rows*width),'allocate destination')
        try:
            for kind,ptr in [('pageable',C.addressof(pageable)),('file-readonly-offset256',view+256),('pinned-portable',pinned.value)]:
                for half in range(2):
                    expected=b''.join(source[r*stride+half*width:r*stride+(half+1)*width] for r in range(rows))
                    check(copy2d(dst,width,ptr+half*width,stride,width,rows,1),'2D upload')
                    actual=C.create_string_buffer(rows*width)
                    check(copy(actual,dst,rows*width,2),'2D download')
                    raw=actual.raw[:rows*width]
                    bad=sum(a!=b for a,b in zip(expected,raw))
                    first=next((i for i,(a,b) in enumerate(zip(expected,raw)) if a!=b),len(expected))
                    packed=C.create_string_buffer(expected)
                    check(copy(dst,packed,len(expected),1),'packed upload')
                    check(copy(actual,dst,len(expected),2),'packed download')
                    packed_bad=sum(a!=b for a,b in zip(expected,actual.raw[:len(expected)]))
                    record={'device':dev,'pci_bus':bus.value.decode(),'source':kind,'half':half,'bytes':len(expected),'2d_mismatch':bad,'first_mismatch':first,'packed_mismatch':packed_bad}
                    results.append(record);print(json.dumps(record),flush=True)
        finally:
            check(free(dst),'free');check(hostfree(pinned),'host free')
        if a.skip_bandwidth:
            continue
        size=128*1024*1024
        h=C.c_void_p();d=C.c_void_p()
        check(hostalloc(C.byref(h),size,1),'bandwidth host allocate');C.memset(h,69,size)
        check(malloc(C.byref(d),size),'bandwidth device allocate')
        try:
            times=[]
            for r in range(6):
                begin=time.perf_counter();check(copy(d,h,size,1),'bandwidth upload');check(sync(),'bandwidth sync')
                if r:times.append(time.perf_counter()-begin)
            record={'device':dev,'pci_bus':bus.value.decode(),'upload_GB_s':size/statistics.median(times)/1e9,'times_s':times}
            results.append(record);print(json.dumps(record),flush=True)
        finally:
            check(free(d),'bandwidth free');check(hostfree(h),'bandwidth host free')
finally:
    k.UnmapViewOfFile(view);k.CloseHandle(mapping);fd.close()
    (w/a.output).write_text(json.dumps(results,indent=2),encoding='utf-8')
