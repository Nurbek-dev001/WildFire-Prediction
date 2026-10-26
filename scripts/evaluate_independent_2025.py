"""One registered new-year assessment; never fits or tunes any estimator."""
from __future__ import annotations
import argparse
import json
import struct
from datetime import UTC,datetime
import joblib
import numpy as np
import pandas as pd

from wildfire_kz import model_upgrade as mu
from wildfire_kz.independent import RUN, RELEASE, protocol, labels_gate, feature_frame,write_table,download_labels
from wildfire_kz.data import checksum,dump_json
from wildfire_kz.data.adapters import firms_csv
from wildfire_kz.data.public_predictors import geography,download,complete,PUBLIC,log
from wildfire_kz.data import public_study as study
from wildfire_kz.events import link_events
from wildfire_kz.evaluation import metrics,cluster_draws

MODEL = mu.ROOT/'runs/model_stack_v5'


def outcomes():
    labels_gate()
    path=RUN/'events.parquet'
    if path.exists():
        proof=json.loads(path.with_suffix('.sha256.json').read_text())
        if checksum(path)!=proof['sha256']:raise ValueError('Independent labels changed')
        return pd.read_parquet(path)
    raw=RUN/'viirs-snpp_2025_Kazakhstan.csv'
    url='https://firms.modaps.eosdis.nasa.gov/data/country/viirs-snpp_2025_Kazakhstan.csv'
    download_labels(url,raw)
    dump_json(RUN/'label_access.json',{'first_access_utc':datetime.now(UTC).isoformat(),
        'url':url,'raw_sha256':checksum(raw),'protocol_sha256':checksum(RUN/'protocol.json'),
        'adapter_gate_sha256':checksum(RUN/'adapter_gate.json')})
    grid=geography()[0]
    normalized=firms_csv(raw,grid,standard_processed=True)
    if not normalized.year.eq(2025).all():raise ValueError('Unexpected acquisition year')
    write_table(RUN/'detections_2025.parquet',normalized,{'raw_sha256':checksum(raw)})
    previous=pd.read_parquet(mu.ROOT/'data/real/normalized/detections_2024.parquet')
    linked=link_events(pd.concat([previous,normalized],ignore_index=True))
    write_table(path,linked,{'protocol_sha256':checksum(RUN/'protocol.json'),'raw_sha256':checksum(raw)})
    return linked


