#!/usr/bin/env python3
"""Dedicated support process. No main launcher, exchange calls or trading."""
import json
import os
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[5]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from storage.path_registry import data_root
from btc_ml.runtime import cognitive_cycle as _approved_cycle
from btc_ml.runtime.cognitive_cycle import run_cycle,observe,home,atomic,encode,CognitiveStateUnavailable
# Same approved reducer bytes, private to this extension; baseline /app originals stay intact.
_approved_cycle.SOURCE = ROOT / "deploy/vps/cognition_extension/reducers"

def main():
    root=data_root()
    try:
        generation=os.environ.get('BTC_ML_COGNITION_GENERATION','')
        if not generation:raise CognitiveStateUnavailable('EXPLICIT_COGNITIVE_GENERATION_REQUIRED')
        # Historical acquisition is opt-in test configuration, never a live default.
        test_cutoff=os.environ.get('BTC_ML_COGNITION_TEST_OBSERVATION_CUTOFF')
        if test_cutoff is not None and os.environ.get('BTC_ML_COGNITION_TEST_ONLY')!='TEST_ONLY':
            raise CognitiveStateUnavailable('TEST_ONLY_OBSERVATION_CUTOFF_NOT_AUTHORIZED')
        if test_cutoff is not None:
            test_cutoff=pd.Timestamp(test_cutoff)
            if pd.isna(test_cutoff) or test_cutoff.tzinfo is None:
                raise CognitiveStateUnavailable('TEST_ONLY_OBSERVATION_CUTOFF_REQUIRES_EXPLICIT_TIMEZONE')
        if (home(root)/'pending.json').exists():
            result=run_cycle(root,generation)
        else:
            if test_cutoff is None:
                frames,proof=observe(root,pd.Timestamp.now(tz='UTC'))
            else:
                frames,proof=observe(root,pd.Timestamp.now(tz='UTC'),observation_cutoff=test_cutoff)
            result=run_cycle(root,generation,frames,proof,initialize=os.environ.get('BTC_ML_COGNITION_INITIALIZE_EMPTY','0')=='1')
    except (CognitiveStateUnavailable,FileNotFoundError) as error:
        result={'status':'SKIPPED','reason':'REQUIRED_INPUT_UNAVAILABLE','detail':str(error)}
    except Exception as error:
        result={'status':'FAILED','reason':type(error).__name__,'detail':str(error)}
    atomic(root/'runtime/cognitive_cycle_status.json',encode(result))
    print(json.dumps(result))
    return 0 if result['status']=='SUCCESS' else 2

if __name__=='__main__':raise SystemExit(main())
