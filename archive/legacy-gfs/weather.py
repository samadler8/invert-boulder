"""Deprecated GFS downloader kept for import compatibility.

HRRR version 3 uses `python -m inversion.hrrr` instead.
"""
def fetch_archive(*args, **kwargs):
    raise RuntimeError('GFS downloader retired. Use python -m inversion.hrrr collect.')

def latest_available_run(*args, **kwargs):
    raise RuntimeError('GFS downloader retired. Use python -m inversion.hrrr live.')
