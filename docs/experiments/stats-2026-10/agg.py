import json,glob,os,collections,statistics as st
rows=[]
for f in glob.glob(os.path.expanduser('~/projects/packets/**/steps/*/meta.json'),recursive=True):
    if '/work/' in f: continue
    m=json.load(open(f)); parts=f.split('/')
    proj=parts[parts.index('packets')+1]
    t=m.get('tokens') or {}; c=m.get('context') or {}
    d=os.path.dirname(f)
    rows.append(dict(proj=proj,step=m.get('step'),att=m.get('attempt'),model=m.get('model'),cost=m.get('cost_usd') or 0,
      inp=t.get('input_tokens',0),cw=t.get('cache_creation_input_tokens',0),cr=t.get('cache_read_input_tokens',0),
      out=t.get('output_tokens',0),think=t.get('thinking_tokens',0),cw5=t.get('cache_write_5m',0),
      first=c.get('first',0),peak=c.get('peak',0),calls=c.get('calls',0),breaks=c.get('cache_breaks',0),rewrite=c.get('cache_rewrite',0),
      dur=m.get('duration_s') or 0,api=m.get('api_s') or 0,err=m.get('is_error'),to=m.get('timed_out'),exit=m.get('exit_code'),
      carried=m.get('carried_from'),prompt=os.path.getsize(d+'/prompt.md') if os.path.exists(d+'/prompt.md') else 0,
      system=os.path.getsize(d+'/system.md') if os.path.exists(d+'/system.md') else 0, path=d))
json.dump(rows,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'rows.json'),'w'))
def summ(key):
    g=collections.defaultdict(list)
    for r in rows: g[key(r)].append(r)
    print(f"{'group':38} {'n':>4} {'$':>8} {'$/st':>6} {'calls':>6} {'peak_med':>8} {'peak_max':>8} {'first_med':>9} {'out/st':>7} {'cr/cw':>6} {'brk':>4} {'err':>3} {'TO':>3} {'min/st':>6}")
    for k,v in sorted(g.items(),key=lambda kv:-sum(r['cost'] for r in kv[1])):
        cost=sum(r['cost'] for r in v); cw=sum(r['cw'] for r in v) or 1
        print(f"{str(k)[:38]:38} {len(v):4} {cost:8.2f} {cost/len(v):6.2f} {st.median([r['calls'] for r in v]):6.0f} {st.median([r['peak'] for r in v]):8.0f} {max(r['peak'] for r in v):8} {st.median([r['first'] for r in v]):9.0f} {st.mean([r['out'] for r in v]):7.0f} {sum(r['cr'] for r in v)/cw:6.1f} {sum(r['breaks'] for r in v):4} {sum(1 for r in v if r['err']):3} {sum(1 for r in v if r['to']):3} {st.mean([r['dur'] for r in v])/60:6.1f}")
print("TOTAL $",round(sum(r['cost'] for r in rows),2),"steps",len(rows))
summ(lambda r:r['model']); print(); summ(lambda r:r['proj']); print(); summ(lambda r:(r['proj'][:24],r['model'][7:12] if r['model'] else None))
