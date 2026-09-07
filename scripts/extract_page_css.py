"""One-time deterministic extraction of page CSS from Django templates."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / 'management' / 'templates' / 'management'
OUTPUT_DIR = ROOT / 'management' / 'static' / 'management' / 'css'
PAGES = {
    'index.html': 'dashboard.css',
    'car_details.html': 'pattern-master.css',
    'complaint_list.html': 'complaints.css',
    'admin_panel.html': 'admin-panel.css',
    'approvals_list.html': 'approvals.css',
    'chat.html': 'chat.css',
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for template_name, asset_name in PAGES.items():
        path = TEMPLATE_DIR / template_name
        source = path.read_text(encoding='utf-8')
        marker_pattern = r'<style(?:\s+data-fabro-page-asset)?>(.*?)</style>'
        matches = list(re.finditer(marker_pattern, source, flags=re.DOTALL))
        if not matches:
            print(f'skip {template_name}: no inline CSS')
            continue
        # Admin and chat use a single unmarked head block. Other pages may have
        # more than one explicitly marked block; leave unmarked modal CSS alone.
        selected = matches[:1] if template_name in {'admin_panel.html', 'chat.html'} else [
            match for match in matches if 'data-fabro-page-asset' in match.group(0)
        ]
        css = '\n'.join(match.group(1).strip() for match in selected) + '\n'
        if '{%' in css or '{{' in css:
            print(f'skip {template_name}: CSS contains Django template syntax')
            continue
        (OUTPUT_DIR / asset_name).write_text(css, encoding='utf-8', newline='\n')
        link = "<link rel=\"stylesheet\" href=\"{% static 'management/css/" + asset_name + "' %}?v=20260907-perf1\">"
        for index, match in reversed(list(enumerate(selected))):
            replacement = link if index == 0 else ''
            source = source[:match.start()] + replacement + source[match.end():]
        path.write_text(source, encoding='utf-8', newline='\n')
        print(f'extracted {template_name} -> {asset_name} ({len(css)} bytes)')


if __name__ == '__main__':
    main()
