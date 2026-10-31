# HRRR 40-hour extractor v4: CLWMR schema correction

This overlay fixes `ValueError: HRRR missing CLWMR at 800 mb`.
The inspected PRS subset has 25 fields: HGT, TMP, RH, UGRD, VGRD at five pressure levels.
Cloud-liquid mixing ratio (CLWMR) was not present in that subset, but v3 assumed it was.

Changes:
- Stop requesting CLWMR in the pressure-level subset.
- Keep four physically sourced CNN channels: temperature, humidity, U wind, V wind.
- Remove two nonexistent cloud-liquid tabular features.
- Bump schema version to v4 so incompatible model artifacts cannot be loaded accidentally.
- Strengthen the offline test: the fixture now has NO CLWMR fields.

Extract over your existing repository; do not delete historical METAR CSVs.
Retry the 8-sample collection and run data_status before requesting months or years.
The fix has offline QA but still requires end-to-end GRIB verification on your Mac.
