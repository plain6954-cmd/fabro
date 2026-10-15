"""Print matched median/p95 comparisons from staging_nav_benchmark captures."""

import argparse
import json
import statistics
from pathlib import Path


ROUTES = ('/', '/car-details/', '/complaints/')


def median_p95(samples, key):
    values = sorted(sample[key] for sample in samples if sample.get(key) is not None)
    if len(values) < 10:
        raise ValueError(f'Need at least 10 samples for {key}; found {len(values)}')
    return (round(statistics.median(values), 1),
            round(values[min(len(values)-1, int((len(values)-1)*.95+.5))], 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    before, after = (json.loads(path.read_text(encoding='utf8'))
                     for path in (args.before, args.after))
    if before['label'] != 'before' or after['label'] != 'after':
        raise ValueError('Captures must be labeled before and after.')
    if before['revision'] == after['revision']:
        raise ValueError('Both captures use the same revision.')
    if before['fixture'] != after['fixture']:
        raise ValueError('Fixtures differ; results are not comparable.')
    if before['roles'] != after['roles']:
        raise ValueError('Role access results differ between baseline and feature.')
    if before['database_name'] == after['database_name']:
        raise ValueError('Baseline and feature must use separate fresh databases.')
    for field in ('version', 'shared_buffers', 'work_mem'):
        if before['database_profile'][field] != after['database_profile'][field]:
            raise ValueError(f'PostgreSQL {field} differs between runs.')
    if before['browser']['chrome_version'] != after['browser']['chrome_version']:
        raise ValueError('Chrome versions differ between runs.')
    for capture in (before, after):
        browser = capture['browser']
        if browser['page_errors'] or browser['request_failures'] or browser['http_failures']:
            raise ValueError(f"Browser failures in {capture['label']} capture.")
        if not browser.get('history_ok'):
            raise ValueError(f"History test missing in {capture['label']} capture.")

    print('Metric / route                         baseline median/p95       feature median/p95')
    for route in ROUTES:
        metrics = (
            ('server ms', 'server', 'duration_ms'),
            ('SQL count', 'server', 'sql_count'),
            ('SQL execution ms', 'server', 'sql_duration_ms'),
            ('cold TTFB ms', 'cold', 'ttfb_ms'),
            ('cold DCL ms', 'cold', 'dcl_ms'),
            ('cold LCP ms', 'cold', 'lcp_ms'),
            ('warm usable ms', 'warm', 'usable_ms'),
            ('warm TTFB ms', 'warm', 'ttfb_ms'),
            ('warm HTML duration ms', 'warm', 'html_duration_ms'),
            ('warm HTML bytes', 'warm', 'html_bytes'),
            ('warm script ms', 'warm', 'script_ms'),
            ('warm long task ms', 'warm', 'long_task_ms'),
        )
        for name, group, key in metrics:
            old_samples = (before['browser'][group][route] if group != 'server'
                           else before['server'][route])
            new_samples = (after['browser'][group][route] if group != 'server'
                           else after['server'][route])
            if key == 'lcp_ms' and (sum(s.get(key) is not None for s in old_samples) < 10
                                    or sum(s.get(key) is not None for s in new_samples) < 10):
                print(f'{name + " " + route:37} {"unavailable":25} unavailable')
                continue
            old = median_p95(old_samples, key)
            new = median_p95(new_samples, key)
            print(f'{name + " " + route:37} {str(old):25} {new}')


if __name__ == '__main__':
    main()
