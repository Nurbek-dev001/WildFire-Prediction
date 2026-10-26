"""Read public NOAA national subsets with bounded HTTP ranges in separate processes."""
import json
import h5netcdf
import numpy as np
import pandas as pd
import s3fs
import shutil
from concurrent.futures import ProcessPoolExecutor
from wildfire_kz.data import checksum,dump_json
from wildfire_kz.data.public_predictors import PUBLIC,geography,complete,log
from wildfire_kz.independent import protocol
from wildfire_kz.data.http_range import HTTPRangeFile

protocol()
fs=s3fs.S3FileSystem(anon=True)
_,lon,lat=geography()
iy=np.floor((90-lat)/.05).astype(int);ix=np.floor((lon+180)/.05).astype(int)
y0,y1,x0,x1=int(iy.min()),int(iy.max())+1,int(ix.min()),int(ix.max())+1
def acquire(date):
    day=str(date.date());path=PUBLIC/f'vegetation/{day}.npz'
    if complete(path):return
    keys=fs.glob(f'noaa-cdr-ndvi-pds/data/2025/VIIRS-Land*_{date:%Y%m%d}_*.nc')
    if not keys:
        dump_json(path.with_suffix('.unavailable.json'),{'day':day,'reason':'No provider record for the fixed weekly snapshot'})
        return
    key=sorted(keys)[-1];info=fs.info(key)
    # This adapter writes only <=2 MiB national subsets, never global objects.
    # Keep the legacy 5 GiB policy untouched; use a bounded 512 MiB reserve here.
    if shutil.disk_usage(PUBLIC).free < 512*1024**2+2*1024**2:
        raise OSError('National NDVI subset reserve: 512 MiB')
    log(f'NDVI {day}: reading national ranges')
    url='https://noaa-cdr-ndvi-pds.s3.amazonaws.com/'+key.split('/',1)[1]
    with HTTPRangeFile(url,info['size'],info.get('ETag')) as stream:
        with h5netcdf.File(stream,'r') as src:
            log(f'NDVI {day}: metadata opened')
            raw=np.asarray(src.variables['NDVI'][0,y0:y1,x0:x1])
            log(f'NDVI {day}: vegetation raster read')
            # QA is contiguous, not chunked. Read one latitude strip rather than
            # hundreds of tiny requests for discontiguous longitude slices.
            qa=np.asarray(src.variables['QA'][0,y0:y1,:])[:,x0:x1].astype('uint16')
            log(f'NDVI {day}: QA read')
    valid=(raw>=-1000)&(raw<=10000)
    valid &= (qa&(32768|1024|512|256|4))==0
    valid &= (qa&3)<=1
    valid &= (qa&192)!=192
    valid &= np.isin(qa&56,[0,8])
    ndvi=np.where(valid,raw*.0001,np.nan).astype('float32')
    selected=ndvi[iy-y0,ix-x0]
    temporary=path.with_suffix('.working')
    with temporary.open('wb') as stream:np.savez_compressed(stream,ndvi=selected,observation_day=np.array(day))
    if temporary.stat().st_size>2*1024**2:raise ValueError('National subset exceeded bounded budget')
    temporary.replace(path)
    dump_json(path.with_suffix('.sha256.json'),{'sha256':checksum(path),'bytes':path.stat().st_size})
    dump_json(path.with_suffix('.provenance.json'),{'source':'s3://'+key,'source_etag':info.get('ETag'),
        'source_bytes':info['size'],'transport':'anonymous AWS national range reads; same grid and QA as historical module',
        'snapshot_interval_days':7,'native_resolution_deg':.05,'available_after_days':10,
        'quality':'identical QA equations to frozen historical predictor','reprocessed_hindcast':True})
    log(f'NDVI {day}: {np.isfinite(selected).mean():.1%} valid; {info["size"]} source bytes')

if __name__=='__main__':
    # HDF5 serializes its Python file-object callbacks across threads.
    with ProcessPoolExecutor(max_workers=2) as executor:
        for _ in executor.map(acquire,[d for d in pd.date_range('2014-11-01','2025-12-31',freq='7D') if d.year==2025]):pass
