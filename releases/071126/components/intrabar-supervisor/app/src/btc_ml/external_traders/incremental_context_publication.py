"""Publish a completed own-TF generation; shared lifecycle is activation authority.

The existing daemon lock remains the single writer lock. Readers do not need it:
all dependencies precede one atomic replacement of the shared lifecycle file.
"""
from pathlib import Path
from datetime import datetime, timezone
import os, tempfile
import pandas as pd

TF_ORDER=("M15","M30","H1","H4")
def atomic(frame,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,suffix=".parquet",delete=False) as f:tmp=Path(f.name)
    try:
        frame.to_parquet(tmp,index=False)
        with tmp.open("rb") as f:os.fsync(f.fileno())
        os.replace(tmp,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:tmp.unlink(missing_ok=True)

def merge_scope(old,new,tf,immutable=False):
    new=new.copy()
    if "timeframe" not in new or set(new.timeframe.astype(str))!={tf}:raise RuntimeError("PUBLICATION_OWNER_LOST:"+tf)
    parts=[]
    for owner in TF_ORDER:
        previous=None if old is None else old.loc[old.timeframe.astype(str)==owner].copy()
        current=new if owner==tf else previous
        if current is None:continue
        if owner==tf and immutable and previous is not None and len(previous):
            # Preserve published representation and IDs, validate the old prefix.
            current=current.reindex(columns=list(dict.fromkeys(list(previous.columns)+list(current.columns)))).copy();current["timestamp"]=pd.to_datetime(current.timestamp,utc=True)
            previous["timestamp"]=pd.to_datetime(previous.timestamp,utc=True)
            retained=current.loc[current.timestamp.isin(previous.timestamp)].copy()
            for column in previous:
                if pd.api.types.is_datetime64_any_dtype(previous[column].dtype):
                    retained[column]=pd.to_datetime(retained[column],utc=isinstance(previous[column].dtype,pd.DatetimeTZDtype)).astype(previous[column].dtype)
            common=list(previous.columns)
            pd.testing.assert_frame_equal(previous[common].reset_index(drop=True),retained[common].reset_index(drop=True),check_dtype=False,check_exact=True)
            current=pd.concat([previous,current.loc[current.timestamp>previous.timestamp.max()]],ignore_index=True,sort=False)
        parts.append(current)
    out=pd.concat(parts,ignore_index=True,sort=False)
    if immutable:
        if out.timeframe.isna().any() or out.timestamp.isna().any() or out.duplicated(["timeframe","timestamp"]).any():raise RuntimeError("PUBLICATION_INVALID_KEYS")
        # Match the existing M15-first batch normalization.
        m15=next((x for x in parts if len(x) and str(x.timeframe.iloc[0])=="M15"),None)
        if m15 is not None:
            for col in m15:
                if isinstance(m15[col].dtype,pd.DatetimeTZDtype):out[col]=pd.to_datetime(out[col],utc=True).astype(m15[col].dtype)
    return out

def publish_completed(root,stage,tf,lifecycle,episodes,artifacts):
    root,stage=Path(root),Path(stage)
    life_path=root/"data/cognition/market_context_lifecycle_memory.parquet"
    old=pd.read_parquet(life_path) if life_path.exists() else None
    combined=merge_scope(old,lifecycle,tf,immutable=True)
    ep_path=root/"data/cognition/market_context_lifecycle_episodes.parquet"
    old_ep=pd.read_parquet(ep_path) if ep_path.exists() else None
    combined_ep=merge_scope(old_ep,episodes,tf)
    # Full validation above occurs before publishing any dependency.
    for rel in artifacts:
        src=stage/rel;dest=root/rel
        if not dest.exists() or src.read_bytes()!=dest.read_bytes():atomic(pd.read_parquet(src),dest)
    atomic(combined_ep,ep_path)
    atomic(combined,life_path)  # The sole trading activation point, always last.
    return {"timeframe":tf,"published_at":datetime.now(timezone.utc).isoformat(),"source_bar_open":str(lifecycle.timestamp.max()),"rows":len(lifecycle)}
