"""Dated 2020 exposure overlay; never silently replaces the trained 2010 feature."""
import json
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import reproject,Resampling
from wildfire_kz.data import checksum,dump_json
from wildfire_kz.data.public_predictors import ROOT,PUBLIC,geography,target_lattice

source=PUBLIC/'human/worldpop_2020.tif'
proof=json.loads(source.with_name(source.name+'.sha256.json').read_text())
if checksum(source)!=proof['sha256']:raise ValueError('WorldPop checksum differs')
grid=geography()[0];shape,transform,rows,cols=target_lattice(grid)
with rasterio.open(source) as src:
    image=np.full(shape,np.nan,dtype='float32')
    reproject(rasterio.band(src,1),image,src_transform=src.transform,src_crs=src.crs,
              dst_transform=transform,dst_crs=grid.crs,src_nodata=src.nodata,dst_nodata=np.nan,
              resampling=Resampling.sum)
values=image[rows,cols]
frame=pd.DataFrame({'cell_id':grid.cell_id,'estimated_population_2020':values})
frame.to_parquet(PUBLIC/'human/population_2020_cells.parquet',index=False)
destination=ROOT/'platform/dist/assets/population-2020.json'
dump_json(destination,{'year':2020,'source':'WorldPop 1 km population counts, unadjusted',
    'source_url':'https://hub.worldpop.org/geodata/summary?id=31960','source_sha256':checksum(source),
    'aggregation':'GDAL sum to native 5 km lattice; boundary-cell estimates follow raster overlap',
    'model_input':False,'damage_prediction':False,'values':dict(zip(frame.cell_id,[round(float(v),1) if np.isfinite(v) else None for v in values]))})
print(json.dumps({'cells':len(frame),'finite_cells':int(np.isfinite(values).sum()),'path':str(destination)}))
