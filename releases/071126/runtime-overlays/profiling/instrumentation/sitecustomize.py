# No instrumentation in health checks, guards, launcher or disabled mode.
import os,sys
if os.environ.get('BTCML_PERF_PROFILE')=='1' and (sys.argv[0].endswith('run_intrabar_paper_manager.py') or sys.argv[0].endswith('run_profiled.py')):
 import btcml_perf
 btcml_perf.install()
