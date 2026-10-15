"""Summarize equivalent before/after synthetic navigation captures."""

import json
import hashlib
import math
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / 'output'
ROUTES = ('/', '/car-details/', '/complaints/')


def fixture_media(checkout):
    root = checkout / 'output' / 'navigation-synthetic-media'
    paths = sorted(path for path in root.rglob('*') if path.is_file()
                   and 'synthetic' in path.relative_to(root).parts)
    digest = hashlib.sha256()
    total = 0
    for path in paths:
        contents = path.read_bytes()
        digest.update(path.relative_to(root).as_posix().encode('utf8'))
        digest.update(contents)
        total += len(contents)
    return {'files': len(paths), 'bytes': total, 'sha256': digest.hexdigest()}


def summary(samples, key):
    values = sorted(float(sample[key]) for sample in samples if sample.get(key) is not None)
    if not values:
        return None
    return {'median': round(statistics.median(values), 1),
            'p95': round(values[math.ceil(.95 * len(values)) - 1], 1),
            'n': len(values)}


def main():
    captures = {}
    for label in ('before', 'after'):
        path = CAPTURES / f'synthetic-navigation-{label}.json'
        captures[label] = json.loads(path.read_text(encoding='utf8'))
        if 'browser' not in captures[label] or 'error' in captures[label]:
            raise RuntimeError(f'Incomplete {label} capture')
    before, after = captures['before'], captures['after']
    if before['fixture'] != after['fixture']:
        raise RuntimeError('Fixture volumes differ')
    media = {label: fixture_media(ROOT if label == 'after' else
                                  ROOT.parent / 'fast-navigation-baseline')
             for label in captures}
    if media['before'] != media['after']:
        raise RuntimeError('Synthetic media fixture differs')
    if before['browser']['chrome_version'] != after['browser']['chrome_version']:
        raise RuntimeError('Chrome versions differ')
    for label, capture in captures.items():
        browser = capture['browser']
        if not browser['history_ok'] or any(browser[key] for key in
                ('page_errors', 'request_failures', 'http_failures')):
            raise RuntimeError(f'{label} had browser failures')
        if len(capture['logins']) != 13:
            raise RuntimeError(f'{label} did not test every role')
    result = {'revisions': {label: capture['revision'] for label, capture in captures.items()},
              'fixture': before['fixture'],
              'database_bytes': {label: capture['database_bytes']
                                 for label, capture in captures.items()},
              'fixture_media': media['before'],
              'media_root_bytes_during_capture': {label: capture['media_bytes']
                                                   for label, capture in captures.items()},
              'chrome_version': before['browser']['chrome_version'],
              'history': {label: {'ok': capture['browser']['history_ok'],
                                  'trace': capture['browser'].get('history_trace', [])}
                          for label, capture in captures.items()},
              'routes': {}}
    for route in ROUTES:
        rows = {}
        for label, capture in captures.items():
            rows[label] = {
                'server': {metric: summary(capture['server'][route], metric)
                           for metric in ('duration_ms', 'sql_count', 'sql_duration_ms')},
                'cold': {metric: summary(capture['browser']['cold'][route], metric)
                         for metric in ('ttfb_ms', 'html_duration_ms', 'dcl_ms',
                                        'lcp_ms', 'long_task_ms')},
                'warm': {metric: summary(capture['browser']['warm'][route], metric)
                         for metric in ('usable_ms', 'ttfb_ms', 'html_duration_ms',
                                        'long_task_ms', 'script_ms')},
            }
        result['routes'][route] = rows
    run1_paths = {label: CAPTURES / f'synthetic-navigation-{label}-run1.json'
                  for label in ('before', 'after')}
    if all(path.is_file() for path in run1_paths.values()):
        prior = {label: json.loads(path.read_text(encoding='utf8'))
                 for label, path in run1_paths.items()}
        if any(prior[label]['fixture'] != captures[label]['fixture']
               or prior[label]['browser']['chrome_version'] != captures[label]['browser']['chrome_version']
               or not prior[label]['browser']['history_ok']
               for label in prior):
            raise RuntimeError('Earlier pair is incompatible with the current capture')
        result['combined_routes'] = {}
        for route in ROUTES:
            result['combined_routes'][route] = {}
            for label in ('before', 'after'):
                result['combined_routes'][route][label] = {
                    'warm_usable_ms': summary(prior[label]['browser']['warm'][route]
                                              + captures[label]['browser']['warm'][route], 'usable_ms'),
                    'cold_dcl_ms': summary(prior[label]['browser']['cold'][route]
                                           + captures[label]['browser']['cold'][route], 'dcl_ms'),
                    'server_ms': summary(prior[label]['server'][route]
                                         + captures[label]['server'][route], 'duration_ms'),
                }
    output = CAPTURES / 'synthetic-navigation-comparison.json'
    output.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(output)
    for route, rows in result['routes'].items():
        print(route)
        for label in ('before', 'after'):
            print(f"  {label}: cold DCL {rows[label]['cold']['dcl_ms']}, "
                  f"warm usable {rows[label]['warm']['usable_ms']}, "
                  f"server {rows[label]['server']['duration_ms']}")
        if 'combined_routes' in result:
            print('  combined warm usable:',
                  result['combined_routes'][route]['before']['warm_usable_ms'],
                  '->', result['combined_routes'][route]['after']['warm_usable_ms'])


if __name__ == '__main__':
    main()
