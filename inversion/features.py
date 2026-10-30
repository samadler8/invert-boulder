"""Deprecated GFS feature adapter. HRRR rows are created in `inversion.hrrr`."""
def rows_from_data(*args, **kwargs):
    raise RuntimeError('GFS feature conversion retired. Use inversion.hrrr.build_row.')
