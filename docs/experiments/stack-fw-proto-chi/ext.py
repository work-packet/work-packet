import json,sys,collections
for f in sys.argv[1:]:
    print("=====",f.split('/')[-1])
    n=0;tools=collections.Counter();asst=0;peak=0;tot=collections.Counter();msgids=set()
    for i,l in enumerate(open(f),1):
        try:d=json.loads(l)
        except:continue
        t=d.get('type')
        if t=='user' and not d.get('isMeta') and not d.get('isSidechain'):
            c=d.get('message',{}).get('content')
            txt=None
            if isinstance(c,str): txt=c
            elif isinstance(c,list):
                ts=[b.get('text','') for b in c if b.get('type')=='text']
                if ts and not any(b.get('type')=='tool_result' for b in c): txt='\n'.join(ts)
            if txt and not txt.startswith('<local-command') and not txt.startswith('<command-') and 'Caveat:' not in txt[:30]:
                print(f"--- L{i} {d.get('timestamp')} len={len(txt)}\n{txt[:1500]}")
        if t=='assistant':
            m=d['message'];mid=m.get('id')
            for b in m.get('content',[]):
                if b.get('type')=='tool_use': tools[b['name']]+=1
            if mid in msgids: continue
            msgids.add(mid);asst+=1
            u=m.get('usage',{})
            for k in ['input_tokens','cache_creation_input_tokens','cache_read_input_tokens','output_tokens']: tot[k]+=u.get(k,0) or 0
            ctx=(u.get('input_tokens',0) or 0)+(u.get('cache_creation_input_tokens',0) or 0)+(u.get('cache_read_input_tokens',0) or 0)
            peak=max(peak,ctx)
    print("API calls",asst,"tools",sum(tools.values()),dict(tools.most_common()),"usage",dict(tot),"peak",peak)
