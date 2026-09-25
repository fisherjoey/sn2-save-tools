#!/usr/bin/env python3
"""Find UE v2 compressed-chunk blobs inside a Subnautica2 .sav, decompress via ooz."""
import struct, subprocess, sys, os, tempfile
# Path to an ooz binary (https://github.com/powzix/ooz). Override with SN2_OOZ.
OOZ = os.environ.get('SN2_OOZ', 'ooz')
TAG = b'\xc1\x83\x2a\x9e\x22\x22\x22\x22'

def find_blobs(d):
    out=[]; i=0
    while True:
        i=d.find(TAG,i)
        if i<0: break
        p=i+8
        chunk_size,=struct.unpack_from('<q',d,p); p+=8
        comp=d[p]; p+=1
        csum,usum=struct.unpack_from('<qq',d,p); p+=16
        n=(usum+chunk_size-1)//chunk_size
        chunks=[]
        for _ in range(n):
            c,u=struct.unpack_from('<qq',d,p); p+=16; chunks.append((c,u))
        data_start=p
        parts=[]
        for c,u in chunks:
            parts.append((p,c,u)); p+=c
        out.append(dict(tag_off=i,hdr_end=data_start,end=p,chunk_size=chunk_size,comp=comp,csum=csum,usum=usum,chunks=parts))
        i=p
    return out

def ooz_decomp(raw,usize):
    with tempfile.TemporaryDirectory() as t:
        fi=os.path.join(t,'in'); fo=os.path.join(t,'out')
        open(fi,'wb').write(struct.pack('<Q',usize)+raw)
        r=subprocess.run([OOZ,'-d','-q',fi,fo],capture_output=True)
        if r.returncode!=0: raise RuntimeError(r.stderr.decode())
        return open(fo,'rb').read()

def ooz_comp(raw,level=4):
    with tempfile.TemporaryDirectory() as t:
        fi=os.path.join(t,'in'); fo=os.path.join(t,'out')
        open(fi,'wb').write(raw)
        r=subprocess.run([OOZ,'-z','-q',f'-{level}','--kraken',fi,fo],capture_output=True)
        if r.returncode!=0: raise RuntimeError(r.stderr.decode())
        return open(fo,'rb').read()[8:]

def decompress_blob(d,b):
    if b['comp']==0:
        return d[b['hdr_end']:b['end']]
    return b''.join(ooz_decomp(d[o:o+c],u) for o,c,u in b['chunks'])

if __name__=='__main__':
    if len(sys.argv)!=3:
        sys.exit('usage: sn2blob.py IN.sav OUTDIR')
    src=sys.argv[1]; outdir=sys.argv[2]
    os.makedirs(outdir,exist_ok=True)
    d=open(src,'rb').read()
    blobs=find_blobs(d)
    print(f'{len(blobs)} blobs')
    for k,b in enumerate(blobs):
        u=decompress_blob(d,b)
        assert len(u)==b['usum'],(k,len(u),b['usum'])
        open(os.path.join(outdir,f'blob_{k:03d}_{b["tag_off"]}.bin'),'wb').write(u)
        print(f'{k:3d} off={b["tag_off"]:8d} comp={b["comp"]} c={b["csum"]:7d} u={b["usum"]:7d} chunks={len(b["chunks"])}')
