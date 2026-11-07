import pathlib,time,json,datetime,os
R=pathlib.Path('/profile');logprev={}
while not (R/'STOP_OBSERVER').exists():
 s=time.monotonic();d={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'mono':s,'cgroups':{},'logs':[],'vm':{}}
 for n in ['meminfo','stat','pressure/cpu','pressure/memory','pressure/io']:
  try:d['vm'][n]=(pathlib.Path('/proc')/n).read_text()
  except OSError:pass
 try:
  for c in json.loads((R/'container-pids.json').read_text()):
   pid=c.get('pid');service=c['service']
   if pid:
    try:
     group=(pathlib.Path('/proc')/str(pid)/'cgroup').read_text().split('::',1)[1].strip();base=pathlib.Path('/proc')/str(pid)/'root/sys/fs/cgroup';d['cgroups'][service]={n:(base/n).read_text() for n in ['cpu.stat','memory.current','memory.peak','memory.events','memory.swap.current','io.stat','pids.current','cpu.pressure','memory.pressure','io.pressure'] if (base/n).exists()}
    except OSError:pass
   if c.get('logpath'):
    p=pathlib.Path('/proc/1/root')/c['logpath'].lstrip('/')
    try:
     st=p.stat();old=logprev.get(str(p));record={'service':service,'path':c['logpath'],'bytes':st.st_size,'inode':st.st_ino}
     if old and st.st_ino==old['inode'] and st.st_size>=old['bytes']:
      delta=st.st_size-old['bytes'];elapsed=s-old['mono'];record.update(delta_bytes=delta,bytes_per_s=delta/elapsed)
      if delta<=1048576:
       with p.open('rb') as f:f.seek(old['bytes']);record['lines_per_s']=f.read(delta).count(b'\n')/elapsed
      else:record['lines_per_s']='NOT_MEASURED_DELTA_TOO_LARGE'
     logprev[str(p)]={'bytes':st.st_size,'mono':s,'inode':st.st_ino};d['logs'].append(record)
    except OSError:pass
 except Exception as ex:d['error']=str(ex)
 with (R/'linux-extra.jsonl').open('a') as f:f.write(json.dumps(d)+'\n')
 time.sleep(max(.1,5-(time.monotonic()-s)))
