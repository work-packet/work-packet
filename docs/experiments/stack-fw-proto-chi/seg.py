import json,sys,re,collections
F=sys.argv[1]
segs=[];cur=None;msgids=set()
def new(i,ts,label):
    global cur
    cur=dict(line=i,ts=ts,label=label,calls=0,out=0,peak=0,ctxsum=0,tools=collections.Counter(),designreads=0,writes=[],last_ts=ts,lasttext='')
    segs.append(cur)
for i,l in enumerate(open(F),1):
    d=json.loads(l);t=d.get('type')
    if t=='attachment' and d.get('attachment',{}).get('type')=='queued_command':
        p=d['attachment'].get('prompt');
        if isinstance(p,str) and not p.startswith('<task-notification'): new(i,d.get('timestamp'),'Q:'+p[:70])
    if t=='user' and not d.get('isSidechain'):
        c=d['message'].get('content')
        txt=c if isinstance(c,str) else None
        if isinstance(c,list):
            ts=[b.get('text','') for b in c if b.get('type')=='text']
            if ts and not any(b.get('type')=='tool_result' for b in c): txt='\n'.join(ts)
        if txt and not txt.startswith('<local-command') and not txt.startswith('<command-') and not txt.startswith('<task-notif'):
            new(i,d.get('timestamp'),txt[:70].replace('\n',' '))
    if t=='assistant' and cur:
        m=d['message']
        for b in m.get('content',[]):
            if b.get('type')=='tool_use':
                cur['tools'][b['name']]+=1
                inp=json.dumps(b.get('input'))
                if 'fw-proto-chi-design.md' in inp and b['name'] in('Read','Bash') and re.search(r'(sed -n|cat |grep|head|Read|awk)',inp+b['name']): cur['designreads']+=1
                if b['name'] in('Write','Edit'): cur['writes'].append(b['input'].get('file_path','').split('fw-proto-chi/')[-1])
            if b.get('type')=='text' and b.get('text','').strip(): cur['lasttext']=b['text']
        cur['last_ts']=d.get('timestamp')
        if m.get('id') in msgids: continue
        msgids.add(m.get('id'));u=m.get('usage',{})
        ctx=sum((u.get(k) or 0) for k in['input_tokens','cache_creation_input_tokens','cache_read_input_tokens'])
        cur['calls']+=1;cur['out']+=u.get('output_tokens',0) or 0;cur['peak']=max(cur['peak'],ctx);cur['ctxsum']+=ctx
for s in segs:
    print(f"L{s['line']} {s['ts'][:16]}->{s['last_ts'][11:16]} calls={s['calls']} out={s['out']//1000}k peak={s['peak']//1000}k ctxsum={s['ctxsum']//1000000}M dreads={s['designreads']} tools={dict(s['tools'])} | {s['label']}")
    if s['writes']: print("   writes:",sorted(set(s['writes']))[:25])
    print("   END:",s['lasttext'][:600].replace('\n',' '))
