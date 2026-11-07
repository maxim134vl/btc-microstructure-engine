"""Exact approved configuration guard; no changes to execution methodology."""
from pathlib import Path
import hashlib, json, os, subprocess, sys
CONFIG_PATH=Path('/app/config/intrabar_paper_execution.qualified-anti-saw.json')
EXPECTED_SHA256='2dea2baf031a63e5cb3a23c0206478b4c08e76a19c00ad672491506a04457f57'
EXPECTED_ANTI_SAW={'enabled': True, 'mode': 'enforce', 'window_bars': {'M15': 8, 'M30': 8, 'H1': 6, 'H4': 4}, 'balance_support_enter': 0.55, 'balance_max_net_disp_ratio': 0.4, 'min_path_atr': 2.0, 'min_failed_breakouts': 1, 'min_bars': 3, 'volume_two_sided_enter': 0.55, 'auction_balance_share': 0.5, 'candle_structure_path': 'data/cognition/candle_structure_memory.parquet', 'auction_path': 'data/cognition/auction_episode_memory.parquet'}

def verify_effective_config(path=CONFIG_PATH):
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=EXPECTED_SHA256:
        raise RuntimeError('QUALIFIED_PAPER_CONFIG_SHA_MISMATCH')
    config=json.loads(raw)
    if config.get('anti_saw_path_density')!=EXPECTED_ANTI_SAW or config['anti_saw_path_density'].get('enabled') is not True:
        raise RuntimeError('QUALIFIED_ANTI_SAW_CONTRACT_MISMATCH')
    return config

def main():
    verify_effective_config()
    if len(sys.argv)!=2:
        raise RuntimeError('EXPLICIT_FRESH_LIVE_DOMAIN_REQUIRED')
    subprocess.run([sys.executable,'/app/deploy/vps/entrypoints/paper_only_guard.py'],check=True)
    os.execv(sys.executable,[sys.executable,'/app/scripts/live/run_intrabar_paper_manager.py','--config',str(CONFIG_PATH),'--poll-ms',os.environ.get('PAPER_POLL_MS','250'),'--health-every-s',os.environ.get('PAPER_HEALTH_EVERY_S','2.0'),'--fresh-live-domain',sys.argv[1]])

if __name__=='__main__': main()
