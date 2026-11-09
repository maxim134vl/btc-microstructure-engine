"""Validate accepted owner source/dependencies and compile only the12-file delta.

Unchanged dormant071126 modules are preserved; their pre-existing syntax debt is
reported separately rather than rewritten or mistaken for a new packaging fault.
"""
from pathlib import Path
import hashlib,importlib.metadata,json,stat,sys

root=Path('/candidate');up=root/'releases/071126/updates/20261109';service=sys.argv[1]
scope=[x for x in json.loads((up/'runtime-source-scope.json').read_text()) if x['service']==service]
compiled=[]
for x in scope:
    f=Path(x['runtime_path']);raw=f.read_bytes();s=f.stat()
    assert hashlib.sha256(raw).hexdigest()==x['sha256'],('SHA_PARITY',str(f))
    assert (stat.S_IMODE(s.st_mode),s.st_uid,s.st_gid)==(x['mode'],x['uid'],x['gid']),('MODE_OWNER_PARITY',str(f))
    if x['changed_since071126'] and f.suffix=='.py':compile(raw,str(f),'exec');compiled.append(str(f))
expected=json.loads((up/'dependencies'/(service+'.json')).read_text())['packages']
current={x.metadata['Name']:x.version for x in importlib.metadata.distributions()}
assert expected==current,'DEPENDENCY_PARITY'
print(json.dumps({'service':service,'source_SHA_owner_mode_PASS':len(scope),'changed_source_compile_PASS':len(compiled),'dependency_pins_PASS':len(expected),'production_volumes':False}))
