"""Two fixed feature-rich challengers; selection uses 2021/2022 only."""
import gc
import json
from datetime import UTC,datetime
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score
from threadpoolctl import threadpool_limits
from wildfire_kz import model_upgrade as mu
from wildfire_kz.data import checksum,dump_json

OUT=mu.ROOT/'runs/hist_challengers_v6';OUT.mkdir(exist_ok=True)
features=mu.ALL_FEATURES
specs=[{'name':'hist_leaf15','max_leaf_nodes':15,'min_samples_leaf':100,'l2_regularization':10},
       {'name':'hist_leaf31','max_leaf_nodes':31,'min_samples_leaf':300,'l2_regularization':100}]
if not (OUT/'plan.json').exists():
    dump_json(OUT/'plan.json',{'created_utc':datetime.now(UTC).isoformat(),'synthetic':False,
        'training_years':list(range(2015,2021)),'selection_years':[2021,2022],
        'candidate_budget':2,'specifications':specs,'features':features,
        'promotion_rule':'recall and AP must exceed frozen stack development values in both 2021 and 2022; no final-year data',
        'test_2023_2025_used':False})
industrial=set(json.loads((mu.OLD/'industrial_cells_2020.json').read_text())['cell_ids'])
columns=features+['day','label','weight','cell_id']
pieces=[]
for year in range(2015,2021):
    path=mu.RUN/f'features/{year}_train.parquet';proof=json.loads(path.with_suffix('.json').read_text())
    if checksum(path)!=proof['sha256']:raise ValueError('Development feature hash differs')
    f=pd.read_parquet(path,columns=columns);pieces.append(f[~f.cell_id.isin(industrial)])
train=pd.concat(pieces,ignore_index=True);del pieces;gc.collect()
valid={y:pd.read_parquet(mu.RUN/f'features/{y}_evaluation.parquet',columns=columns) for y in [2021,2022]}
valid={y:f[~f.cell_id.isin(industrial)] for y,f in valid.items()}
joint=pd.read_csv(mu.ROOT/'runs/model_stack_v5/joint_comparison.csv').query('weight==0.5').iloc[0]
records=[]
for spec in specs:
    target=OUT/(spec['name']+'.json')
    if target.exists():records.append(json.loads(target.read_text()));continue
    model=HistGradientBoostingClassifier(**{k:v for k,v in spec.items() if k!='name'},
        max_iter=250,learning_rate=.05,early_stopping=False,random_state=42)
    with threadpool_limits(limits=4):
        model.fit(train[features],train.label,sample_weight=train.weight/train.weight.mean())
        result={'name':spec['name'],'synthetic':False,'training_max_year':2020,'selection_max_year':2022,'years':{}}
        for year,f in valid.items():
            score=model.predict_proba(f[features])[:,1]
            point=mu.operating_point(f.label.to_numpy(),score,f.weight.to_numpy(),.10 if year==2021 else .05948629009987054)
            result['years'][str(year)]=point
            pd.DataFrame({'probability':score}).to_parquet(OUT/f'{spec["name"]}_{year}.parquet',index=False)
    result['promotable']=all(result['years'][str(y)]['recall']>joint[f'recall_{y}'] and result['years'][str(y)]['average_precision']>joint[f'ap_{y}'] for y in [2021,2022])
    joblib.dump(model,OUT/f'{spec["name"]}.joblib',compress=3)
    dump_json(target,result);records.append(result)
    print(json.dumps(result),flush=True)
    del model;gc.collect()
dump_json(OUT/'comparison.json',{'synthetic':False,'candidates':records,'test_used':False,'selected':None,
                               'reason':'A challenger is never promoted without the registered development criteria and a new frozen release'})
