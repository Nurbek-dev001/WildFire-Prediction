"""Archive the public seven-day NRT feed and publish honest current-data readiness.

NRT observations never enter scientific training/test labels. An incomplete
365-day feature history cannot be replaced by zeros or a stale forecast.
"""
import argparse
import json
from datetime import UTC,datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from wildfire_kz import model_upgrade as mu
from wildfire_kz.data import checksum,dump_json
from wildfire_kz.data.public_predictors import download,PUBLIC,complete


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--day',default=str(datetime.now(ZoneInfo('Asia/Qyzylorda')).date()))
    args=parser.parse_args();day=pd.Timestamp(args.day,tz='UTC')
    run=mu.ROOT/'runs/daily';run.mkdir(exist_ok=True)
    mu.verify_release(mu.ROOT/'runs/model_stack_v5/release.json')
    now=datetime.now(UTC)
    raw=run/f'SNPP_NRT_{now:%Y%m%dT%H%M%S}.csv'
    url='https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Russia_Asia_7d.csv'
    cached=sorted(run.glob('SNPP_NRT_*.csv'))
    if cached and now.timestamp()-cached[-1].stat().st_mtime<3600 and complete(cached[-1]):
        raw=cached[-1]
    else:download(url,raw,timeout=90)
    source=pd.read_csv(raw,dtype={'acq_time':str,'confidence':str})
    needed={'latitude','longitude','satellite','confidence','version','acq_date','acq_time'}
    if not needed<=set(source.columns) or not source.satellite.eq('N').all():raise ValueError('Unexpected public NRT schema')
    timestamp=pd.to_datetime(source.acq_date+'T'+source.acq_time.str.zfill(4).str[:2]+':'+source.acq_time.str.zfill(4).str[2:]+':00Z',utc=True)
    first,last=timestamp.min(),timestamp.max()
    kz=source[source.latitude.between(40,56)&source.longitude.between(46,88)].copy()
    kz.to_parquet(run/f'kz_bbox_{now:%Y%m%dT%H%M%S}.parquet',index=False)
    # Public annual files cover 2025. A seven-day feed cannot fill the missing
    # earlier 2026 interval needed by the frozen 365-day history feature.
    earliest=day-pd.Timedelta(days=366);latest=day-pd.Timedelta(days=2)
    gaps=[]
    gap_start=max(earliest,pd.Timestamp('2026-01-01',tz='UTC'))
    if gap_start<first.floor('D'):
        gaps.append({'source':'365-day fire history','from':str(gap_start.date()),
                     'to':str((first.floor('D')-pd.Timedelta(days=1)).date()),
                     'reason':'No verified daily country archive; recent NRT feed alone is insufficient'})
    weather=complete(PUBLIC/f'weather/{day.year}.npz')
    cover=complete(PUBLIC/f'landcover/annual_{day.year-1}_{day.year-1}.npz')
    if not weather:gaps.append({'source':'meteorology','reason':'Current-year verified ERA5 arrays not acquired'})
    if not cover:gaps.append({'source':'landcover','reason':f'Prior-year MODIS {day.year-1} not acquired'})
    ndvi=[p for p in (PUBLIC/'vegetation').glob('????-??-??.npz')
          if day-pd.Timedelta(days=32)<=pd.Timestamp(p.stem,tz='UTC')<=day-pd.Timedelta(days=12) and complete(p)]
    if not ndvi:gaps.append({'source':'vegetation','reason':'No verified NDVI snapshot within the frozen availability and age window'})
    result={'target_day':args.day,'checked_utc':now.isoformat(),'synthetic':False,
            'status':'unavailable','forecast_available':False,'operationally_validated':False,
            'model_release_sha256':checksum(mu.ROOT/'runs/model_stack_v5/release.json'),
            'nrt_source':url,'nrt_sha256':checksum(raw),'nrt_first_observation':first.isoformat(),
            'nrt_last_observation':last.isoformat(),'bbox_observations':len(kz),
            'bbox_is_not_national_boundary_clip':True,'history_required_through':str(latest.date()),
            'gaps':gaps,'reason':'Current forecast pipeline is not commissioned; missing inputs are not imputed as zero activity.',
            'schedule_enabled':False,'nrt_used_as_test_labels':False}
    dump_json(run/'status.json',result)
    dump_json(mu.ROOT/'platform/dist/assets/daily-status.json',result)
    print(json.dumps(result))


if __name__=='__main__':main()
