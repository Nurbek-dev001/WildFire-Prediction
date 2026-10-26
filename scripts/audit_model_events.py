"""Exact event and alert-burden audit over every published cell, with no tuning."""
import gzip
import json
import struct
from pathlib import Path

import numpy as np
import pandas as pd

from wildfire_kz import model_upgrade as mu
from wildfire_kz.data import checksum, dump_json

RUN = mu.ROOT / 'runs/model_stack_v5'
OUT = RUN / 'audit'


def main():
    mu.verify_release(RUN/'release.json')
    OUT.mkdir(exist_ok=True)
    manifest = json.loads((RUN/'site_assets/forecast-manifest.json').read_text())
    binary = (mu.ROOT/'platform/dist/assets/cells.bin').read_bytes()
    cells = list(struct.iter_unpack('<hhfffH8H',binary))
    index = pd.Index([f'g5000_{c[0]}_{c[1]}' for c in cells])
    events = pd.read_parquet(mu.OLD/'outcomes/events_through_2024.parquet')
    first = events[events.is_first & events.day.dt.year.isin([2023,2024])].copy()
    first['position'] = index.get_indexer(first.cell_id)
    first['covered'] = False; first['hit_same_day'] = False; first['hit_previous_day'] = False
    first['hit_either'] = False
    first['probability'] = np.nan
    # Alert components use eight-neighbour adjacency on the grid, same day or
    # previous day. This is a descriptive burden audit, not an ignition claim.
    parent=[]; nodes={}; matched=set(); daily=[]
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]; i=parent[i]
        return i
    histogram=np.zeros(65536,dtype='int64');positive_histogram=np.zeros(65536,dtype='int64')
    exact_tp=0;exact_positive=0;exact_rows=0
    previous = np.full(len(index),np.nan,dtype='float32')
    prior_nodes={}
    for day,proof in manifest['prediction_assets'].items():
        path=RUN/f'site_assets/predictions/{day}.f16.gz'
        if checksum(path)!=proof['payload_sha256']:
            raise ValueError('Prediction hash differs')
        raw=np.frombuffer(gzip.decompress(path.read_bytes()),dtype='uint8')
        p=np.frombuffer(raw.reshape(2,-1).T.tobytes(),dtype='<f2').astype('float32')
        alerts=np.flatnonzero(p>=manifest['threshold'])
        today={}
        for ci in alerts:
            r,c=cells[ci][:2]; node=len(parent);parent.append(node); today[(r,c)]=node
            for dr in [-1,0,1]:
                for dc in [-1,0,1]:
                    for other in [today.get((r+dr,c+dc)),prior_nodes.get((r+dr,c+dc))]:
                        if other is not None:
                            a,b=find(node),find(other);parent[max(a,b)]=min(a,b)
        ids=first.index[first.day==pd.Timestamp(day,tz='UTC')]
        pos=first.loc[ids,'position'].to_numpy();valid=pos>=0; ids=ids[valid];pos=pos[valid]
        first.loc[ids,'covered']=np.isfinite(p[pos])
        first.loc[ids,'probability']=p[pos]
        same=p[pos]>=manifest['threshold']; prior=previous[pos]>=manifest['threshold']
        positive_cells=np.unique(pos[np.isfinite(p[pos])])
        finite=p[np.isfinite(p)]
        histogram += np.bincount(finite.astype('<f2').view('<u2'),minlength=65536)
        positive_histogram += np.bincount(p[positive_cells].astype('<f2').view('<u2'),minlength=65536)
        exact_tp += int(np.sum(p[positive_cells]>=manifest['threshold']))
        exact_positive += len(positive_cells);exact_rows += len(finite)
        first.loc[ids,'hit_same_day']=same;first.loc[ids,'hit_previous_day']=prior
        first.loc[ids,'hit_either']=same|prior
        for ci in pos[same]: matched.add(today[cells[ci][:2]])
        for ci in pos[prior]: matched.add(prior_nodes[cells[ci][:2]])
        daily.append({'day':day,'eligible_cells':int(np.isfinite(p).sum()),'alert_cell_days':len(alerts),
                      'first_events':len(ids),'covered_first_events':int(np.isfinite(p[pos]).sum()),
                      'first_events_hit_same_day':int(same.sum()),'first_events_hit_prior_day':int(prior.sum())})
        previous=p;prior_nodes=today
    components={find(i) for i in range(len(parent))}; matched_components={find(i) for i in matched}
    def summary(f):
        covered=f[f.covered]
        return {'events':len(f),'covered_events':len(covered),'uncovered_events':int((~f.covered).sum()),
                'same_day_event_recall_all':float(f.hit_same_day.mean()),
                'same_day_event_recall_covered':float(covered.hit_same_day.mean()) if len(covered) else None,
                'prior_day_event_recall_all':float(f.hit_previous_day.mean()),
                'day_or_prior_event_recall_all':float(f.hit_either.mean())}
    # All decoded probabilities are float16: histogram tie groups give exact AP
    # for the entire national map without allocating 80 million row objects.
    order=np.arange(0x3c00,-1,-1);counts=histogram[order];positives=positive_histogram[order]
    cumulative=np.cumsum(counts);cumulative_positive=np.cumsum(positives)
    ap=float(np.sum(positives*np.divide(cumulative_positive,cumulative,out=np.zeros_like(cumulative,dtype=float),where=cumulative>0))/exact_positive)
    alert_count=sum(d['alert_cell_days'] for d in daily)
    pp=exact_tp/alert_count;rr=exact_tp/exact_positive
    exact={'unit':'unique eligible cell-day; exhaustive 731 national maps; no negative subsampling',
           'rows':exact_rows,'positive_cell_days':exact_positive,'tp':exact_tp,'fp':alert_count-exact_tp,
           'fn':exact_positive-exact_tp,'tn':exact_rows-exact_positive-alert_count+exact_tp,
           'precision':pp,'recall':rr,'f1':2*pp*rr/(pp+rr),'average_precision':ap,
           'sampling_weights':False,'uncertainty':'Fixed-period census; generalization uncertainty not estimated by this calculation'}
    result={'synthetic':False,'release_sha256':manifest['release_sha256'],
            'interpretation':'Retrospective satellite event audit. No verified ignition time, damage, or prospective operational validity.',
            'event_definition':'SNPP nominal/high, connected 2 km within 48 hours; first observation per component',
            'alert_cluster_definition':'8-neighbour grid cells connected on same/adjacent UTC day',
            'match_rule':'same 5 km cell on first detection day or previous UTC day; fixed threshold, no tuning',
            'all_events':summary(first),'by_year':{str(y):summary(g) for y,g in first.groupby(first.day.dt.year)},
            'cell_day_exact':exact,
            'alert_cell_days':sum(d['alert_cell_days'] for d in daily),
            'alert_components':len(components),'matched_alert_components':len(matched_components),
            'alert_component_match_fraction':len(matched_components)/len(components) if components else None,
            'false_alert_components':len(components-matched_components),
            'ci':'Not estimated for this descriptive event audit; cell-day CIs are in cluster_intervals.csv',
            'not_spatial_holdout':True}
    first.drop(columns=['position']).to_parquet(OUT/'events.parquet',index=False)
    pd.DataFrame(daily).to_csv(OUT/'daily_burden.csv',index=False)
    dump_json(OUT/'event_metrics.json',result)
    print(json.dumps(result))


if __name__=='__main__':main()