def predict():
    p=protocol();labels_gate()
    # Fail before outcome access if the mandatory predictor acquisition is incomplete.
    if not complete(PUBLIC/'weather/2025.npz') or not complete(PUBLIC/'landcover/annual_2024_2024.npz'):
        raise FileNotFoundError('Weather or cover acquisition incomplete; independent labels remain sealed')
    for day in pd.date_range('2014-11-01','2025-12-31',freq='7D'):
        if day.year==2025:
            path=PUBLIC/f'vegetation/{day:%Y-%m-%d}.npz'
            if not complete(path) and not path.with_suffix('.unavailable.json').exists():
                raise FileNotFoundError('NDVI acquisition incomplete; independent labels remain sealed')
    sources=[PUBLIC/'weather/2024.npz',PUBLIC/'weather/2025.npz',PUBLIC/'landcover/annual_2024_2024.npz',PUBLIC/'terrain/national.npz',PUBLIC/'human/national.npz']
    sources += [p for p in (PUBLIC/'vegetation').glob('????-??-??.npz') if '2024-12-01'<=p.stem<='2025-12-31']
    dump_json(RUN/'predictor_registry.json',{'protocol_sha256':checksum(RUN/'protocol.json'),
        'sources':{str(path.relative_to(mu.ROOT)):checksum(path) for path in sources}})
    detections=outcomes()
    grid=geography()[0];ids=pd.Index(grid.cell_id);n=len(ids)
    rows=list(struct.iter_unpack('<hhfffH8H',(mu.ROOT/'platform/dist/assets/cells.bin').read_bytes()))
    regions=pd.Series({f'g5000_{r[0]}_{r[1]}':r[5] for r in rows})
    region=regions.reindex(ids).to_numpy()
    cover=study.cover_year(2024,RELEASE)
    fractions=np.stack([cover[k] for k in study.COVER]);valid=np.isfinite(fractions).all(axis=0)
    with np.load(PUBLIC/'terrain/national.npz') as terrain: valid &= np.isfinite(terrain['elevation'])
    valid &= ~ids.isin(json.loads((mu.OLD/'industrial_cells.json').read_text())['cell_ids'])
    base=joblib.load(MODEL/'model.joblib');cal=joblib.load(MODEL/'calibrator.joblib')
    baseline_cal=joblib.load(mu.OLD/'calibrators.joblib')['xgboost']
    normalized_path=RUN/'detections_2025.parquet'
    normalized_proof=json.loads(normalized_path.with_suffix('.sha256.json').read_text())
    if checksum(normalized_path)!=normalized_proof['sha256']:raise ValueError('Raw history source changed')
    # The frozen history uses all raw confidence categories, while event labels
    # and past-48h eligibility use nominal/high only. Preserve that distinction.
    raw_history=pd.read_parquet(normalized_path,columns=['cell_id','timestamp'])
    raw_history['day']=raw_history.timestamp.dt.floor('D')
    history_data=pd.concat([mu.load_history(2024,MODEL/'release.json'),
        raw_history[['cell_id','day']]],ignore_index=True).drop_duplicates()
    history=mu.FireHistory(history_data)
    rng=np.random.default_rng(20250401)
    first=detections[detections.is_first].groupby('day').cell_id.apply(set).to_dict()
    recent_by_day=detections.groupby('day').cell_id.apply(set).to_dict()
    audit=[];(RUN/'months').mkdir(exist_ok=True)
    for month in range(1,13):
        target=RUN/f'months/{month:02}.parquet';keys=[]
        for day in pd.date_range(f'2025-{month:02}-01',periods=pd.Period(f'2025-{month:02}').days_in_month,tz='UTC'):
            recent=recent_by_day.get(day-pd.Timedelta(days=1),set())|recent_by_day.get(day-pd.Timedelta(days=2),set())
            eligible=valid&~ids.isin(recent);positive=ids.isin(first.get(day,set()))&eligible
            for r in sorted(set(region)):
                neg=np.flatnonzero(eligible&~positive&(region==r));pos=np.flatnonzero(positive&(region==r))
                count=min(300,len(neg));q=count/len(neg) if len(neg) else 1
                sampled=rng.choice(neg,count,replace=False)
                for ci,label,prob in [(pos,1,1.),(sampled,0,q)]:
                    if len(ci):keys.append(pd.DataFrame({'cell_index':ci,'day':day,'label':label,'q':prob,'weight':1/prob,'region':r}))
                audit.append({'day':str(day.date()),'region':int(r),'positive':len(pos),'negative_population':len(neg),'sampled_negatives':count,'q':q})
        # Advance the seeded sampling even when resuming; cached output must match the protocol.
        if target.exists():
            proof=json.loads(target.with_suffix('.sha256.json').read_text())
            if checksum(target)!=proof['sha256']:raise ValueError('Cached independent predictions changed')
            log(f'2025 month {month}: verified prediction cache');continue
        frame=feature_frame(pd.concat(keys,ignore_index=True),RELEASE)
        frame=mu.augment(frame,history,MODEL/'release.json')
        missing=~frame.required_features_valid
        missing_positives=int(frame.loc[missing,'label'].sum())
        log(f'2025 month {month}: {len(frame)} sampled rows; {int(missing.sum())} mandatory gaps')
        frame=frame[~missing].copy()
        score=base['estimator'].predict_proba(frame[base['features']])[:,1]
        frame['probability']=mu.published_probability(cal.predict(score))
        frame['baseline_probability']=baseline_cal.predict(base['estimator'].baseline.predict(frame)).astype('float32')
        keep=['cell_id','day','label','weight','q','x','y_coord','region','ndvi_missing','probability','baseline_probability']
        write_table(target,frame[keep],{'protocol_sha256':checksum(RUN/'protocol.json'),
            'excluded_required_source_rows':int(missing.sum()),'excluded_required_source_positives':missing_positives})
    pd.DataFrame(audit).to_csv(RUN/'sampling.csv',index=False)
    frame=pd.concat([pd.read_parquet(RUN/f'months/{m:02}.parquet') for m in range(1,13)],ignore_index=True)
    write_table(RUN/'predictions.parquet',frame,{'protocol_sha256':checksum(RUN/'protocol.json')})
    evaluate(frame,p)


