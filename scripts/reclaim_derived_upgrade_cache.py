"""Reclaim reproducible feature caches; keep providers, models, predictions and reports."""
from datetime import UTC,datetime
from pathlib import Path
from wildfire_kz.data import checksum,dump_json

root=Path(__file__).resolve().parents[1]
targets=[root/'runs/model_upgrade_v3/features',root/'runs/model_upgrade_v4/features']
records=[]
for directory in targets:
    resolved=directory.resolve()
    if resolved not in [(root/'runs'/name/'features').resolve() for name in ['model_upgrade_v3','model_upgrade_v4']]:
        raise ValueError('Unverified cache directory')
    if not resolved.is_relative_to(root.resolve()):raise ValueError('Cache outside workspace')
    for path in sorted(directory.glob('*.parquet')):
        records.append({'path':str(path.relative_to(root)),'sha256':checksum(path),'bytes':path.stat().st_size})
dump_json(root/'runs/derived_cache_reclamation.json',{'created_utc':datetime.now(UTC).isoformat(),
    'files':records,'saved_bytes':sum(r['bytes'] for r in records),
    'kind':'generated pre-2023 history-feature caches; source tables and all experiment results retained',
    'regeneration':'scripts/train_model_upgrade.py prepare rebuilds current v4 caches from original provider-backed features; v3 is superseded seven-day-lag exploratory cache'})
for record in records:
    path=(root/record['path']).resolve()
    if path.parent not in [p.resolve() for p in targets]:raise ValueError('Unexpected cache file')
    path.unlink()
print({'saved_bytes':sum(r['bytes'] for r in records),'files':len(records)})
