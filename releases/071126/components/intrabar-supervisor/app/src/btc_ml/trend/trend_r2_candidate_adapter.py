"""Read-only candidate atom parsing; intentionally cannot produce qualification."""
from dataclasses import dataclass

ATOMS=frozenset(('initiative_continuation','passive_pullback','defended_absorption',
    'initiative_failure','balanced_auction','FAILED_CONTINUATION_SEQUENCE','EXHAUSTION_SEQUENCE'))
@dataclass(frozen=True)
class CandidateAtom:
    atom: str
    raw_timestamp: str | None
    source_record_identity: str | None
    status: str='NOT_QUALIFIED'
    eligibility: str='NO_ENTRY'

def parse_candidate(row):
    atom=row.get('transition_state') or row.get('sequence_type')
    if atom not in ATOMS: return None
    return CandidateAtom(atom,row.get('timestamp'),row.get('source_event_id'))