def evaluate(frame,p):
    if (RUN/'evaluation.json').exists():raise FileExistsError('Independent evaluation already completed; do not retune')
    y=frame.label.to_numpy();score=frame.probability.to_numpy();w=frame.weight.to_numpy()
    reference=np.full(len(frame),json.loads((MODEL/'frozen.json').read_text())['original_2022_metrics']['prevalence'])
    overall=metrics(y,score,w,p['threshold'],reference)
    baseline_threshold=json.loads((mu.OLD/'frozen.json').read_text())['thresholds']['xgboost']
    baseline_score=frame.baseline_probability.to_numpy()
    baseline_metrics=metrics(y,baseline_score,w,baseline_threshold,reference)
    rows=[]
    for field,groups in [('region',frame.region),('month',frame.day.dt.month),('ndvi_missing',frame.ndvi_missing)]:
        for key,indices in groups.groupby(groups).groups.items():
            take=frame.index.get_indexer(indices)
            rows.append({'group':field,'value':str(key),'rows':len(take),**metrics(y[take],score[take],w[take],p['threshold'],reference[take])})
    pd.DataFrame(rows).to_csv(RUN/'subgroups.csv',index=False)
    draws=cluster_draws(frame,1000,100000,30,42)
    codes=draws.codes;pred=score>=p['threshold']
    tp=draws.multiplicities@np.bincount(codes,weights=w*y*pred)
    fp=draws.multiplicities@np.bincount(codes,weights=w*(1-y)*pred)
    positives=draws.multiplicities@np.bincount(codes,weights=w*y)
    ci={}
    for name,values in [('precision',tp/np.maximum(tp+fp,1)),('recall',tp/np.maximum(positives,1))]:
        ci[name]=[float(v) for v in np.quantile(values,[.025,.975])]
    baseline_pred=baseline_score>=baseline_threshold
    baseline_tp=draws.multiplicities@np.bincount(codes,weights=w*y*baseline_pred)
    baseline_fp=draws.multiplicities@np.bincount(codes,weights=w*(1-y)*baseline_pred)
    differences={}
    for name,a,b in [('precision',tp/np.maximum(tp+fp,1),baseline_tp/np.maximum(baseline_tp+baseline_fp,1)),
                     ('recall',tp/np.maximum(positives,1),baseline_tp/np.maximum(positives,1))]:
        differences[name]=[float(v) for v in np.quantile(a-b,[.025,.975])]
    dump_json(RUN/'evaluation.json',{'synthetic':False,'year':2025,'protocol_sha256':checksum(RUN/'protocol.json'),
        'release_sha256':p['model_release_sha256'],'threshold':p['threshold'],'training_max_year':2022,
        'model_updated_after_test':False,'metrics':overall,'confidence_intervals_95':ci,
        'baseline_metrics':baseline_metrics,'baseline_threshold':baseline_threshold,
        'paired_difference_intervals_95':differences,'baseline_is_predeclared_secondary':True,
        'spatial_holdout':False,'prospective_operational_trial':False,
        'outputs':{name:checksum(RUN/name) for name in ['predictions.parquet','subgroups.csv','sampling.csv']}})
    print(json.dumps(overall),flush=True)


if __name__=='__main__':
    predict()
