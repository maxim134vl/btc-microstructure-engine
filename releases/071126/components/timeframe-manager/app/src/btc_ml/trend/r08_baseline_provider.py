"""DRAFT 300s baseline input preparation; no source or trading authority.

Call once at the prefix/initiative boundary, with the existing verified delivery
buffer from read_retained_canary. No file reads, network, history storage, or
per-event recomputation. The native consumer still verifies all source bindings.
The caller serializes the source handoff: INIT must finish before supplying the
next occurrence. Old already observed initiatives must not be relabelled new.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
import json
from .trend_evidence import RawOccurrence
from .trend_event import DUR, ordered_raw, utc
from .trend_journal import Blocked, canonical

WINDOW_SECONDS = 300
RECIPE_STATUS = 'DRAFT'


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class BaselinePreparation:
    status: str
    reason: str
    config_json: str | None = None
    t_cut: str | None = None
    method_declared_at: str | None = None
    fixed_at: str | None = None

    @property
    def config(self):
        # Never expose a mutable reference to the fixed input configuration.
        return json.loads(self.config_json) if self.config_json is not None else None


def prepare_baseline_inputs(template, capture, *, confirmed_cursor,
                            method_declared_at, clock=utc_now):
    """Prepare the four existing ResearchSystem fields from a received prefix.

    capture is the existing reader result, not a new receipt format. Its
    deliveries have already undergone native byte/pin/ACK validation upstream.
    This helper does not certify those facts and never mints a permission.
    confirmed_cursor must be the last received and dequeued native occurrence;
    it is preserved verbatim as predecessor. Its T is the half-open right edge.
    A left bracket at/before T_cursor-300s proves the observed period in the
    existing buffer. Only that bracket and the following prefix are checked.
    """
    fixed_at = clock()
    def not_ready(reason):
        return BaselinePreparation('NOT_READY', reason)
    try:
        fixed = utc(fixed_at)
        if utc(method_declared_at) > fixed:
            return not_ready('METHOD_NOT_DECLARED_BEFORE_FIXATION')
        if any(template.get(k) is not None for k in
               ('baseline', 'predecessor', 'baseline_available_at', 'policy_available_at')):
            return not_ready('EXISTING_BASELINE_CONFIG_MUST_NOT_BE_REPLACED')
        if (template.get('market') != 'BINANCE_SPOT'
                or template.get('mode') not in ('FIXTURE_ONLY', 'REAL_CANDIDATE')
                or template.get('sequence') != 'CONTIGUOUS_PLUS_ONE'):
            return not_ready('SOURCE_DOMAIN_OR_SEQUENCE')
        tfs = template.get('timeframes', [])
        if not tfs or any(tf not in DUR for tf in tfs):
            return not_ready('OWN_TF_CONTEXT_REQUIRED')
        for tf in tfs:
            own = template.get('contexts', {}).get(tf)
            if (not own or not own.get('id') or own.get('direction') not in ('LONG', 'SHORT')):
                return not_ready('OWN_TF_CONTEXT_REQUIRED')
            if utc(own['available_at']) > fixed:
                return not_ready('CONTEXT_NOT_AVAILABLE_AT_FIXATION')
        if capture['root'] != template.get('coverage_ref'):
            return not_ready('CAPTURE_ROOT_BINDING')
        # Borrow the existing bounded buffer; do not allocate another history/queue.
        deliveries = capture['deliveries']
        observed_count = len(deliveries)
        if not deliveries:
            return not_ready('INSUFFICIENT_OBSERVED_PERIOD')
        cursor_packet = RawOccurrence.from_dict(deliveries[-1]['packet'])
        if type(confirmed_cursor) is not int or cursor_packet.trade.native_id != confirmed_cursor:
            return not_ready('CURSOR_NOT_LAST_RECEIVED_OCCURRENCE')
        cut = utc(cursor_packet.trade.trade_time)
        left = cut - timedelta(seconds=WINDOW_SECONDS)
        # Search backwards only within the bounded 300s prefix plus one bracket.
        begin = len(deliveries)-1
        while begin >= 0 and utc(deliveries[begin]['packet']['trade']['trade_time']) > left:
            begin -= 1
        if begin < 0:
            return not_ready('INSUFFICIENT_OBSERVED_PERIOD')
        baseline = []
        previous = None
        previous_delivery = None
        pending = set(capture.get('pending_queue', []))
        for i in range(begin, len(deliveries)):
            delivery = deliveries[i]
            raw = RawOccurrence.from_dict(delivery['packet'])
            if utc(raw.available_at) > fixed:
                return not_ready('SOURCE_NOT_AVAILABLE_AT_FIXATION')
            raw.validate(fixed_at)
            if utc(delivery['available_by']) != utc(raw.available_at):
                return not_ready('ORIGINAL_AVAILABILITY_BINDING')
            if delivery['delivery_id'] in pending:
                return not_ready('PREFIX_NOT_CONFIRMED_DEQUEUED')
            if (raw.capture_family != template['capture_family']
                    or raw.capture_origin != template['mode']
                    or raw.trade.market != 'BINANCE_SPOT'):
                return not_ready('CAPTURE_PROVENANCE_CONFLICT')
            if previous is not None:
                if (raw.predecessor != previous.trade.native_id
                        or raw.trade.native_id != previous.trade.native_id+1):
                    return not_ready('SOURCE_GAP_UNCONFIRMED')
                local_rewind = utc(raw.available_at) < utc(previous.available_at)
                # A wall-clock adjustment is not a receive-order rewind. Live
                # callbacks carry the original ACK monotonic clock/domain.
                if 'ack_monotonic_ns' in delivery and 'ack_monotonic_ns' in previous_delivery:
                    if delivery.get('clock_domain') != previous_delivery.get('clock_domain'):
                        return not_ready('SOURCE_ORDER_UNCONFIRMED')
                    local_rewind = delivery['ack_monotonic_ns'] < previous_delivery['ack_monotonic_ns']
                if (utc(raw.trade.trade_time) < utc(previous.trade.trade_time)
                        or utc(raw.trade.exchange_event_time) < utc(previous.trade.exchange_event_time)
                        or local_rewind):
                    return not_ready('SOURCE_ORDER_UNCONFIRMED')
            at = utc(raw.trade.trade_time)
            if at > cut:
                return not_ready('SOURCE_ORDER_UNCONFIRMED')
            if left <= at < cut:
                baseline.append(raw.trade)
            previous = raw
            previous_delivery = delivery
        if len(baseline) < 2 or utc(baseline[-1].trade_time) <= utc(baseline[0].trade_time):
            return not_ready('ZERO_BASELINE_T_SPAN')
        error = ordered_raw(tuple(baseline))
        if error:
            return not_ready(error)
        if len(deliveries) != observed_count or deliveries[-1]['packet']['trade']['native_id'] != confirmed_cursor:
            return not_ready('SOURCE_ADVANCED_DURING_FIXATION')
        # Record the actual completion clock, not the earlier start of selection.
        completed_at = clock()
        if utc(completed_at) < fixed:
            return not_ready('LOCAL_CLOCK_REWIND_DURING_FIXATION')
        fixed_at = completed_at
        c = deepcopy(template)
        c.update(baseline=[asdict(t) for t in baseline], predecessor=confirmed_cursor,
                 baseline_available_at=fixed_at, policy_available_at=fixed_at)
        return BaselinePreparation('PREPARED_INPUTS_ONLY', 'NO_MARKET_OR_PAPER_AUTHORITY',
                                   canonical(c), cut.isoformat(), method_declared_at, fixed_at)
    except (Blocked, KeyError, TypeError, ValueError, AttributeError) as exc:
        return not_ready('INVALID_BASELINE_INPUT:' + str(exc))


def prepare_research_system(path, template, capture, *, confirmed_cursor,
                            method_declared_at, clock=utc_now, authority=None):
    """Immediate handoff into unchanged native INIT; never edits an existing INIT.

    Call on the existing serialized consumer path before future deliveries are
    supplied. This function does not connect the recorder or read files/captures.
    Native ResearchSystem remains responsible for all subsequent validation.
    """
    prepared = prepare_baseline_inputs(template, capture, confirmed_cursor=confirmed_cursor,
                                       method_declared_at=method_declared_at, clock=clock)
    if prepared.status != 'PREPARED_INPUTS_ONLY':
        return prepared, None
    from .trend_research_system import ResearchSystem
    count = len(capture['deliveries'])
    system = ResearchSystem(path, config=prepared.config, authority=authority)
    if (len(capture['deliveries']) != count
            or capture['deliveries'][-1]['packet']['trade']['native_id'] != confirmed_cursor):
        # Leave the native INIT intact and without market authority. Never relabel
        # already received events or rewrite its pinned config to catch up.
        raise Blocked('SOURCE_ADVANCED_DURING_INIT_NO_HANDOFF')
    return prepared, system
