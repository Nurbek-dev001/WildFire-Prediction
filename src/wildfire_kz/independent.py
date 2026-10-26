"""Forward extension of frozen feature equations; no change to sealed study code."""
from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from types import FunctionType

import numpy as np
import pandas as pd

from wildfire_kz import model_upgrade as mu
from wildfire_kz import stacked_model
from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data import public_study as study
from wildfire_kz.data.public_predictors import PUBLIC, complete, geography

RUN = mu.ROOT / 'runs/independent_2025'
RELEASE = mu.OLD / 'release.json'


def protocol() -> dict:
    path = RUN / 'protocol.json'
    proof = json.loads((RUN / 'protocol.sha256.json').read_text())
    if checksum(path) != proof['sha256']:
        raise PermissionError('Independent protocol changed')
    p = json.loads(path.read_text())
    release=mu.verify_release(mu.ROOT / 'runs/model_stack_v5/release.json')
    if checksum(Path(stacked_model.__file__)) != release['model_code_sha256']:
        raise PermissionError('Frozen model inference code changed')
    if checksum(mu.ROOT / 'runs/model_stack_v5/release.json') != p['model_release_sha256']:
        raise PermissionError('Independent model changed')
    return p


@lru_cache(maxsize=8)
def checked_years(years: tuple[int, ...], release: Path | None) -> None:
    study.permitted(list(years), release)


def cached_guard(years: list[int], release: Path | None = None) -> None:
    checked_years(tuple(years), release)


def vegetation_features(indices, dates, release=None):
    """Identical original equations, with the weekly calendar extended to target year."""
    cached_guard(sorted(set(dates.year)), release)
    ncell = len(geography()[0])
    value = np.full(ncell, np.nan, dtype='float32')
    observation = np.full(ncell, -100000, dtype='int32')
    result = np.full(len(indices), np.nan, dtype='float32')
    age = np.full(len(indices), np.nan, dtype='float32')
    first, last = dates.min() - pd.Timedelta(days=32), dates.max() - pd.Timedelta(days=12)
    records = sorted(p for p in (PUBLIC / 'vegetation').glob('????-??-??.npz')
                     if first <= pd.Timestamp(p.stem, tz='UTC') <= last)
    expected = [d for d in pd.date_range('2014-11-01',f'{dates.max().year}-12-31',freq='7D',tz='UTC')
                if first <= d <= last]
    missing = [str(d.date()) for d in expected if not complete(PUBLIC / f'vegetation/{d:%Y-%m-%d}.npz')
               and not (PUBLIC / f'vegetation/{d:%Y-%m-%d}.unavailable.json').is_file()]
    if missing:
        raise FileNotFoundError(f'NDVI acquisition incomplete: {missing[:3]}')
    cursor = 0
    for day in sorted(dates.unique()):
        while cursor < len(records) and pd.Timestamp(records[cursor].stem,tz='UTC') <= day-pd.Timedelta(days=12):
            path = records[cursor]
            if not complete(path):
                raise ValueError(f'NDVI checksum mismatch: {path}')
            with np.load(path) as data:
                a = data['ndvi']; valid = np.isfinite(a)
                value[valid] = a[valid]
                observation[valid] = int(pd.Timestamp(path.stem,tz='UTC').value//86400000000000)
            cursor += 1
        selected = np.flatnonzero(dates == day); ci = indices[selected]
        elapsed = int(day.value//86400000000000)-observation[ci]
        fresh = elapsed <= 32
        result[selected[fresh]] = value[ci[fresh]]; age[selected[fresh]] = elapsed[fresh]
    return {'ndvi':result,'ndvi_missing':(~np.isfinite(result)).astype('float32'),'ndvi_age_days':age}


def feature_frame(keys, release=RELEASE):
    # Private globals preserve the exact frozen function bytecode without mutating
    # the original module or weakening its release checks.
    env = dict(study.__dict__)
    env.update(permitted=cached_guard, vegetation_features=vegetation_features)
    env['meteorology'] = FunctionType(study.meteorology.__code__,env,'meteorology',study.meteorology.__defaults__)
    adapted = FunctionType(study.feature_frame.__code__,env,'feature_frame',study.feature_frame.__defaults__)
    return adapted(keys,release)


def verify_adapter() -> None:
    protocol()
    checks = []
    for date in ['2022-01-16','2022-06-16','2022-12-16']:
        keys = pd.DataFrame({'cell_index':np.arange(0,len(geography()[0]),307,dtype='int32'),
                             'day':pd.Timestamp(date,tz='UTC')})
        old = study.feature_frame(keys,RELEASE)
        new = feature_frame(keys,RELEASE)
        pd.testing.assert_frame_equal(old,new,check_exact=True)
        checks.append({'date':date,'rows':len(keys),'all_columns_exact':True})
    dump_json(RUN/'adapter_gate.json',{'protocol_sha256':checksum(RUN/'protocol.json'),
        'adapter_sha256':checksum(Path(__file__)),'checks':checks,'passed':True,'labels_2025_accessed':False})


def labels_gate() -> None:
    protocol()
    gate=json.loads((RUN/'adapter_gate.json').read_text())
    if not gate['passed'] or gate['adapter_sha256'] != checksum(Path(__file__)) or gate['protocol_sha256'] != checksum(RUN/'protocol.json'):
        raise PermissionError('Compatibility gate must precede independent labels')
    versions=list(RUN.glob('implementation_frozen_v*.json'))
    implementation_path=max(versions,key=lambda p:int(p.stem.rsplit('_v',1)[1])) if versions else RUN/'implementation_frozen.json'
    implementation=json.loads(implementation_path.read_text())
    if (RUN/'label_access.json').exists():
        opened=json.loads((RUN/'label_access.json').read_text())['first_access_utc']
        if implementation['created_utc']>=opened:raise PermissionError('Implementation revision occurred after independent label access')
    for path,digest in implementation['code_sha256'].items():
        if checksum(mu.ROOT/path)!=digest:raise PermissionError(f'Frozen independent implementation changed: {path}')


def write_table(path,frame,metadata):
    """Bounded new-study output; preserves 2 GiB without changing legacy guards."""
    if shutil.disk_usage(mu.ROOT).free<2*1024**3:
        raise OSError('Independent evaluation preserves a 2 GiB disk reserve')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.working')
    frame.to_parquet(temporary,index=False)
    if temporary.stat().st_size>128*1024**2:raise OSError('Independent monthly output exceeds 128 MiB budget')
    temporary.replace(path)
    dump_json(path.with_suffix('.sha256.json'),{'sha256':checksum(path),**metadata})


def download_labels(url,path):
    if complete(path):return
    if shutil.disk_usage(mu.ROOT).free<2*1024**3+12*1024**2:
        raise OSError('Independent archive preserves a 2 GiB disk reserve')
    temporary=path.with_suffix('.working')
    subprocess.run(['curl.exe','--fail','--silent','--show-error','--max-time','90',url,'--output',str(temporary)],check=True)
    if not 0<temporary.stat().st_size<=12*1024**2:raise ValueError('Independent country archive exceeds declared budget')
    temporary.replace(path)
    dump_json(path.with_name(path.name+'.sha256.json'),{'sha256':checksum(path),'url':url,'bytes':path.stat().st_size})
