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

Before the final metric implementation was sealed, a code audit identified
an assumption of four distinct map classes. A constant-score fixture checks the repair. Frozen calibration
quantiles can coincide and are deliberately deduplicated. Class-frequency
tabulation now iterates the actual frozen intervals; tests verify that equality
belongs to the upper interval and that sample counts, design-weight mass and
area-days are conserved. Calibration boundaries, AP and model selection are
unchanged. This pre-test repair is included in the sealed evaluation-code hash.

## Final-year supplier gap and original-provider recovery

The models, 2022 calibrators, thresholds and metric code were frozen on
22 October 2026 at 13:28 UTC before final-year input retrieval. The public S3
catalogue lacks four `soil_moisture_0_to_7cm` objects: chunks 934–937, covering
14 September through 6 December 2023. Other weather fields and 2024 weather
remain available. No missing soil observations are fabricated.

The original provider's [historical API](https://open-meteo.com/en/docs/historical-weather-api)
exposes the same ERA5 parameter. Recovery requests `models=era5`, the original
quarter-degree native coordinates, `cell_selection=nearest`, UTC and hourly
0–7 cm volumetric soil water in m³/m³. No spatial interpolation or model refitting
is added. The 24-hour mean and frozen physical bounds are unchanged. Comparison
of 200 native locations on each of 1 October and 1 December 2021 measured **zero
difference** against the existing training archive after that same daily feature
rule. No final labels were opened to choose the input transport.

`scripts/openmeteo_soil_api.py` saves losslessly compressed original responses,
request URLs, byte checksums, a code-bound acquisition plan and the development
comparison. `scripts/acquire_2023_weather_recovery.py` stages native fields and
registers the complete annual input only after the missing observations arrive.
The source plan and annual provenance bind the frozen model release. A guard
rejects a new source recovery after final labels have been normalised. The
original frozen models and preprocessing remain unchanged.

The [published quota](https://open-meteo.com/en/terms) is 600 equivalent calls per
minute, 5,000 per hour and 10,000 per day. The public pricing calculator reports
100 equivalent calls for 100 locations, one variable and three months. The local
downloader conservatively accounts for one equivalent call per location, using
500/minute, 4,500/hour and 9,000/day, including diagnostic requests and failed
attempts. It persists the budget journal and honours server rejections. No key,
subscription or paid request is used.

Google's [ARCO-ERA5](https://github.com/google-research/arco-era5) was considered
as another public copy. Two development-day comparisons measured maximum
differences of 0.000125 and 0.179917 m³/m³. It was rejected as a drop-in replacement
and contributes no values to the 2023 model input. Compatibility evidence and its
code snapshot are retained in `runs/public_hindcast/source_checks/rejected_arco/`.
The broad acquisition inventory includes unused compatibility evidence; the
annual weather provenance identifies the actual model inputs.
