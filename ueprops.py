#!/usr/bin/env python3
"""Minimal UE5.4+ (typename-tree) property-tag walker for SN2 save streams."""
import struct

def rstr(d,p):
    n,=struct.unpack_from('<i',d,p); p+=4
    if n==0: return '',p
    if n<0:
        n=-n; s=d[p:p+2*n].decode('utf-16-le').rstrip('\0'); return s,p+2*n
    s=d[p:p+n].decode('latin1').rstrip('\0'); return s,p+n

def rtype(d,p):
    """type-name tree: name, int32 innerCount, inner..."""
    name,p=rstr(d,p)
    cnt,=struct.unpack_from('<i',d,p); p+=4
    inner=[]
    for _ in range(cnt):
        t,p=rtype(d,p); inner.append(t)
    return (name,inner),p

def tstr(t):
    n,inner=t
    return n if not inner else f"{n}<{','.join(tstr(i) for i in inner)}>"

def walk(d,p,end,depth=0,out=None,maxdepth=1):
    """yield (offset,name,type,size,payload_off) for properties at this level until None."""
    while p<end:
        start=p
        name,p=rstr(d,p)
        if name=='None': return p
        t,p=rtype(d,p)
        size,=struct.unpack_from('<i',d,p); p+=4
        flag=d[p]; p+=1
        payload=p
        print('  '*depth+f'@{start} {name} : {tstr(t)} size={size} payload@{payload}')
        p=payload+size
    return p

if __name__=='__main__':
    import sys
    d=open(sys.argv[1],'rb').read()
    start=int(sys.argv[2]) if len(sys.argv)>2 else 0
    walk(d,start,len(d))
