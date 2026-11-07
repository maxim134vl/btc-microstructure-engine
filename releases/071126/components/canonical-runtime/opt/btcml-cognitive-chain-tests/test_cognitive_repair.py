"""Regression fixtures are isolated, never seed live contexts."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

ROOT=Path('/app')
EVIDENCE=Path('/evidence')
ENGINES=['test_recognition_engine_v1.py','defended_liquidity_engine_v1.py','contextual_memory_loader_v2.py','perception_context_integration_v1.py','temporal_context_memory_v1.py']


def execute(name, inputs, original=False):
    outputs={}
    def reader(name,*args,**kwargs):
        if name not in inputs:
            raise FileNotFoundError(name)
        return inputs[name].copy(deep=True)
    def writer(df,name,*args,**kwargs):
        outputs[name]=df.copy(deep=True)
    path=EVIDENCE/'actual'/name if original else ROOT/name
    with patch.dict(os.environ,{'BTC_ML_COGNITIVE_CHAIN_LIVE':'0'}), patch.object(pd,'read_parquet',reader),patch.object(pd.DataFrame,'to_parquet',writer),contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(str(path),run_name='__main__')
    return outputs


class CognitiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g=pd.read_parquet(EVIDENCE/'evidence/real_geometry.parquet')
        cls.z=pd.read_parquet(EVIDENCE/'evidence/real_zones.parquet')
        assert cls.g.timestamp.equals(cls.z.timestamp)

    def data(self,n=None):
        return {'candle_geometry_v2_memory.parquet':self.g.iloc[:n] if n else self.g,'volume_localization_v2_memory.parquet':self.z.iloc[:n] if n else self.z}

    def test_original_formula_identity(self):
        for name in ENGINES:
            original=ast.parse((EVIDENCE/'actual'/name).read_text())
            candidate=ast.parse((ROOT/name).read_text())
            candidate.body=[x for x in candidate.body if not (isinstance(x,ast.ImportFrom) and x.module=='cognitive_chain_io') and not (isinstance(x,ast.Expr) and isinstance(x.value,ast.Call) and isinstance(x.value.func,ast.Name) and x.value.func.id=='install_io') and not (isinstance(x,ast.Assign) and any(isinstance(y,ast.Name) and y.id=='_cognitive_decision_at' for y in x.targets))]
            if name=='temporal_context_memory_v1.py':
                for x in ast.walk(candidate):
                    if isinstance(x,ast.ExceptHandler) and isinstance(x.type,ast.Name) and x.type.id=='FileNotFoundError':x.type=None
                    if isinstance(x,ast.If) and isinstance(x.test,ast.BoolOp) and any(isinstance(y,ast.Compare) and 'previous.index' in ast.unparse(y) for y in x.test.values):x.test=x.test.values[-1]
            if name in {'contextual_memory_loader_v2.py','perception_context_integration_v1.py'}:
                for x in candidate.body:
                    if isinstance(x,ast.Assign) and any(isinstance(y,ast.Name) and y.id=='_legacy_available_at' for y in x.targets):
                        x.value=next(y.value for y in original.body if isinstance(y,ast.Assign) and any(isinstance(z,ast.Name) and z.id=='_legacy_available_at' for z in y.targets))
            self.assertEqual(ast.dump(original,include_attributes=False),ast.dump(candidate,include_attributes=False),name)

    def test_real_original_outputs_unchanged(self):
        data=self.data()
        for name,key in [(ENGINES[0],'test_recognition_memory.parquet'),(ENGINES[1],'defended_liquidity_memory.parquet')]:
            before=execute(name,data,True)[key];after=execute(name,data)[key]
            pd.testing.assert_frame_equal(before,after)
            data[key]=after

    def test_real_market_prefixes_are_immutable(self):
        full=execute(ENGINES[0],self.data())['test_recognition_memory.parquet']
        for n in [20,50,100,500,len(self.g)-1]:
            result=execute(ENGINES[0],self.data(n))['test_recognition_memory.parquet']
            pd.testing.assert_frame_equal(full.iloc[:n-1].reset_index(drop=True),result.reset_index(drop=True))
            before=execute(ENGINES[1],{**self.data(n),'test_recognition_memory.parquet':result})['defended_liquidity_memory.parquet']
            after=execute(ENGINES[1],{**self.data(),'test_recognition_memory.parquet':full})['defended_liquidity_memory.parquet']
            pd.testing.assert_frame_equal(after.iloc[:n-1].reset_index(drop=True),before.reset_index(drop=True))

    def test_temporal_first_pass_reproduced_then_fixed(self):
        # Explicit fixture tests specified original zero-count branch, not an initial
        # state choice for contextual/perception and never written to live volumes.
        context=pd.DataFrame([dict(timestamp=pd.Timestamp('2025-01-01'),regime_state='BEARISH_PRESSURE',inventory_modifier='LIQUIDITY_FAILED',acceptance_modifier='ACCEPTANCE_BREAKING',reaction_state='EXHAUSTION')])
        inputs={'contextual_memory_state.parquet':context}
        with self.assertRaises(NameError):execute(ENGINES[-1],inputs,True)
        after=execute(ENGINES[-1],inputs)['temporal_context_memory.parquet']
        self.assertEqual(len(after),1);self.assertEqual(after.bearish_persistence.iloc[0],1)
        self.assertEqual(after.failure_persistence.iloc[0],1)
        # All existing-state event priorities and original ring behavior unchanged.
        for _ in range(6):
            context=context.copy();context.timestamp+=pd.Timedelta(minutes=15)
            inputs={'contextual_memory_state.parquet':context,'temporal_context_memory.parquet':after}
            before=execute(ENGINES[-1],inputs,True)['temporal_context_memory.parquet']
            after=execute(ENGINES[-1],inputs)['temporal_context_memory.parquet']
            pd.testing.assert_frame_equal(before,after)

    def test_future_and_duplicate_candles_rejected(self):
        from cognitive_chain_io import validate_times
        at=pd.to_datetime(self.g.timestamp.max(),utc=True)+pd.Timedelta(minutes=15)
        validate_times(self.g,'candle_geometry_v2_memory.parquet',at)
        with self.assertRaises(ValueError):validate_times(self.g,'candle_geometry_v2_memory.parquet',at-pd.Timedelta(minutes=1))
        with self.assertRaises(ValueError):validate_times(pd.concat([self.g,self.g.tail(1)]),'candle_geometry_v2_memory.parquet',at)

    def test_original_dependencies_remain_mandatory(self):
        from runtime_dependency_map import DEPENDENCIES
        self.assertIn('temporal_context_memory.parquet',DEPENDENCIES[ENGINES[2]])
        self.assertIn('temporal_context_memory.parquet',DEPENDENCIES[ENGINES[3]])
        self.assertIn('contextual_memory_state.parquet',DEPENDENCIES[ENGINES[4]])
        self.assertNotIn('temporal_context_memory.parquet',DEPENDENCIES[ENGINES[4]])

    def test_startup_contract_both_modes_and_bad_order(self):
        from runtime_hardening import validate_canonical_pipeline_order
        from btc_ml.runtime.pipeline import CANONICAL_PIPELINE,EXPECTED_CANONICAL_PIPELINE_STEP_COUNT
        self.assertEqual(EXPECTED_CANONICAL_PIPELINE_STEP_COUNT,28)
        self.assertEqual(validate_canonical_pipeline_order(CANONICAL_PIPELINE,28),[])
        swapped=list(CANONICAL_PIPELINE);i=swapped.index(ENGINES[2]);swapped[i],swapped[i+1]=swapped[i+1],swapped[i]
        self.assertTrue(validate_canonical_pipeline_order(swapped,28))
        env={**os.environ,'BTC_ML_STAGE2_SYNTHESIS_INPUTS_LIVE':'1'}
        command='from btc_ml.runtime.pipeline import *; from runtime_hardening import validate_canonical_pipeline_order; assert len(CANONICAL_PIPELINE)==33; assert not validate_canonical_pipeline_order(CANONICAL_PIPELINE,33)'
        subprocess.run(['python','-c',command],env=env,check=True,capture_output=True)

    def test_guard_blocks_missing_cold_start(self):
        from runtime_dependency_guard import should_run_engine,LAST_DECISIONS
        from runtime_dependency_map import DEPENDENCIES
        import storage.path_registry as registry
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'BTC_ML_DATA_ROOT':temp,'BTC_ML_COGNITIVE_CHAIN_LIVE':'1'}):
            for engine in ENGINES[2:]:
                self.assertFalse(should_run_engine(engine,DEPENDENCIES[engine]))
                self.assertEqual(LAST_DECISIONS[engine]['reason'],'REQUIRED_INPUT_UNAVAILABLE')
            for name in registry.COGNITIVE_CHAIN_FILES:
                self.assertFalse(Path(registry.resolve_read(name)).exists())
                self.assertFalse(registry.migrate_legacy(name))


    def test_live_io_atomic_publication_and_immutable_prefix(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'cognition').mkdir()
            env={**os.environ,'BTC_ML_DATA_ROOT':temp,'BTC_ML_COGNITIVE_CHAIN_LIVE':'1'}
            def stage(n):
                self.g.iloc[:n].to_parquet(root/'cognition/candle_geometry_v2_memory.parquet')
                self.z.iloc[:n].to_parquet(root/'cognition/volume_localization_v2_memory.parquet')
            def run(name):
                return subprocess.run(['python',str(ROOT/name)],env=env,capture_output=True,text=True)
            stage(50)
            self.assertEqual(run(ENGINES[0]).returncode,0)
            self.assertEqual(run(ENGINES[1]).returncode,0)
            old=pd.read_parquet(root/'cognition/test_recognition_memory.parquet')
            before=list((root/'diagnostics/cognitive_chain/test_recognition_memory').glob('*.json'))
            self.assertEqual(len(before),1)
            pub=json.loads(before[0].read_text())
            self.assertGreater(pd.Timestamp(pub['available_at']),pd.to_datetime(old.timestamp.max(),utc=True))
            self.assertEqual(run(ENGINES[0]).returncode,0)
            self.assertEqual(len(list(before[0].parent.glob('*.json'))),1)
            stage(100)
            result=run(ENGINES[0]);self.assertEqual(result.returncode,0,result.stderr)
            result=run(ENGINES[1]);self.assertEqual(result.returncode,0,result.stderr)
            extended=pd.read_parquet(root/'cognition/test_recognition_memory.parquet')
            pd.testing.assert_frame_equal(old,extended.iloc[:len(old)])
            target=root/'cognition/test_recognition_memory.parquet';sha=hashlib.sha256(target.read_bytes()).hexdigest()
            stage(20)
            failed=run(ENGINES[0]);self.assertNotEqual(failed.returncode,0)
            self.assertIn('cannot be truncated',failed.stderr)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),sha)
            self.assertFalse(list(target.parent.glob('.*.tmp')))

    def test_misaligned_real_inputs_fail_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'cognition').mkdir()
            self.g.iloc[:50].to_parquet(root/'cognition/candle_geometry_v2_memory.parquet')
            self.z.iloc[1:51].to_parquet(root/'cognition/volume_localization_v2_memory.parquet')
            env={**os.environ,'BTC_ML_DATA_ROOT':temp,'BTC_ML_COGNITIVE_CHAIN_LIVE':'1'}
            result=subprocess.run(['python',str(ROOT/ENGINES[0])],env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('not timestamp-aligned',result.stderr)
            self.assertFalse((root/'cognition/test_recognition_memory.parquet').exists())

    def test_corrupt_temporal_is_not_silently_reset(self):
        def reader(name,*a,**kw):
            if name=='contextual_memory_state.parquet':return pd.DataFrame([dict(timestamp='2025-01-01')])
            raise ValueError('corrupt temporal parquet')
        with patch.dict(os.environ,{'BTC_ML_COGNITIVE_CHAIN_LIVE':'0'}),patch.object(pd,'read_parquet',reader),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError,'corrupt temporal'):
                runpy.run_path(str(ROOT/ENGINES[-1]),run_name='__main__')

if __name__=='__main__':unittest.main()
