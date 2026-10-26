"""Select on 2021, refit only pre-2023, calibrate 2022, freeze before reassessment."""
from __future__ import annotations
import argparse
import json
import shutil
from datetime import UTC,datetime
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from wildfire_kz import model_upgrade as mu,stacked_model
from wildfire_kz.calibration import fit_sigmoid,map_boundaries
from wildfire_kz.data import checksum,dump_json
from wildfire_kz.evaluation import metrics,cluster_draws

RUN=mu.ROOT/'runs/model_stack_v5'
OLD=mu.OLD


def log(message):print(datetime.now(UTC).isoformat(),message,flush=True)


def meta_data(year):
    if year>2021:raise PermissionError('Meta training is restricted to 2019–2021 OOF rows')
    frame=pd.read_parquet(mu.RUN/f'features/{year}_evaluation.parquet')
    baseline_path=OLD/f'validation/xgboost_{year}.parquet'
    proof=json.loads(baseline_path.with_suffix('.sha256.json').read_text())
    if checksum(baseline_path)!=proof['sha256']:raise ValueError('OOF probabilities changed')
    old=pd.read_parquet(baseline_path)
    f=old[['cell_id','day']].merge(frame,on=['cell_id','day'],how='left',validate='one_to_one')
    if f.label.isna().any():raise ValueError('OOF keys differ')
    x=f[mu.HISTORY].copy()
    x['baseline_logit']=logit(np.clip(old.probability.to_numpy(),1e-7,1-1e-7))
    return f,x


