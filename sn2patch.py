#!/usr/bin/env python3
"""Add story-goal entries to a Subnautica 2 savegame (.sav). Round-trips through real Oodle."""
import ctypes,struct,sys,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from sn2blob import find_blobs, TAG
from sn2goals import props, locate

# Path to the Oodle shared library (liboo2corelinux64.so.9). It is not
# redistributable, so you must supply your own copy. Override with SN2_OODLE_LIB.
OODLE=os.environ.get('SN2_OODLE_LIB','liboo2corelinux64.so.9')
_lib=None
def oodle_lib():
    """Load the Oodle library on first use, so the pure helpers import without it."""
    global _lib
    if _lib is None:
        lib=ctypes.CDLL(OODLE)
        lib.OodleLZ_Decompress.restype=ctypes.c_longlong
        lib.OodleLZ_Decompress.argtypes=[ctypes.c_void_p,ctypes.c_longlong,ctypes.c_void_p,ctypes.c_longlong,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p,ctypes.c_longlong,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_longlong,ctypes.c_int]
        lib.OodleLZ_Compress.restype=ctypes.c_longlong
        lib.OodleLZ_Compress.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_longlong,ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_longlong]
        _lib=lib
    return _lib
KRAKEN=8; LEVEL=4; CHUNK=131072

def oodle_dec(src,usize):
    dst=ctypes.create_string_buffer(usize)
    n=oodle_lib().OodleLZ_Decompress(src,len(src),dst,usize,1,0,0,None,0,None,None,None,0,3)
    assert n==usize,('decompress failed',n,usize)
    return dst.raw
