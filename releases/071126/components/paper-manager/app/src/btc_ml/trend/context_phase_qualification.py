"""TREND_CONTEXT_PHASE_QUALIFICATION_V1: isolated M1/M3/M4 and approved opt-in M2 W1/R1.

Own context phases are never economic R2 events. The pinned archive reader below
provides RESEARCH_OBSERVED only: a snapshot hash cannot prove first publication.
No production activation, collector, journal genesis, order or numerical score.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json

import pandas as pd

VERSION = 'TREND_CONTEXT_PHASE_QUALIFICATION_V1'
MINUTES = {'M15': 15, 'M30': 30, 'H1': 60, 'H4': 240}
M2_AMENDMENT = 'TREND_CONTEXT_M2_W1_R1_APPROVED_20261018'
APPROVED_M2_EVENTS = frozenset(('INITIATIVE_WEAKEN', 'INITIATIVE_RENEW'))
UNRESOLVED_EVENTS = frozenset(('INITIATIVE_WEAKEN', 'INITIATIVE_EXHAUST', 'INITIATIVE_RENEW', 'DEFENDED_PAUSE'))


def _clean(v):
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (tuple, list)):
        return [_clean(x) for x in v]
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if hasattr(v, 'item'):
        return _clean(v.item())
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def _hash(v):
    return sha256(json.dumps(_clean(v), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _time(v):
    t = pd.Timestamp(v)
    if pd.isna(t) or t.tzinfo is None:
        raise ValueError('EXPLICIT_CAUSAL_CLOCK_REQUIRED')
    return t.tz_convert('UTC')


def _observation_fingerprint(packet):
    # Growing artifact SHA and evaluation clock are not new market observations.
    return _hash({k: v for k, v in packet.items() if k not in ('decision_as_of', 'sources')} | {
        'source_rows': {k: v['source_row_sha'] for k, v in packet['sources'].items()}})


class PinnedContextObservations:
    """Explicit archived own-TF artifacts; no default production paths/writes.

    Identity pins are supplied by the existing frozen SHA manifest. The reader
    never upgrades first_published_at, mtime or primary_context_publication.json
    (which lacks artifact hashes) into LIVE_QUALIFIED. No live proof parser is
    invented here; future live admission requires the genuine source contract.
    """
    def __init__(self, root, manifest, *, market, instrument, legacy_m15_owner=None):
        self.root = Path(root).resolve()
        self.manifest = dict(manifest)
        if not market or not instrument:
            raise ValueError('MARKET_INSTRUMENT_REQUIRED')
        self.market, self.instrument = market, instrument
        self._cache = {}
        self._legacy_frames = {}
        self._row_indices = {}
        self.legacy_m15_owner = legacy_m15_owner
        if legacy_m15_owner is not None:
            from .legacy_m15_phase_owner import LegacyM15Owner
            if type(legacy_m15_owner) is not LegacyM15Owner:
                raise TypeError('VERIFIED_LEGACY_M15_OWNER_REQUIRED')

    def _frame(self, rel):
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root) or rel not in self.manifest:
            raise ValueError('UNPINNED_CONTEXT_SOURCE')
        raw = path.read_bytes()
        fingerprint = sha256(raw).hexdigest()
        if fingerprint != self.manifest[rel]:
            raise ValueError('CONTEXT_SOURCE_SHA_MISMATCH')
        if rel not in self._cache or self._cache[rel][0] != fingerprint:
            f = pd.read_parquet(BytesIO(raw))
            f['timestamp'] = pd.to_datetime(f.timestamp, utc=True)
            self._cache[rel] = (fingerprint, f)
        return self._cache[rel][1], fingerprint

    def read(self, tf, opened, decision_as_of):
        if tf not in MINUTES:
            raise ValueError('OWN_TF_REQUIRED')
        opened, cutoff = _time(opened), _time(decision_as_of)
        if tf == 'M15' and self.legacy_m15_owner is not None:
            self.legacy_m15_owner.verify_files()  # No proof SHA check is skipped.
        closed = opened + pd.Timedelta(minutes=MINUTES[tf])
        if opened.timestamp() % (MINUTES[tf] * 60) or closed > cutoff:
            raise ValueError('FORMING_OR_FUTURE_SOURCE')
        base = 'cognition/' + ('' if tf == 'M15' else 'timeframes/' + tf + '/')
        paths = {k: base + name + '.parquet' for k, name in (
            ('auction', 'auction_episode_memory'), ('cognitive', 'cognitive_market_state_memory'),
            ('final', 'final_market_context_memory'), ('lifecycle', 'market_context_lifecycle_memory'))}
        paths['market'] = 'cognition/candle_structure_memory.parquet' if tf == 'M15' else base + 'native_closed_candles.parquet'
        rows, identities, previous_market = {}, {}, None
        for kind, rel in paths.items():
            f, artifact_sha = self._frame(rel)
            # _frame still verifies exact source bytes on EVERY read. Reuse
            # only row positions of that immutable fingerprint, never admission.
            key = (rel, tf)
            indexed = self._row_indices.get(key)
            if indexed is None or indexed[0] != artifact_sha:
                if tf == 'M15' and kind in ('final', 'cognitive') and self.legacy_m15_owner is not None:
                    prior = self._legacy_frames.get(rel)
                    if prior is None or prior[0] != artifact_sha:
                        self._legacy_frames[rel] = (artifact_sha, self.legacy_m15_owner.validate_frame(f, kind))
                    f = self._legacy_frames[rel][1]
                elif 'timeframe' in f:
                    f = f.loc[f.timeframe.astype(str) == tf]
                elif kind not in ('auction', 'market') or tf != 'M15':
                    raise ValueError('SOURCE_TF_NOT_PROVEN')
                positions = {}
                for position, stamp in enumerate(f.timestamp):
                    positions.setdefault(stamp, []).append(position)
                clocks = pd.Index(f.timestamp)
                indexed = (artifact_sha, f, positions,
                           clocks.is_unique and clocks.is_monotonic_increasing, clocks)
                self._row_indices[key] = indexed
            _, f, positions, ordered_unique, clocks = indexed
            selected = positions.get(opened, [])
            if len(selected) != 1:
                raise ValueError('EXACT_OWN_SOURCE_ROW_REQUIRED')
            row = _clean(f.iloc[selected[0]].to_dict())
            rows[kind] = row
            identities[kind] = {'path': rel, 'artifact_sha256': artifact_sha, 'source_row_sha': _hash(row)}
            for key in ('information_available_at', 'observation_available_at', 'confirmation_window_end'):
                if row.get(key) is not None and _time(row[key]) > cutoff:
                    raise ValueError('CAUSALLY_UNAVAILABLE_SOURCE')
            for key, expected in (('source_bar_open', opened), ('source_bar_close', closed)):
                if row.get(key) is not None and _time(row[key]) != expected:
                    raise ValueError('WRONG_SOURCE_BAR')
            if kind == 'market':
                if ordered_unique:
                    position = int(clocks.searchsorted(opened, side='left')) - 1
                    previous = f.iloc[position] if position >= 0 else None
                else:
                    # Preserve native sorting/tie semantics for unusual input.
                    prior = f.loc[f.timestamp < opened].sort_values('timestamp')
                    previous = prior.iloc[-1] if len(prior) else None
                if previous is not None:
                    previous_market = _clean(previous.to_dict())
                    identities['previous_market'] = {'path': rel, 'artifact_sha256': artifact_sha, 'source_row_sha': _hash(previous_market)}
        a, c, final, life = (rows[k] for k in ('auction', 'cognitive', 'final', 'lifecycle'))
        if c.get('source_episode_freshness') == 'stale' or final.get('source_state_freshness') == 'stale':
            raise ValueError('NATIVE_SOURCE_STALE')
        if life.get('raw_market_context') != final.get('market_context'):
            raise ValueError('FINAL_LIFECYCLE_CONFLICT')
        if c.get('primary_auction_episode') != a.get('auction_episode'):
            raise ValueError('AUCTION_COGNITIVE_CONFLICT')
        if any(row.get('close') != rows['market'].get('close') for row in (a, c, final, life)):
            raise ValueError('UNDERLYING_MARKET_ROW_CONFLICT')
        from btc_ml.trading.timeframe_state_adapter import _episode_id_for_timeframe
        episode = _episode_id_for_timeframe(tf, life.get('context_episode_id'))
        if not episode or ':prov:' in episode.lower():
            raise ValueError('CANONICAL_EPISODE_REQUIRED')
        direction = {'LONG_CONTEXT': 'LONG', 'SHORT_CONTEXT': 'SHORT', 'OBSERVE': 'NONE'}.get(final.get('market_context'))
        if direction is None:
            raise ValueError('CANONICAL_DIRECTION_REQUIRED')
        observed_at = max([closed] + [_time(row[key]) for row in rows.values()
                           for key in ('information_available_at', 'observation_available_at', 'confirmation_window_end')
                           if row.get(key) is not None])
        return {'market': self.market, 'instrument': self.instrument, 'timeframe': tf,
                'bar_open': opened.isoformat(), 'bar_close': closed.isoformat(),
                'final_context_episode_id': episode, 'direction': direction,
                'rows': rows, 'previous_market': previous_market, 'sources': identities,
                'source_observation_ids': [f'{self.market}:{self.instrument}:{tf}:{opened.isoformat()}'],
                'source_availability_at': observed_at.isoformat(), 'source_publication_ref': None,
                'publication_status': 'ORIGINAL_PUBLICATION_SHA_CHAIN_NOT_PROVEN',
                'qualification': 'RESEARCH_OBSERVED', 'decision_as_of': cutoff.isoformat()}


def _directional_fact(packet):
    """Exact native categorical semantics + authentic underlying price result.

    Auction/Cognitive on one candle are one observation, never multiple votes.
    A new row alone is insufficient: require native accepted price/effort,
    matching native cognitive control, and reproduce the *existing* price rule
    from that candle and its actual prior source candle (no new thresholds).
    """
    from scripts.research.build_auction_episode_memory import classify_price_result
    from scripts.research.build_cognitive_market_state_memory import classify_cognitive_market_state
    a, c, m = (packet['rows'][k] for k in ('auction', 'cognitive', 'market'))
    prior = packet['previous_market']
    if prior is None:
        return False, 'INDEPENDENT_UNDERLYING_PRICE_RESULT_NOT_PROVEN'
    native = classify_cognitive_market_state(auction_episode=a.get('auction_episode'),
        episode_status=a.get('episode_status'), effort_side=a.get('effort_side'), effort_result=a.get('effort_result'))
    if native[:2] != (c.get('cognitive_market_state'), c.get('state_direction')):
        return False, 'NATIVE_COGNITIVE_SEMANTICS_CONFLICT'
    expected, control, episodes = ('ACCEPTED_HIGHER', 'BUYER_CONTROL', ('ACCEPTANCE_HIGHER', 'CONTINUATION')) if packet['direction'] == 'LONG' else ('ACCEPTED_LOWER', 'SELLER_CONTROL', ('ACCEPTANCE_LOWER', 'CONTINUATION'))
    if a.get('episode_status') == 'INVALIDATED' or c.get('state_status') == 'INVALIDATED':
        return False, 'INVALIDATED_NATIVE_EVIDENCE'
    if a.get('auction_episode') == 'BALANCE':
        return False, 'BALANCE_HISTORICAL_PHASE_ONLY'
    if a.get('price_result') in ('ACCEPTED_HIGHER', 'ACCEPTED_LOWER') and a['price_result'] != expected:
        return False, 'CONTRADICTORY_DIRECTIONAL_EVIDENCE_NO_RESOLUTION_RULE'
    if (a.get('auction_episode') not in episodes or a.get('price_result') != expected
            or a.get('effort_result') not in ('ACCEPTED', 'CONTINUED') or c.get('state_direction') != control):
        return False, 'DIRECTIONAL_ACCEPTANCE_NOT_PROVEN_M2_UNDEFINED'
    price = classify_price_result(close=m['close'], prev_close=prior['close'],
        open_=m['open'], high=m['high'], low=m['low'], bar_event=a.get('bar_event', 'UNKNOWN'))
    if price != expected:
        return False, 'NATIVE_UNDERLYING_RESULT_NOT_REPRODUCED'
    return True, 'NATIVE_ACCEPTANCE_AND_DISTINCT_UNDERLYING_OBSERVATION'


def _m2_acceptance(packet, direction):
    """Approved A(d,o): native M1 facts plus confirmed Auction/Cognitive status.

    Direction here selects which native acceptance to check, never a new Final
    direction. The source packet, canonical scope and emitted direction are intact.
    """
    a, c, final = (packet['rows'][k] for k in ('auction', 'cognitive', 'final'))
    if a.get('episode_status') != 'CONFIRMED' or c.get('state_status') != 'CONFIRMED':
        return False, 'M2_NATIVE_ACCEPTANCE_NOT_CONFIRMED'
    own = packet['direction']
    if (final.get('market_context') != {'LONG': 'LONG_CONTEXT', 'SHORT': 'SHORT_CONTEXT'}.get(own)
            or final.get('living_process') != {'LONG': 'BUYER', 'SHORT': 'SELLER'}.get(own)):
        return False, 'M2_CANONICAL_PROCESS_NOT_RETAINED'
    if (final.get('cognitive_market_state') != c.get('cognitive_market_state')
            or final.get('state_direction') != c.get('state_direction')):
        return False, 'M2_FINAL_COGNITIVE_SOURCE_CONFLICT'
    return _directional_fact(dict(packet, direction=direction))


class ContextPhaseQualifier:
    """Isolated event producer with independent per-TF canonical lineage.

    Results/history live in research memory. Rebuilding from the same ordered
    pinned prefix is deterministic; this is not a durable production publisher.
    """
    def __init__(self, observations, *, m2_w1_r1=False):
        if type(observations) is not PinnedContextObservations:
            raise TypeError('PINNED_NATIVE_CONTEXT_OBSERVATIONS_REQUIRED')
        if type(m2_w1_r1) is not bool:
            raise TypeError("EXPLICIT_ISOLATED_M2_PROFILE_REQUIRED")
        self.m2_w1_r1 = m2_w1_r1
        self.observations = observations
        self._lines, self._heads, self._seen = {}, {}, {}
        self._conflicts = set()
        self._last_order = {}
        self._history = []

    @property
    def history(self):
        return deepcopy(self._history)

    def unresolved_event(self, event_kind):
        if self.m2_w1_r1 and event_kind in APPROVED_M2_EVENTS:
            raise ValueError('APPROVED_M2_EVENT_REQUIRES_NATIVE_PROCESS')
        if event_kind not in UNRESOLVED_EVENTS:
            raise ValueError('NOT_AN_UNRESOLVED_CONTEXT_EVENT')
        return {'event_kind': event_kind, 'status': 'NOT_PROVEN', 'reason': 'NECESSARY_SUFFICIENT_NATIVE_COMBINATION_NOT_APPROVED', 'event_emitted': False}

    def process(self, tf, opened, decision_as_of):
        try:
            p = self.observations.read(tf, opened, decision_as_of)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            result = {'context_trend_phase': 'NOT_PROVEN', 'historical_context_trend_phase': None,
                      'qualification': 'NOT_PROVEN', 'reason': str(exc), 'current_evidence': False,
                      'context_veto': 'BLOCK', 'event': None, 'timeframe': tf,
                      'decision_as_of': str(decision_as_of), 'contract_version': VERSION}
            self._heads[tf] = result
            return deepcopy(result)
        identity = (tf, p['bar_open'])
        # Artifact files may grow; event identity binds exact rows, not mutable file bytes.
        fp = _observation_fingerprint(p)
        prior_head = self._heads.get(tf)
        if identity in self._conflicts:
            return self._reject(p, 'CONFLICTING_SOURCE_IDENTITY')
        if identity in self._seen:
            previous = self._seen[identity]
            if previous['fingerprint'] == fp and prior_head and prior_head.get('bar_open') == p['bar_open'] and prior_head.get('reason') != 'CONFLICTING_SOURCE_IDENTITY':
                return deepcopy(prior_head)
            if previous['fingerprint'] != fp:
                self._conflicts.add(identity)
            reason = 'CONFLICTING_SOURCE_IDENTITY' if previous['fingerprint'] != fp else 'HISTORICAL_REPLAY_NOT_CURRENT'
            return self._reject(p, reason)
        if tf in self._last_order and _time(p['bar_open']) <= self._last_order[tf]:
            return self._reject(p, 'LATE_SOURCE_NO_REPAINT')
        scope = (tf, p['final_context_episode_id'], p['direction'])
        previous_scope = next((k for k in self._lines if k[0] == tf and not self._lines[k]['closed']), None)
        if previous_scope and previous_scope != scope:
            old = self._lines[previous_scope]
            old['closed'] = True
            if old['phase'] != 'UNKNOWN':
                event = {'event_kind': 'INITIATIVE_BREAK', 'previous_event_id': old['last_event'],
                         'closed_scope': previous_scope, 'new_scope': scope, 'source_rows': p['sources'],
                         'qualification': p['qualification'], 'decision_as_of': p['decision_as_of'], 'contract_version': VERSION}
                event['event_id'] = _hash({k: v for k, v in event.items() if k not in ('decision_as_of', 'source_rows')} | {'source_row_sha': {k: v['source_row_sha'] for k, v in p['sources'].items()}})
                old['phase'] = 'BROKEN'
                self._history.append(event)
        line = self._lines.setdefault(scope, {'phase': 'UNKNOWN', 'last_event': None, 'last_sources': [], 'last_close': None, 'closed': False})
        if line['closed']:
            return self._reject(p, 'CLOSED_CANONICAL_EPISODE_CANNOT_REOPEN')
        fact, reason = _directional_fact(p) if p['direction'] != 'NONE' else (False, 'CANONICAL_OBSERVE_NO_DIRECTIONAL_EVENT')
        if p['rows']['lifecycle'].get('lifecycle_state') == 'INVALIDATED':
            fact, reason = False, 'CANONICAL_INVALIDATION_BLOCKS_CURRENT_EVIDENCE'
            if line['phase'] not in ('UNKNOWN', 'BROKEN'):
                broken = {'event_kind': 'INITIATIVE_BREAK', 'previous_event_id': line['last_event'],
                          'closed_scope': scope, 'sources': p['sources'], 'decision_as_of': p['decision_as_of'],
                          'qualification': p['qualification'], 'contract_version': VERSION}
                broken['event_id'] = _hash({k: v for k, v in broken.items() if k not in ('decision_as_of', 'sources')} | {'source_row_sha': {k: v['source_row_sha'] for k, v in p['sources'].items()}})
                self._history.append(broken)
                line.update(phase='BROKEN', closed=True)
        previous_phase = line['phase']
        m2_transition = None
        if self.m2_w1_r1 and not line['closed'] and p['direction'] in ('LONG', 'SHORT'):
            if previous_phase in ('CONFIRMED', 'ACTIVE'):
                opposite = 'SHORT' if p['direction'] == 'LONG' else 'LONG'
                weakens, _ = _m2_acceptance(p, opposite)
                if weakens:
                    fact, reason = True, 'M2_W1_OPPOSITE_NATIVE_ACCEPTANCE_PROCESS_RETAINED'
                    m2_transition = ('INITIATIVE_WEAKEN', 'WEAKENING')
            elif previous_phase == 'WEAKENING':
                renews, renewal_reason = _m2_acceptance(p, p['direction'])
                if renews and line.get('last_weaken_event_id'):
                    fact, reason = True, 'M2_R1_NEW_OWN_ACCEPTANCE_AFTER_PROVEN_W1'
                    m2_transition = ('INITIATIVE_RENEW', 'REACTIVATING')
                else:
                    fact = False
                    if reason != 'BALANCE_HISTORICAL_PHASE_ONLY':
                        reason = ('M2_WEAKENING_OPPOSITE_ACCEPTANCE_NO_NEW_TRANSITION'
                                  if p['rows']['auction'].get('price_result') in ('ACCEPTED_HIGHER', 'ACCEPTED_LOWER')
                                  and p['rows']['auction']['price_result'] != ('ACCEPTED_HIGHER' if p['direction'] == 'LONG' else 'ACCEPTED_LOWER')
                                  else renewal_reason)
            elif previous_phase == 'REACTIVATING' and fact:
                # Original M1 predicate, on a later independent source: RENEW
                # itself cannot also confirm, and cannot jump directly to ACTIVE.
                m2_transition = ('INITIATIVE_CONFIRM', 'ACTIVE')
                reason = 'M1_INDEPENDENT_CONFIRM_AFTER_M2_RENEW'
        event = None
        if fact:
            new_sources = set(p['source_observation_ids'])
            if (m2_transition and line.get('last_source_available_at')
                    and _time(p['source_availability_at']) < _time(line['last_source_available_at'])):
                fact, reason = False, 'M2_SOURCE_AVAILABILITY_PRECEDES_PRIOR_PHASE_EVENT'
            elif new_sources.intersection(line.get('used_sources', line['last_sources'])) or (line['last_close'] and _time(p['bar_open']) < _time(line['last_close'])):
                fact, reason = False, 'INDEPENDENT_SOURCE_BOUNDARY_NOT_PROVEN'
            elif m2_transition or line['phase'] in ('UNKNOWN', 'FORMING', 'CONFIRMED', 'ACTIVE'):
                kind, phase = m2_transition or {'UNKNOWN': ('INITIATIVE_START', 'FORMING'), 'FORMING': ('INITIATIVE_CONFIRM', 'CONFIRMED'),
                               'CONFIRMED': ('INITIATIVE_CONTINUE', 'ACTIVE'), 'ACTIVE': ('INITIATIVE_CONTINUE', 'ACTIVE')}[line['phase']]
                event = {k: deepcopy(p[k]) for k in ('market', 'instrument', 'timeframe', 'bar_open', 'bar_close', 'source_observation_ids', 'sources', 'source_availability_at', 'source_publication_ref', 'decision_as_of', 'final_context_episode_id', 'direction', 'qualification')}
                event.update(event_kind=kind, previous_event_id=line['last_event'], contract_version=VERSION,
                             native_price_result=p['rows']['auction']['price_result'], native_effort_result=p['rows']['auction']['effort_result'])
                if m2_transition:
                    event['methodology_amendment'] = M2_AMENDMENT
                    event['native_process_reason'] = p['rows']['final'].get('context_reason')
                    if kind in ('INITIATIVE_RENEW', 'INITIATIVE_CONFIRM'):
                        event['weakening_event_id'] = line.get('last_weaken_event_id')
                event['event_id'] = _hash({k: v for k, v in event.items() if k not in ('decision_as_of', 'sources')} | {'source_row_sha': {k: v['source_row_sha'] for k, v in p['sources'].items()}})
                line.update(phase=phase, last_event=event['event_id'], last_sources=p['source_observation_ids'], last_close=p['bar_close'])
                if self.m2_w1_r1:
                    line['used_sources'] = list(line.get('used_sources', [])) + p['source_observation_ids']
                    line['last_source_available_at'] = p['source_availability_at']
                    if kind == 'INITIATIVE_WEAKEN':
                        line['last_weaken_event_id'] = event['event_id']
                self._history.append(deepcopy(event))
            else:
                fact, reason = False, 'CONTEXT_TRANSITION_PREDICATE_NOT_APPROVED'
        result = {'contract_version': VERSION, 'timeframe': tf, 'market': p['market'], 'instrument': p['instrument'],
                  'bar_open': p['bar_open'], 'bar_close': p['bar_close'], 'final_context_episode_id': p['final_context_episode_id'],
                  'direction': p['direction'], 'context_trend_phase': line['phase'] if fact else 'NOT_PROVEN',
                  'historical_context_trend_phase': line['phase'], 'qualification': p['qualification'],
                  'reason': reason, 'current_evidence': fact, 'event': event, 'context_veto': 'BLOCK',
                  'live_blocker': p['publication_status'], 'decision_as_of': p['decision_as_of'],
                  'source_availability_at': p['source_availability_at'], 'source_publication_ref': None,
                  'creates_r2_opportunity': False, 'grants_open': False}
        if self.m2_w1_r1:
            result['methodology_amendment'] = M2_AMENDMENT
            result['previous_context_trend_phase'] = previous_phase
        self._heads[tf] = deepcopy(result)
        self._last_order[tf] = _time(p['bar_open'])
        self._seen[identity] = {'fingerprint': fp}
        return deepcopy(result)

    def _reject(self, p, reason):
        result = {'contract_version': VERSION, 'market': p['market'], 'instrument': p['instrument'],
                  'timeframe': p['timeframe'], 'bar_open': p['bar_open'],
                  'bar_close': p['bar_close'], 'final_context_episode_id': p['final_context_episode_id'],
                  'direction': p['direction'], 'context_trend_phase': 'NOT_PROVEN',
                  'qualification': 'NOT_PROVEN', 'reason': reason, 'current_evidence': False,
                  'context_veto': 'BLOCK', 'event': None, 'decision_as_of': p['decision_as_of']}
        self._heads[p['timeframe']] = result
        return deepcopy(result)

    def read(self, tf, state, cutoff):
        r = deepcopy(self._heads.get(tf))
        if not r:
            return {'context_trend_phase': 'UNKNOWN', 'qualification': 'NOT_PROVEN', 'current_evidence': False, 'reason': 'CONTEXT_PHASE_OBSERVATION_NOT_PROCESSED', 'context_veto': 'BLOCK'}
        try:
            # Revalidate actual source bytes at consumption, not a cached ALLOW.
            current = self.observations.read(tf, r['bar_open'], cutoff)
            seen = self._seen.get((tf, r['bar_open']))
            if seen and seen['fingerprint'] != _observation_fingerprint(current):
                raise ValueError('CONFLICTING_SOURCE_IDENTITY')
        except (ValueError, TypeError, KeyError, OSError) as exc:
            r.update(context_trend_phase='NOT_PROVEN', qualification='NOT_PROVEN', current_evidence=False, reason=str(exc), context_veto='BLOCK')
            return r
        if (state.get('timeframe') != tf
                or r.get('final_context_episode_id') != state.get('lifecycle_episode_id')
                or r.get('direction') != state.get('timeframe_direction')
                or _time(r['bar_open']) != _time(state.get('source_bar_open'))
                or _time(r['bar_close']) != _time(state.get('source_bar_close'))
                or _time(r['decision_as_of']) > _time(cutoff)):
            r.update(context_trend_phase='NOT_PROVEN', qualification='NOT_PROVEN', current_evidence=False, reason='CONTEXT_PHASE_BOUNDARY_MISMATCH', context_veto='BLOCK')
        return r