def train_and_freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    if (RUN/'release.json').exists():raise FileExistsError('Existing frozen experiment is immutable')
    archive=RUN/'before_joint_selection';archive.mkdir(exist_ok=True)
    for name in ['model.joblib','plan.json','selection.json','training.json']:
        if (RUN/name).exists() and not (archive/name).exists():shutil.copyfile(RUN/name,archive/name)
    comparison=pd.read_csv(mu.RUN/'meta_blends.csv')
    winner=comparison.sort_values(['recall','average_precision'],ascending=False).iloc[0].to_dict()
    baseline=pd.read_parquet(OLD/'validation/xgboost_2021.parquet')
    baseline_point=mu.operating_point(baseline.label.to_numpy(),baseline.probability.to_numpy(),baseline.weight.to_numpy())
    if winner['recall']<=baseline_point['recall']:raise ValueError('No development recall gain')
    dump_json(RUN/'plan.json',{'synthetic':False,'created_utc':datetime.now(UTC).isoformat(),
        'model':'original XGBoost plus learned chronological logistic stack and selected score blend',
        'base_training_years':list(range(2015,2022)),'meta_selection_training_years':[2019,2020],
        'validation_years':[2021,2022],'meta_final_training_years':[2019,2020,2021],'calibration_year':2022,
        'selection_max_year':2022,'selection_rule':'C selected on 2021; blend maximizes minimum relative recall gain across 2021 at precision>=0.10 and 2022 at original operating precision; AP must improve in both years',
        'threshold_rule':'max 2022 weighted recall with precision no lower than original XGBoost 2022 operating precision',
        'history_lag_days':2,'history_windows':mu.FIRE_WINDOWS,'meta_C_candidates':[.01,.1,1],
        'meta_blend_weights':[1,.75,.5,.25],'test_previously_reported':True,'test_used_for_selection':False,
        'transport':'float16 rounding before calibration operating-point evaluation and all final metrics',
        'previous_failed_experiments':['model_upgrade_v3','model_upgrade_v4'],
        'lineage':'OOF first-stage scores were produced by models fitted on years strictly earlier than each OOF year'})
    comparison.to_csv(RUN/'comparison.csv',index=False)
    dump_json(RUN/'selection.json',{'selected':{**winner,'name':winner['name']+f"_blend{winner['weight']}"},
        'baseline':baseline_point,'selection_max_year':2021,'test_accessed':False})
    pairs=[meta_data(y) for y in [2019,2020,2021]]
    frame=pd.concat([f for f,x in pairs],ignore_index=True)
    x=pd.concat([x for f,x in pairs],ignore_index=True)
    c=float(winner['name'].split('_C')[-1])
    meta=make_pipeline(StandardScaler(),LogisticRegression(C=c,max_iter=1000))
    meta.fit(x,frame.label,logisticregression__sample_weight=frame.weight.to_numpy()/frame.weight.mean())
    base=joblib.load(OLD/'models.joblib')['xgboost']
    features=mu.FEATURES+mu.HISTORY
    model=stacked_model.StackedFireModel(base,meta,float(winner['weight']))
    joblib.dump({'estimator':model,'features':features,'spec':winner},RUN/'model.joblib',compress=3)
    dump_json(RUN/'training.json',{'synthetic':False,'training_end':2021,'meta_rows':len(frame),
        'meta_positive_rows':int(frame.label.sum()),'base_rows':1250660,'rows':len(frame),
        'positives':int(frame.label.sum()),'baseline_sha256':checksum(OLD/'models.joblib'),
        'meta_C':c,'meta_weight':winner['weight'],'model_sha256':checksum(RUN/'model.joblib')})
    calibration_frame=pd.read_parquet(mu.RUN/'features/2022_evaluation.parquet')
    excluded=json.loads((OLD/'industrial_cells.json').read_text())['cell_ids']
    f=calibration_frame.loc[~calibration_frame.cell_id.isin(excluded)].reset_index(drop=True)
    old_cal=joblib.load(OLD/'calibrators.joblib')['xgboost']
    old_p=old_cal.predict(base.predict(f))
    old_threshold=json.loads((OLD/'frozen.json').read_text())['thresholds']['xgboost']
    original_metrics=metrics(f.label.to_numpy(),old_p,f.weight.to_numpy(),old_threshold,old_p)
    trials=[]
    for weight in [1.,.75,.5,.25]:
        model.meta_weight=weight
        raw=model.predict_proba(f[features])[:,1]
        point2022=mu.operating_point(f.label.to_numpy(),raw,f.weight.to_numpy(),original_metrics['precision'])
        fold2021=comparison.loc[(comparison['name']==winner['name'])&(comparison['weight']==weight)].iloc[0]
        gain=min(float(fold2021.recall)/baseline_point['recall'],point2022['recall']/original_metrics['recall'])
        if float(fold2021.average_precision)<=baseline_point['average_precision'] or point2022['average_precision']<=original_metrics['average_precision']:gain=0.
        trials.append({'weight':weight,'minimum_relative_recall':gain,'recall_2021':float(fold2021.recall),
            'ap_2021':float(fold2021.average_precision),'recall_2022':point2022['recall'],'ap_2022':point2022['average_precision']})
    best=max(trials,key=lambda v:v['minimum_relative_recall'])
    if best['minimum_relative_recall']<=1:raise ValueError('No blend improves both pre-2023 validation years')
    model.meta_weight=best['weight']
    joblib.dump({'estimator':model,'features':features,'spec':{**winner,'weight':best['weight']}},RUN/'model.joblib',compress=3)
    training=json.loads((RUN/'training.json').read_text());training['meta_weight']=best['weight'];training['model_sha256']=checksum(RUN/'model.joblib');dump_json(RUN/'training.json',training)
    pd.DataFrame(trials).to_csv(RUN/'joint_comparison.csv',index=False)
    dump_json(RUN/'selection.json',{'selected':{**winner,'weight':best['weight'],'name':winner['name']+f"_blend{best['weight']}"},
        'baseline':baseline_point,'selection_max_year':2022,'test_accessed':False,'joint_criterion':best})
    raw=model.predict_proba(f[features])[:,1]
    calibration,_=fit_sigmoid(f,raw,2022)
    p=mu.published_probability(calibration.predict(raw))
    point=mu.operating_point(f.label.to_numpy(),p,f.weight.to_numpy(),original_metrics['precision'])
    strict=mu.operating_point(f.label.to_numpy(),p,f.weight.to_numpy(),.10)
    if point['recall']<=original_metrics['recall']:raise ValueError('2022 matched-precision recall did not improve; no release')
    joblib.dump(calibration,RUN/'calibrator.joblib',compress=3)
    dump_json(RUN/'frozen.json',{'synthetic':False,'model':'xgboost_spatiotemporal','features':features,
        'threshold':point['threshold'],'calibration_metrics':point,'original_2022_metrics':original_metrics,
        'strict_precision10_operating_point':strict,'calibration_year':2022,'selection_max_year':2022,
        'precision_floor':original_metrics['precision'],'boundaries':map_boundaries(p,[.5,.8,.95],f.weight.to_numpy()),
        'test_used_for_selection':False,'operational_validation':False})
    files=['model.joblib','calibrator.joblib','frozen.json','selection.json','training.json','plan.json','comparison.csv','joint_comparison.csv']
    dump_json(RUN/'release.json',{'synthetic':False,'selection_max_year':2022,'frozen_utc':datetime.now(UTC).isoformat(),
        'test_previously_reported':True,'artifacts':{n:checksum(RUN/n) for n in files},
        'feature_code_sha256':checksum(Path(mu.__file__)),'model_code_sha256':checksum(Path(stacked_model.__file__)),
        'runner_code_sha256':checksum(Path(__file__)),
        'feature_table_hashes':{p.name:checksum(p) for p in (mu.RUN/'features').glob('*.parquet')},
        'oof_hashes':{f'xgboost_{y}.parquet':checksum(OLD/f'validation/xgboost_{y}.parquet') for y in [2019,2020,2021]}})
    log(f"Frozen: calibration P={point['precision']:.3%}, R={point['recall']:.3%}, AP={point['average_precision']:.5f}; original 2022 P={original_metrics['precision']:.3%}, R={original_metrics['recall']:.3%}")