def oodle_comp(raw):
    out=ctypes.create_string_buffer(len(raw)+274*((len(raw)+0x3ffff)//0x40000)+4096)
    m=oodle_lib().OodleLZ_Compress(KRAKEN,raw,len(raw),out,LEVEL,None,None,None,None,0)
    assert m>0
    c=out.raw[:m]; assert oodle_dec(c,len(raw))==raw
    return c

def decode_buffer(d,start,end):
    """decompress all SerializeCompressed blocks in d[start:end] -> bytes"""
    out=[]; p=start
    while p<end:
        assert d[p:p+8]==TAG,(p,d[p:p+8])
        p+=8; chunk_size,=struct.unpack_from('<q',d,p); p+=8; comp=d[p]; p+=1
        csum,usum=struct.unpack_from('<qq',d,p); p+=16
        n=(usum+chunk_size-1)//chunk_size; chunks=[]
        for _ in range(n): chunks.append(struct.unpack_from('<qq',d,p)); p+=16
        for c,u in chunks:
            out.append(oodle_dec(d[p:p+c],u) if comp==2 else d[p:p+c]); p+=c
    assert p==end
    return b''.join(out)

def encode_buffer(raw):
    out=[]
    for i in range(0,len(raw),CHUNK):
        piece=raw[i:i+CHUNK]; c=oodle_comp(piece)
        out.append(TAG+struct.pack('<q',CHUNK)+b'\x02'+struct.pack('<qq',len(c),len(piece))+struct.pack('<qq',len(c),len(piece))+c)
    return b''.join(out)

def fstr(s): b=s.encode('ascii')+b'\0'; return struct.pack('<i',len(b))+b
def tag(name,typetree,size):
    def tt(t):
        n,inner=t; return fstr(n)+struct.pack('<i',len(inner))+b''.join(tt(i) for i in inner)
    return fstr(name)+tt(typetree)+struct.pack('<i',size)+b'\x00'
NONE=fstr('None')
def goal_entry(name):
    pat_payload=tag('Name',('NameProperty',[]),len(fstr('UWEStoryGoal')))+fstr('UWEStoryGoal')+NONE
    pan_payload=fstr(name)
    sg_payload=(tag('PrimaryAssetType',('StructProperty',[('PrimaryAssetType',[('/Script/CoreUObject',[])])]),len(pat_payload))+pat_payload
               +tag('PrimaryAssetName',('NameProperty',[]),len(pan_payload))+pan_payload+NONE)
    return tag('StoryGoal',('StructProperty',[('PrimaryAssetId',[('/Script/CoreUObject',[])])]),len(sg_payload))+sg_payload+NONE

def set_i32(b,off,v): b[off:off+4]=struct.pack('<i',v)
def get_i32(b,off): return struct.unpack_from('<i',b,off)[0]

def add_goals(stream,guid,names):
    d=bytearray(stream)
    L=locate(bytes(d),guid)
    existing=bytes(d[L['entries']['payload']:L['entries_end']])
    names=[n for n in names if fstr(n) not in existing]
    if not names: return bytes(d),[]
    ins=b''.join(goal_entry(n) for n in names); delta=len(ins)
    at=L['entries_end']
    d[at:at]=ins
    # fix sizes/counts (all offsets < at, so still valid)
    for prop in (L['entries'],L['storygoals'],L['data'],L['savedata']):
        set_i32(d,prop['payload']-5,prop['size']+delta)
    set_i32(d,L['entries_count_off'],len(L['ents'])+len(names))
    set_i32(d,L['bytes_count_off'],get_i32(d,L['bytes_count_off'])+delta)
    set_i32(d,0,get_i32(d,0)+delta)
    return bytes(d),names

PLAYER=bytes.fromhex('fe4336a9ca3953a0158d8f9583b9defd')
WORLD =bytes.fromhex('a51739146e3bae4f91fa5aa2a192c919')

def patch_file(src,dst,player_goals,world_goals,blobs=(0,1)):
    d=bytearray(open(src,'rb').read())
    i=d.find(b'\x0e\x00\x00\x00ContainerInfo\x00')
    top,_=props(bytes(d),i,len(d))
    ss=[x for x in top if x['name']=='SerializedSaveGames'][0]
    p=ss['payload']; n=get_i32(d,p); p+=4
    blob_info=[]
    for k in range(n):
        vals,p=props(bytes(d),p,ss['next'])
        gd=[v for v in vals if v['name']=='GameData'][0]
        inner,_=props(bytes(d),gd['payload'],gd['next'])
        data=[v for v in inner if v['name']=='Data'][0]
        blob_info.append((gd,data))
    total_delta=0; report=[]
    # process from last blob to first so earlier offsets stay valid
    for k in sorted(blobs,reverse=True):
        gd,data=blob_info[k]
        cnt=get_i32(d,data['payload']); s=data['payload']+4; e=s+cnt
        stream=decode_buffer(bytes(d),s,e)
        assert get_i32(stream,0)==len(stream)-4
        new,added_p=add_goals(stream,PLAYER,player_goals)
        new,added_w=add_goals(new,WORLD,world_goals)
        enc=encode_buffer(new)
        assert decode_buffer(enc,0,len(enc))==new
        delta=len(enc)-cnt
        d[s:e]=enc
        set_i32(d,data['payload'],len(enc))
        set_i32(d,data['payload']-5,data['size']+delta)
        set_i32(d,gd['payload']-5,gd['size']+delta)
        total_delta+=delta
        report.append((k,added_p,added_w,len(stream),len(new),cnt,len(enc)))
    set_i32(d,ss['payload']-5,ss['size']+total_delta)
    open(dst,'wb').write(d)
    return report

def main(argv=None):
    import argparse
    ap=argparse.ArgumentParser(description='Append story-goal entries to a Subnautica 2 .sav. Writes a new file; never edits IN in place.')
    ap.add_argument('src',metavar='IN.sav')
    ap.add_argument('dst',metavar='OUT.sav')
    ap.add_argument('--player',action='append',default=[],metavar='GOAL',help='story goal to add to the player container (repeatable)')
    ap.add_argument('--world',action='append',default=[],metavar='GOAL',help='story goal to add to the world container (repeatable)')
    a=ap.parse_args(argv)
    if not a.player and not a.world: ap.error('give at least one --player or --world goal')
    if os.path.abspath(a.src)==os.path.abspath(a.dst): ap.error('OUT must be a different file from IN')
    for r in patch_file(a.src,a.dst,a.player,a.world): print('blob',r[0],'player+',r[1],'world+',r[2],'stream',r[3],'->',r[4],'compressed',r[5],'->',r[6])

if __name__=='__main__':
    main()
