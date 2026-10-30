"""Quick statistics for collected HRRR training samples and observed target balance."""
import argparse
from collections import Counter
from inversion.hrrr import load_jsonl
from inversion.observations import read_csv

ap=argparse.ArgumentParser()
ap.add_argument('--features',default='data/hrrr_samples.jsonl')
ap.add_argument('--observations',default='data/observed_bdu_2018_2026.csv')
a=ap.parse_args()
rows=load_jsonl(a.features)
obs=read_csv(a.observations)
print('Downloaded forecast-run/lead rows:',len(rows))
print('Forecast lead counts:',dict(sorted(Counter(int(r['lead_hours']) for r in rows).items())))
for target in ('low_ceiling','fog'):
    by_time={r['timestamp'] for r in rows if r['timestamp'] in obs and obs[r['timestamp']].get(target) is not None}
    npos={t for t in by_time if obs[t][target]==1}
    print(target,'usable independently observed hours:',len(by_time),'positive hours:',len(npos),
          'positive calendar days:',len({t[:10] for t in npos}))
print('Note: repeated forecasts verifying at the same time do NOT add independent events.')
