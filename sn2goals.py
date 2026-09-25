#!/usr/bin/env python3
"""Locate and list the story-goal containers in a decompressed SN2 GameData stream."""
import os,sys,struct; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from ueprops import rstr,rtype,tstr
def props(d,p,end):
    out=[]
    while p<end:
        start=p; name,p=rstr(d,p)
        if name=='None': return out,p
        t,p=rtype(d,p); size,=struct.unpack_from('<i',d,p); p+=4; flag=d[p]; p+=1
        out.append(dict(name=name,type=tstr(t),size=size,payload=p,start=start,next=p+size)); p+=size
    return out,p

def locate(d,target):
    """Return dict of offsets for the goal record with guid target in a decompressed stream."""
    top,_=props(d,5,len(d))
    sd=[x for x in top if x['name']=='SaveData'][0]
    p=sd['payload']; rem,cnt=struct.unpack_from('<ii',d,p); p+=8
    for i in range(cnt):
        guid=d[p:p+16]; p+=16
        vals,p=props(d,p,len(d))
        if guid==target:
            data=[v for v in vals if v['name']=='Data'][0]
            q=data['payload']; n,=struct.unpack_from('<i',d,q); q+=4
            inner_end=q+n
            ip,_=props(d,q+1,inner_end)
            sg=[x for x in ip if x['name']=='StoryGoals'][0]
            ep,_=props(d,sg['payload'],sg['next'])
            e=ep[0]; r=e['payload']; ecount,=struct.unpack_from('<i',d,r); r+=4
            ents=[]
            for k in range(ecount):
                s=r; pl,r=props(d,r,e['next']); ents.append((s,r))
            return dict(savedata=sd,data=data,bytes_count_off=data['payload'],inner_start=q,inner_end=inner_end,
                        storygoals=sg,entries=e,entries_count_off=e['payload'],ents=ents,entries_end=r)
    return None

if __name__=='__main__':
    if len(sys.argv)!=2:
        sys.exit('usage: sn2goals.py STREAM.bin')
    d=open(sys.argv[1],'rb').read()
    for g in ['fe4336a9ca3953a0158d8f9583b9defd','a51739146e3bae4f91fa5aa2a192c919']:
        L=locate(d,bytes.fromhex(g))
        print('guid',g)
        if L is None:
            print('  not found'); continue
        print('  SaveData size',L['savedata']['size'],'Data size',L['data']['size'],'inner bytes',L['inner_end']-L['inner_start'])
        print('  StoryGoals size',L['storygoals']['size'],'Entries size',L['entries']['size'],'count',len(L['ents']),'entries_end',L['entries_end'],'entries next',L['entries']['next'])
        s,t=L['ents'][-1]; print('  last entry',s,t,'len',t-s); print('  hex:',d[s:t].hex())
        print('  entry len set',sorted(set(t-s for s,t in L['ents'])))
        # what follows entries array within StoryGoals struct / inner list
        print('  tail after entries to inner_end:',d[L['entries_end']:L['inner_end']].hex())
