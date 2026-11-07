"""Profiling only: original Controller V9 methods, parameters and call order."""
import importlib,time
import btcml_perf as p

def install():
 p.install()
 for name in ['timeframe_state_adapter','timeframe_manager','command_bus','portfolio_risk','near_tp_miss']:
  m=importlib.import_module('btc_ml.trading.'+name)
  if name=='timeframe_state_adapter':
   for fn,phase in {'load_sources':'LOAD_SOURCES','resolve_timeframe_state':'RESOLVE_OWN_STATE','_scoped_lifecycle':'LOAD_OWN_LIFECYCLE','source_lifecycle_binding_reason':'SOURCE_LIFECYCLE_BINDING'}.items():p.wrap(m,fn,phase)
   original=m.resolve_all_states
   def resolve(*a,**kw):return p.timed(original,'RESOLVE_FORMING_STATES' if kw.get('prefer_forming') else 'RESOLVE_CLOSED_STATES')(*a,**kw)
   m.resolve_all_states=resolve
  if name=='timeframe_manager':
   for fn,phase in {'load_feed':'LOAD_MARKET','load_sources':'LOAD_SOURCES','load_decision_identity_index':'LOAD_DECISION_LINEAGE','resolve_decision_identity':'DECISION_LINEAGE','_raw_status_blocks_new_entry':'RAW_GATE','_strength_too_weak':'STRENGTH_GATE','_anti_saw_block_entry':'ANTI_SAW_ENTRY','_anti_saw_block_context_close':'ANTI_SAW_CLOSE','_preview_context_for_open_position':'EXIT_PREVIEW'}.items():p.wrap(m,fn,phase)
   for fn,phase in {'run_cycle':'TOTAL_MANAGER_CYCLE','trader_views':'LOAD_BOOKS','_build_command':'BUILD_COMMANDS','_saw_blocks_open':'ANTI_SAW','portfolio_summary':'PORTFOLIO_SUMMARY'}.items():p.wrap(m.TimeframeManager,fn,phase)
  if name=='command_bus':
   for fn,phase in {'append':'COMMAND_BUS_WRITE','load_manager_state':'LOAD_MANAGER_STATE','save_manager_state':'SAVE_MANAGER_STATE','write_latest_snapshot':'PUBLISH_MANAGER_SNAPSHOT'}.items():p.wrap(m.CommandBus,fn,phase)
  if name=='portfolio_risk':p.wrap(m.PortfolioRiskCoordinator,'evaluate','RISK')
 sleep=time.sleep
 def wait(seconds):
  result=sleep(seconds);p.flush();return result
 time.sleep=wait
