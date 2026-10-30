"""Print separate scenic and low-cloud indices, raw HRRR inputs and scoring rules.

Examples:
  python -m scripts.explain_forecast --date 2026-10-31 --top 5
  python -m scripts.explain_forecast --top 10
  python -m scripts.explain_forecast --date 2026-10-31 --hour 7
This analyzes the live HRRR JSONL cache, not the NOAA weather outside the cache.
"""
import argparse
from pathlib import Path

from inversion.config import DATA_DIR
from inversion.heuristic import evaluate
from inversion.hrrr import load_jsonl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features', type=Path, default=DATA_DIR / 'hrrr_live.jsonl')
    parser.add_argument('--date', help='Target date in Boulder time (YYYY-MM-DD)')
    parser.add_argument('--hour', type=int, choices=range(24), metavar='0..23',
                        help='Target local hour (0-23); omit for all hours')
    parser.add_argument('--top', type=int, default=5, help='Highest Green Mountain scenic index hours')
    args = parser.parse_args()
    if args.top < 1:
        parser.error('--top must be positive')
    if not args.features.exists():
        parser.error(f'{args.features} does not exist; run python -m inversion.hrrr live')
    rows = load_jsonl(args.features)
    selected = []
    for row in rows:
        local_time = row['local_time']
        if args.date and local_time[:10] != args.date:
            continue
        if args.hour is not None and int(local_time[11:13]) != args.hour:
            continue
        selected.append((evaluate(row), row))
    selected.sort(key=lambda item: item[0]['scenic_heuristic_score'] if item[0]['scenic_heuristic_score'] is not None else -1, reverse=True)
    if not selected:
        print('No matching forecasts in the current cache. Check available valid times or run HRRR live with --morning-hours 5,6,7,8,9.')
        return
    for result, row in selected[:args.top]:
        print(f"\n{row['local_time']} | Green Mt scenic {result['scenic_heuristic_score'] if result['scenic_heuristic_score'] is not None else 'N/A'}/100, low-cloud setup {result['heuristic_score']}/100")
        print(f"HRRR run {row['run_utc']} | F{int(row['lead_hours']):02d} | Uncalibrated indices, NOT probabilities")
        print(f"Calculation: {result['heuristic_unrounded_score']:.2f} weighted points -> {result['heuristic_score']}/100")
        for part in result['heuristic_breakdown']:
            values = ', '.join(f"{v['label']}={v['value']:.1f} {v['unit']}" if v['value'] is not None
                               else f"{v['label']}=missing" for v in part['readings'])
            missing = ' [missing input: neutral fallback]' if part['has_missing_readings'] else ''
            print(f"  {part['weighted_points']:5.2f}/{part['max_points']:g} points  {part['label']} ({part['factor_score']:.1f}/100): {values}{missing}")
        print('Scenic assessment:', result['scenic_heuristic_reason'])
        print('First Flatiron scenic:', result['scenic_flatiron_score'])
        for k, v in result['scenic_indicators'].items():
            print(f'  {k}: {v}')
        print('RH-profile drying transition (not a cloud top):', result['scenic_profile_drying_transition_ft_msl'])
        print('NOAA surface index:', result['forecast_source']['surface_inventory_url'])
        print('NOAA pressure index:', result['forecast_source']['pressure_inventory_url'])


if __name__ == '__main__':
    main()
