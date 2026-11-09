"""Feed-owner recovery index. Derived from persisted rows, never a Candle permission.

The existing Feed writer/lock remains the only writer of market rows. The index
remembers holes independently of the largest received open time. No new worker.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
from urllib.parse import urlencode
from urllib.request import urlopen

STEP_MS = 900_000
BASE_URL = 'https://data-api.binance.vision'
SCHEMA = 'FEED_GAP_RECOVERY_V1'


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.feed-recovery-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def _merge(ranges, step):
    out = []
    for lo, hi in sorted(ranges):
        if out and lo <= out[-1][1] + step:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


class FeedRecovery:
    def __init__(self, path, symbol='BTCUSDT', step_ms=STEP_MS):
        self.path = Path(path)
        self.symbol, self.step = symbol.upper(), step_ms
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            'schema': SCHEMA, 'symbol': self.symbol, 'interval_ms': self.step,
            'scope': 'PERSISTED_FEED_ROWS_NOT_CANONICAL_COMMIT',
            'anchor_open_ms': None, 'contiguous_open_ms': None,
            'max_received_open_ms': None, 'missing_ranges': [],
        }
        if (self.state.get('schema'), self.state.get('symbol'), self.state.get('interval_ms')) != (SCHEMA, self.symbol, self.step):
            raise RuntimeError('FEED_RECOVERY_STATE_DOMAIN')

    def reconcile(self, opens):
        """Reconcile after successful Feed persistence or restart; no invented bars."""
        times = sorted(int(x) for x in opens)
        if len(times) != len(set(times)) or any(x % self.step for x in times):
            raise RuntimeError('FEED_RECOVERY_TIMESTAMP_GRID_OR_DUPLICATE')
        previous = self.state['max_received_open_ms']
        if previous is not None and (not times or times[-1] < previous):
            raise RuntimeError('FEED_RECOVERY_SOURCE_REGRESSION')
        if not times:
            return
        # Keep unresolved holes even if the rolling Feed subsequently trims them.
        ranges = [list(x) for x in self.state['missing_ranges']]
        ranges += [[a+self.step, b-self.step] for a,b in zip(times,times[1:]) if b-a>self.step]
        holes = []
        for lo, hi in _merge(ranges, self.step):
            cursor = lo
            for present in times[bisect_left(times,lo):bisect_right(times,hi)]:
                if present > cursor: holes.append([cursor,present-self.step])
                cursor = present+self.step
            if cursor <= hi: holes.append([cursor,hi])
        maximum = times[-1]
        contiguous = holes[0][0]-self.step if holes else maximum
        old_contiguous = self.state['contiguous_open_ms']
        if old_contiguous is not None and contiguous < old_contiguous:
            raise RuntimeError('FEED_RECOVERY_CONTIGUOUS_PREFIX_LOST')
        value = dict(self.state, anchor_open_ms=self.state['anchor_open_ms'] if self.state['anchor_open_ms'] is not None else times[0],
                     contiguous_open_ms=contiguous, max_received_open_ms=maximum,
                     missing_ranges=holes)
        if value != self.state or not self.path.exists():
            _atomic_json(self.path, value)
            self.state = value

    def next_request(self, now_ms, limit=1000):
        # Planning uses the existing UTC cutoff convention. Receipt Date below
        # independently excludes any not-yet-closed REST row from insertion.
        last_closed_open = (int(now_ms)//self.step-1)*self.step
        if self.state['missing_ranges']:
            lo, hi = self.state['missing_ranges'][0]
        elif self.state['max_received_open_ms'] is not None:
            lo, hi = self.state['max_received_open_ms']+self.step, last_closed_open
        else:
            return None  # No historical bootstrap/replay when no existing Feed.
        hi = min(hi,last_closed_open,lo+(limit-1)*self.step)
        return (lo,hi) if lo<=hi else None

    def attempted(self, bounds, error=None, source=None):
        value = dict(self.state, last_request={
            'start_open_ms':bounds[0], 'end_open_ms':bounds[1],
            'at':datetime.now(timezone.utc).isoformat(),
            'error':str(error)[:400] if error is not None else None,
            'source':source,
        })
        _atomic_json(self.path,value)
        self.state=value


def decode_closed_rows(rows, bounds, as_of_ms, step_ms=STEP_MS):
    """Validate the official REST wire format; no interpolation or rescaling."""
    decoded=[]; seen=set()
    for row in rows:
        if not isinstance(row,list) or len(row)<12:
            raise ValueError('FEED_REST_KLINE_FORMAT')
        opened, closed = int(row[0]), int(row[6])
        if opened % step_ms or closed != opened+step_ms-1:
            raise ValueError('FEED_REST_KLINE_BOUNDARY')
        if not bounds[0]<=opened<=bounds[1] or opened in seen:
            raise ValueError('FEED_REST_KLINE_RANGE_OR_DUPLICATE')
        seen.add(opened)
        if closed >= as_of_ms:
            continue
        o,h,l,c,v,b = [Decimal(str(row[i])) for i in (1,2,3,4,5,9)]
        if (not all(x.is_finite() for x in (o,h,l,c,v,b)) or
                not (0<l<=min(o,c)<=max(o,c)<=h) or not (0<=b<=v)):
            raise ValueError('FEED_REST_KLINE_VALUES')
        decoded.append({'open_ms':opened,'open':float(o),'high':float(h),
            'low':float(l),'close':float(c),'volume':float(v),'taker_buy_volume':float(b)})
    return sorted(decoded,key=lambda r:r['open_ms'])


def fetch_closed_rows(symbol, interval, bounds, timeout_s=20):
    """One documented Binance public-data host, verified TLS, no mirror fallback.

    HTTP 451/403 and TLS errors propagate and leave the pending gap intact.
    """
    count=(bounds[1]-bounds[0])//STEP_MS+1
    if interval!='15m' or not 1<=count<=1000:
        raise ValueError('FEED_RECOVERY_REQUEST_DOMAIN')
    url=BASE_URL+'/api/v3/klines?'+urlencode(dict(symbol=symbol.upper(),interval=interval,
        startTime=bounds[0],endTime=bounds[1]+STEP_MS-1,limit=count))
    with urlopen(url,timeout=timeout_s,context=ssl.create_default_context()) as response:
        if response.geturl()!=url:
            raise ValueError('FEED_REST_REDIRECT_NOT_ALLOWED')
        raw=response.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError('FEED_REST_RESPONSE_SIZE')
        date=response.headers.get('Date')
        if not date: raise ValueError('FEED_REST_DATE_MISSING')
    stamp=parsedate_to_datetime(date)
    if stamp.tzinfo is None: raise ValueError('FEED_REST_DATE_TIMEZONE')
    source={'url':url,'response_date':date,'response_sha256':hashlib.sha256(raw).hexdigest()}
    return decode_closed_rows(json.loads(raw),bounds,int(stamp.timestamp()*1000)),source
