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

An optional Windows observer records the owned comparison worker's lifetime
user/kernel CPU times using
[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes).
It keeps a read-only process handle through exit and checks creation time to
avoid a reused PID. Although attached after training began, the counters cover
the process's full lifetime. The completed record is matched to the actual
model artifact SHA-256 before inclusion in the report. CPU time sums all process
threads and is reported separately from elapsed time that includes Windows
sleep/hibernation. The observer changes no model, data or power setting.

The separate optional `govern_public_training.py` helper selects Windows
[process-scoped HighQoS](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation)
for the owned comparison while connected to AC. It restores the process's
original QoS on battery or helper exit, preserves priority and affinity, and
stops controlling the policy if a manual policy change is detected. It respects
an existing explicit EcoQoS preference. It changes no global power plan or
sleep/lid behaviour. The event journal records the target PID, creation time,
source hash and actual transitions. The report includes it only when its target
matches the verified CPU observation for the completed model artifact. Training
data, partitions and model parameters retain their original definitions. The
user reduced the search budget on 22 October before test access; the separate
verified `budget_amendment.json` preserves the original protocol and trial history.

Before the final metric implementation was sealed, a constant-score software
fixture exposed an assumption of four distinct map classes. Frozen calibration
quantiles can coincide and are deliberately deduplicated. Class-frequency
tabulation now iterates the actual frozen intervals; tests verify that equality
belongs to the upper interval and that sample counts, design-weight mass and
area-days are conserved. Calibration boundaries, AP and model selection are
unchanged. This pre-test repair is included in the sealed evaluation-code hash.
