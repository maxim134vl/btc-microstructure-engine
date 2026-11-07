import datetime,json,pathlib,sys,time
import pandas as pd
from io_runtime import FIELDS,validate
name=sys.argv[1]
try:
 df=pd.read_parquet(name);validate(df,name)
 state=json.loads(pathlib.Path('ops/status/'+name.removesuffix('.parquet')+'.json').read_text())
 success=pd.Timestamp(state['last_success_at']).timestamp()
 assert 0 <= time.time()-success <= 120, 'publication stale'
 assert not state.get('last_error'), state.get('last_error')
 flow=pd.read_parquet('multi_exchange_flow.parquet');market=flow[flow.exchange=='BINANCE']
 assert len(market)>=21, 'real Binance warmup incomplete'
 assert 0 <= time.time()-pd.Timestamp(market.timestamp.max()).tz_localize('UTC').timestamp() <= 120, 'Binance snapshots stale'
 sources=['BINANCE']
 for source in sources:
  item=json.loads(pathlib.Path('ops/sources/'+source+'.json').read_text())
  assert item['ok'], 'source failure '+source+': '+str(item)
  assert 0 <= time.time()-pd.Timestamp(item['response_at']).timestamp() <= 120, 'source requests stale '+source
  assert item['event_max_ms'] is not None and 0 <= time.time()-item['event_max_ms']/1000 <= 120, 'underlying trades stale '+source
 print('SOURCE_READY; downstream integration checked separately',name,len(df),'Binance observations',len(market))
except Exception as e:
 print('NOT_READY',name,type(e).__name__,str(e));sys.exit(1)
