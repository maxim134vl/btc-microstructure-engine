"""Explicit new live continuity domain; old history is preserved, never replayed here."""
import json, hashlib, threading, time
from decimal import Decimal
from datetime import datetime, timezone
from .execution_commit import atomic_bytes
from .execution_market_processor import normalize_futures_agg_trade

def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

class FreshLiveContinuity:
    def __init__(self, processor, consumer, domain_root):
        self.processor = processor; self.consumer = consumer
        self.path = domain_root / 'fresh_live_boundary.json'
        self.lock = threading.RLock(); self.last_bbo_exchange_ms = None
        self.engine = processor.engine; self.engine.fresh_live_contract_required = True
        self.proof = None; self.admitted = False
        if self.path.exists():
            envelope = json.loads(self.path.read_text()); raw = envelope['payload']
            if hashlib.sha256(raw.encode()).hexdigest() != envelope['sha256']:
                raise RuntimeError('FRESH_BOUNDARY_CHECKSUM_MISMATCH')
            self.proof = json.loads(raw)
            if (self.proof['paper_epoch_id'] != self.engine.epoch.paper_epoch_id
                    or self.proof['schema_version'] != 'fresh_live_continuity_v1'):
                raise RuntimeError('FRESH_BOUNDARY_IDENTITY_MISMATCH')
            self.admitted = self.proof.get('status') == 'ACTIVE'
            first = int(self.proof['first_exchange_agg_trade_id'])
            if processor.checkpoint.last_processed_agg_trade_id is None:
                # Crash after verified boundary proof, before first durable market append.
                event = normalize_futures_agg_trade(self.proof['first_ws_event'], symbol=processor.symbol,
                    connection_session_id=self.proof['connection_session_id'], receive_monotonic_ns=time.monotonic_ns(),
                    receive_timestamp=self.proof['first_received_at'])
                processor._process_agg_trade_live(event)
            elif int(processor.checkpoint.last_processed_agg_trade_id) < first:
                raise RuntimeError('FRESH_BOUNDARY_CHECKPOINT_BEFORE_ANCHOR')
        elif processor.checkpoint.last_processed_agg_trade_id is not None:
            raise RuntimeError('FRESH_BOUNDARY_CANNOT_REUSE_UNPROVEN_MARKET_DOMAIN')
        processor.fresh_live_boundary = self

    def save(self):
        raw = json.dumps(self.proof, sort_keys=True)
        atomic_bytes(self.path, json.dumps({'payload':raw, 'sha256':hashlib.sha256(raw.encode()).hexdigest()}).encode())

    def handle_market(self, payload, connection_session_id=None):
        with self.lock:
            data = payload.get('data') or payload
            if data.get('e') != 'aggTrade': return []
            if self.proof is None:
                if self.engine.positions:
                    raise RuntimeError('FRESH_INITIAL_BOUNDARY_REQUIRES_CONFIRMED_FLAT_BOOKS')
                first = int(data['a']); received = utc_now()
                # A bounded official REST tail containing the preceding event and exact WS overlap.
                rows = self.processor.fetch_agg_trades(self.processor.symbol, first-1, first)
                if [int(row['a']) for row in rows] != [first-1, first]:
                    raise RuntimeError('FRESH_REST_TAIL_NOT_CONTIGUOUS')
                overlap = rows[-1]
                for key in ('a','T','f','l','m'):
                    if overlap[key] != data[key]: raise RuntimeError('FRESH_REST_WS_MISMATCH:' + key)
                for key in ('p','q'):
                    if Decimal(str(overlap[key])) != Decimal(str(data[key])):
                        raise RuntimeError('FRESH_REST_WS_MISMATCH:' + key)
                if int(rows[0]['T']) > int(data['T']):
                    raise RuntimeError('FRESH_REST_EXCHANGE_TIME_REGRESSION')
                self.proof = {'schema_version':'fresh_live_continuity_v1','status':'VERIFIED_ANCHOR',
                    'paper_epoch_id':self.engine.epoch.paper_epoch_id,'first_exchange_agg_trade_id':first,
                    'first_exchange_trade_timestamp_ms':int(data['T']),
                    'first_exchange_event_timestamp_ms':int(data['E']), 'first_received_at':received,
                    'first_ws_event':data, 'rest_tail':rows,
                    'rest_source':'https://fapi.binance.com/fapi/v1/aggTrades',
                    'rest_verified_at':utc_now(),'connection_session_id':connection_session_id or self.processor.market_connection_session_id,
                    'historical_replay_required':False,'historical_open_quarantine_required':True}
                try:
                    self.save() # Durable proof precedes the first event; no old checkpoint is modified.
                except Exception:
                    # A failed publication must retry REST/WS verification, never
                    # skip it using an anchor that exists only in process memory.
                    self.proof = None
                    raise
            return self.processor.handle_market_ws_payload(payload, connection_session_id=connection_session_id)

    def handle_public(self, payload):
        data = payload.get('data') or payload
        self.last_bbo_exchange_ms = int(data.get('E') or 0)
        return self.processor.handle_public_ws_payload(payload)

    def entry_ready(self):
        if not self.admitted or not self.proof or self.proof.get('status') != 'ACTIVE': return False
        if not self.last_bbo_exchange_ms: return False
        age = time.time_ns()/1e6 - self.last_bbo_exchange_ms
        return 0 <= age <= self.engine.cfg.max_bbo_age_ms

    def try_activate(self):
        # Once durably admitted, no bootstrap lock is needed for health/polling.
        # In particular REST catch-up must not block the controller main loop.
        if self.admitted:
            return self.entry_ready() and self.processor.state.execution_market_ready_for_entry()
        with self.lock:
            if not self.proof: return False
            age = time.time_ns()/1e6 - (self.last_bbo_exchange_ms or 0)
            if not (0 <= age <= self.engine.cfg.max_bbo_age_ms
                    and self.processor.state.execution_market_ready_for_entry()): return False
            if not self.admitted:
                fence = self.consumer.quarantine_recovery_backlog()
                self.proof.update(status='ACTIVE', admitted_at=utc_now(), open_cutoff=fence['cutoff'],
                    admitted_agg_trade_id=self.processor.checkpoint.last_processed_agg_trade_id,
                    fresh_bbo_exchange_timestamp_ms=self.last_bbo_exchange_ms,
                    close_history_preserved=True, old_checkpoint_unchanged=True)
                self.save()
                self.admitted = True  # Only after atomic file + directory fsync succeeded.
            return True
