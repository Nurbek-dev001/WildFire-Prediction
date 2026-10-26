"""Commit the evaluation protocol before accessing new 2025 fire labels."""
from datetime import UTC, datetime
from pathlib import Path
import json
from wildfire_kz import model_upgrade as mu
from wildfire_kz.data import checksum, dump_json

root = mu.ROOT / 'runs/independent_2025'
root.mkdir(exist_ok=True)
path = root / 'protocol.json'
if path.exists():
    raise FileExistsError('The registered protocol is immutable')
mu.verify_release(mu.ROOT / 'runs/model_stack_v5/release.json')
dump_json(path, {
    'created_utc': datetime.now(UTC).isoformat(), 'synthetic': False,
    'test_year': 2025, 'labels_accessed': False,
    'model_release_sha256': checksum(mu.ROOT / 'runs/model_stack_v5/release.json'),
    'model_directory': 'runs/model_stack_v5', 'training_and_selection_max_year': 2022,
    'threshold': json.loads((mu.ROOT / 'runs/model_stack_v5/frozen.json').read_text())['threshold'],
    'model_retraining_permitted': False, 'threshold_tuning_permitted': False,
    'primary_unit': 'eligible 5 km cell-day with first SNPP standard-processed detection',
    'primary_metrics': ['precision','recall','f1','average_precision','roc_auc','brier'],
    'sampling': 'all eligible positive cell-days; 300 negatives per day and region, seed 20250401, inverse inclusion weights',
    'risk_set': 'prior-year vegetated cover, frozen development industrial exclusions, no detection in previous 48 hours',
    'uncertainty': '1000 paired 100 km by 30 day cluster bootstrap resamples, seed 42',
    'subgroups': ['region','month','ndvi_missing'],
    'event_analysis': 'same-cell alert on first detection day; secondary prior-day alert; unique connected events (2 km, 48 hours); exclude events outside eligible risk set; report uncovered separately',
    'weather': 'same anonymous ERA5 0.25 degree source; latest day target minus 7; no future inputs',
    'vegetation': 'same NOAA VIIRS NDVI 0.05 degree QA and weekly calendar extended through 2025; target minus 12, maximum age 32 days',
    'landcover': 'MCD12Q1 2024, never 2025 cover',
    'adapter_gate': 'feature adapter must reproduce 2022 original inputs before opening 2025 labels',
    'test_interpretation': 'one new temporal assessment of a frozen model; not a prospective as-issued operational trial or spatial holdout',
})
dump_json(root / 'protocol.sha256.json', {'sha256': checksum(path)})
print(checksum(path))
