"""Research entrypoint enforces network OFF, including explicit opt-in attempts."""
import argparse,json
from .common import VERSION

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--network',action='store_true');a=p.parse_args(argv)
    if a.network:p.error('NETWORK_ACTIVATION_DISABLED: this research entrypoint cannot activate transport')
    print(json.dumps({'version':VERSION,'network_activation':'DISABLED','mode':'OFFLINE_LIBRARY_ONLY','production_integration':'NO','real_source_qualification':'NOT_PROVEN','real_initiative_qualifier':'NOT_QUALIFIED / NO_ENTRY'}))
    return 0
if __name__=='__main__':raise SystemExit(main())
