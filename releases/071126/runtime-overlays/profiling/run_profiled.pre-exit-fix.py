# Exact original script module + unchanged main(argv); only callable timers.
import sys,runpy,btcml_perf
path=sys.argv.pop(1);sys.argv[0]=path
module=runpy.run_path(path,run_name='__btcml_profile_only__')
from types import SimpleNamespace
proxy=SimpleNamespace(**module);btcml_perf.patch_module(proxy)
# Module functions resolve via their actual globals dictionary.
for k,v in vars(proxy).items():
 if k in module:
  for obj in list(module.values()):
   if hasattr(obj,'__globals__') and obj.__globals__.get('__file__')==path:obj.__globals__[k]=v
module['main']()
