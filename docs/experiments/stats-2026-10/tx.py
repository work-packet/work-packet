import json,glob,os,collections,re
tool_n=collections.Counter(); tool_chars=collections.Counter(); big=[]; bash_cmds=collections.Counter()
reads_whole=0; reads=0; subagent=0; gaps=[]; has_ts=0
for f in glob.glob(os.path.expanduser('~/projects/packets/**/steps/*/transcript.jsonl'),recursive=True):
    if '/work/' in f: continue
    proj=f.split('/packets/')[1].split('/')[0]
    ids={}
    for l in open(f):
        try: e=json.loads(l)
        except: continue
        if e.get('type')=='assistant':
            for c in e['message'].get('content',[]):
                if c.get('type')=='tool_use':
                    n=c['name']; tool_n[n]+=1; ids[c['id']]=(n,c.get('input',{}))
                    if n=='Read':
                        reads+=1
                        if not c['input'].get('limit'): reads_whole+=1
                    if n in('Task','Agent'): subagent+=1
                    if n=='Bash': bash_cmds[c['input'].get('command','').strip().split()[0] if c['input'].get('command','').strip() else '']+=1
        if e.get('type')=='user':
            cont=e['message'].get('content')
            if isinstance(cont,list):
                for c in cont:
                    if c.get('type')=='tool_result':
                        txt=c.get('content'); s=json.dumps(txt) if not isinstance(txt,str) else txt
                        n,inp=ids.get(c['tool_use_id'],('?',{}))
                        tool_chars[n]+=len(s)
                        big.append((len(s),proj,n,(inp.get('command') or inp.get('file_path') or inp.get('pattern') or '')[:90]))
tot=sum(tool_chars.values())
print('tool calls',sum(tool_n.values()),'; result chars %.1fM'%(tot/1e6),'(~%.1fM tok)'%(tot/4e6))
for n,v in tool_n.most_common(): print(f'  {n:8} calls={v:5} result_chars={tool_chars[n]/1e3:8.0f}k share={tool_chars[n]/tot:.2f} avg={tool_chars[n]/v:6.0f}')
print('Read calls',reads,'without limit',reads_whole,'subagent calls',subagent)
print('bash leaders',bash_cmds.most_common(15))
big.sort(reverse=True)
print('results>20k chars:',sum(1 for b in big if b[0]>20000),'of',len(big),'; their share %.2f'%(sum(b[0] for b in big if b[0]>20000)/tot))
for b in big[:15]: print('  ',b)
