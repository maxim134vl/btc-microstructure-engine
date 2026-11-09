"""Run only the existing nine small codec regressions against current app bytes.

No four-TF benchmark, market stream, permission or publication is executed.
The unchanged checker is supplied as a separately hashed validation artifact.
"""
from pathlib import Path
import importlib.util,runpy

scope=runpy.run_path('/checks/check.py',run_name='saved_regression_definitions')
def load(version):
    path=(Path('/candidate/releases/071126/components/context-refresh-daemon/app/src/btc_ml/external_traders/context_stage2_evidence.py')
          if version=='before' else Path('/app/src/btc_ml/external_traders/context_stage2_evidence.py'))
    spec=importlib.util.spec_from_file_location(version+'_accepted_codec',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
scope['regressions'].__globals__['load']=load
scope['regressions']()
