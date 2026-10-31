"""Synthetic meteorological fixtures retained for active public-model tests."""
def hrrr_scalars(fog=False):
    s = {('HGT','surface'): 1650.0,('TMP','2 m above ground'):280.0,
         ('DPT','2 m above ground'): 279.5 if fog else 272.0,
         ('RH','2 m above ground'): 98.0 if fog else 50.0,
         ('UGRD','10 m above ground'): 2.0, ('VGRD','10 m above ground'):-3.0,
         ('VIS','surface'): 200.0 if fog else 16000.0,
         ('LCDC','low cloud layer'):95.0 if fog else 12.0,
         ('MCDC','middle cloud layer'):20.0,('HCDC','high cloud layer'):18.0,
         ('HPBL','surface'): 100.0 if fog else 1000.0,
         ('HGT','cloud base'): 1900.0 if fog else 2900.0,
         ('HGT','cloud top'): 2300.0 if fog else 3600.0}
    p = {}
    for pressure,z in zip([800,750,700,650,600],[1950,2420,3000,3550,4250]):
        k=f'{pressure} mb'
        p.update({('HGT',k):z,('TMP',k):282.0-(z-1950)*.004 if fog else 275-(z-1950)*.004,
                  ('RH',k):90.0 if fog else 50.0,
                  ('UGRD',k):3.0,('VGRD',k):-2.0})
    return s,p


