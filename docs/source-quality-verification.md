# Public-source verification notes

The real-data adapter follows the metadata of the actual downloaded granules.
The retained [2020-12-27 native header](source_metadata/noaa-2020-12-27.das) and
its [source/checksum record](source_metadata/noaa-2020-12-27.json) come from
the anonymous NOAA NCEI endpoint. Although the filename contains `v001`, this
granule declares internal product version `v2r0`. Its aerosol quality field has
mask 192 and values climatology/low/average/high uncertainty; the adapter removes
the high-uncertainty value. Cloud confidence, shadow, land/water, cirrus, cloud
and snow bits are also checked against this native header. An older algorithm
document or a catalogue summary is not used to override the file's actual flags.
The native NDVI scale is 0.0001 and the valid raw range is -1000 to 10000.

Verified NOAA subset responses and MODIS subset JSON can be losslessly archived
as `.gz`. Each archive records both its compressed and original SHA-256. Gzip
decompression restores the exact provider-response bytes. Duplicate weather
row checkpoints can be removed after the complete annual array passes its hash
check. These storage operations do not change the prepared numerical inputs.
Actual reclaimed bytes are recorded in `runs/public_hindcast/storage_*.json`.

Before model release, the final precipitation interval of 2022 is left missing
because it ends at 2023-01-01 00:00 UTC. That observation must remain sealed.
After release, the final-only boundary helper obtains the required interval,
preserves the exact original 2022 array in `runs/public_hindcast/frozen_inputs`,
and completes that day for test-year predictors. Its first possible target is
2023-01-07 under the fixed weather lag. It recomputes the actual 2022 predictor
columns and requires exact agreement with the frozen calibration table; model,
calibrator and threshold hashes must remain unchanged. The old/new source hashes,
backup location, actual source objects and verification are recorded in
`final_weather_boundary.json`. No 2023 observation is used to refit calibration.

The completed run's `acquisition_manifest.json` distinguishes provider dates,
actual download timestamps where recorded, and file modification evidence. It
contains the actual prepared arrays, compressed source responses, native source
metadata and normalized detection partitions. Historical publication times are
not reconstructed from later archive creation dates. See the public method for
the retrospective interpretation and the differences from the primary protocol.