def evaluate() -> None:
    release=RUN/"release.json"
    record=mu.verify_release(release)
    if checksum(Path(stacked_model.__file__))!=record["model_code_sha256"]:raise PermissionError("Frozen stack code changed")
    if checksum(Path(__file__))!=record["runner_code_sha256"]:
        raise PermissionError("Evaluation runner changed after freeze")
    if (RUN/"evaluation.json").exists():
        raise FileExistsError("Preserve completed one-shot reassessment")
    history=mu.FireHistory(mu.load_history(2024,release))
    selected=joblib.load(RUN/"model.joblib")
    calibrator=joblib.load(RUN/"calibrator.joblib")
    frozen=json.loads((RUN/"frozen.json").read_text())
    pieces=[]
    for year in [2023,2024]:
        f=pd.read_parquet(OLD/f"features/{year}_evaluation.parquet")
        f=mu.augment(f,history,release)
        industrial=json.loads((OLD/"industrial_cells.json").read_text())["cell_ids"]
        f=f.loc[~f.cell_id.isin(industrial)].reset_index(drop=True)
        p=mu.published_probability(calibrator.predict(selected["estimator"].predict_proba(f[selected["features"]])[:,1]))
        columns=["cell_id","day","label","weight","x","y_coord","area_km2","landcover"]
        pieces.append(f[columns].assign(probability=p))
        log(f"post-freeze benchmark inference {year}: {len(f):,} rows")
    f=pd.concat(pieces,ignore_index=True)
    f.to_parquet(RUN/"predictions.parquet",index=False)
    old=pd.read_parquet(OLD/"evaluate/predictions_xgboost.parquet")
    if not old[["cell_id","day"]].equals(f[["cell_id","day"]]):
        raise ValueError("Benchmark keys differ from original experiment")
    reference=pd.read_parquet(OLD/"evaluate/predictions_seasonal.parquet").probability.to_numpy()
    old_threshold=json.loads((OLD/"frozen.json").read_text())["thresholds"]["xgboost"]
    rows=[]
    for name,p,t in [("xgboost_original",old.probability.to_numpy(),old_threshold),
                     ("xgboost_spatiotemporal",f.probability.to_numpy(),frozen["threshold"])]:
        for period in ["2023–2024","2023","2024"]:
            mask=np.ones(len(f),bool) if '–' in period else f.day.dt.year.eq(int(period)).to_numpy()
            rows.append({"model":name,"period":period,"threshold":t,**metrics(f.label.to_numpy()[mask],p[mask],f.weight.to_numpy()[mask],t,reference[mask])})
    pd.DataFrame(rows).to_csv(RUN/"metrics.csv",index=False)
    draws=cluster_draws(f,1000,100000,30,42)
    aggregate=lambda a:np.bincount(draws.codes,weights=a,minlength=draws.multiplicities.shape[1])
    w,y=f.weight.to_numpy(),f.label.to_numpy()
    positive=draws.multiplicities@aggregate(w*y)
    estimates={}
    intervals=[]
    for name,p,t in [("original",old.probability.to_numpy(),old_threshold),("new",f.probability.to_numpy(),frozen["threshold"])]:
        alert=p>=t
        tp=draws.multiplicities@aggregate(w*y*alert)
        mass=draws.multiplicities@aggregate(w*alert)
        precision=np.divide(tp,mass,out=np.zeros_like(tp),where=mass>0)
        recall=tp/positive
        estimates[name]={"precision":precision,"recall":recall}
    for name in ["original","new","new minus original"]:
        for metric in ["precision","recall"]:
            v=estimates[name][metric] if name in estimates else estimates["new"][metric]-estimates["original"][metric]
            intervals.append({"model":name,"metric":metric,"lower":float(np.quantile(v,.025)),"upper":float(np.quantile(v,.975)),"resamples":1000})
    pd.DataFrame(intervals).to_csv(RUN/"cluster_intervals.csv",index=False)
    dump_json(RUN/"evaluation.json",{"synthetic":False,"release_sha256":checksum(release),"completed_utc":datetime.now(UTC).isoformat(),
        "selection_max_year":2022,"test_previously_reported":True,"model_frozen_before_reassessment":True,
        "rows":len(f),"positives":int(f.label.sum()),"metrics":rows,
        "outputs":{name:checksum(RUN/name) for name in ["predictions.parquet","metrics.csv","cluster_intervals.csv"]}})
    log(json.dumps([r for r in rows if r['period']=='2023–2024']))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=["train","evaluate"])
    args=parser.parse_args()
    {"train":train_and_freeze,"evaluate":evaluate}[args.phase]()
