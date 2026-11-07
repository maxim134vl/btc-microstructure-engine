import os,sys
if os.environ.get('BTCML_PERF_PROFILE')=='1' and sys.argv and sys.argv[0].endswith('timeframe_manager_daemon.py'):
 import controller_perf
 controller_perf.install()
