"""Isolated Chrome UI smoke test for the existing Web Push controls.

The browser PushManager is simulated; this does not verify external delivery.
"""
import base64
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
MOCK_PUSH_MANAGER = r"""
window.__permissionRequests = 0;
Object.defineProperty(Notification, 'permission', { configurable: true, get: () => 'granted' });
Notification.requestPermission = (...args) => {
  window.__permissionRequests += 1;
  return Promise.resolve('granted');
};
Object.defineProperty(ServiceWorkerRegistration.prototype, 'pushManager', {
  configurable: true,
  get() {
    return {
      async getSubscription() {
        if (!localStorage.getItem('fabro-test-push-sub')) return null;
        return {
          endpoint: 'https://example.invalid/push/browser-test',
          toJSON: () => ({ endpoint: 'https://example.invalid/push/browser-test', keys: { p256dh: 'browser-test-key', auth: 'browser-test-auth' } }),
          unsubscribe: async () => { localStorage.removeItem('fabro-test-push-sub'); return true; },
        };
      },
      async subscribe() {
        localStorage.setItem('fabro-test-push-sub', '1');
        return this.getSubscription();
      },
    };
  },
});
"""


def run(*args, env):
    subprocess.run([PYTHON, 'manage.py', *args], cwd=ROOT, env=env, check=True,
                   stdout=subprocess.DEVNULL)


def server(env, port):
    proc = subprocess.Popen(
        [PYTHON, 'manage.py', 'runserver', f'127.0.0.1:{port}', '--noreload'],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError('Disposable Django server exited unexpectedly')
        try:
            with urlopen(f'http://127.0.0.1:{port}/login/', timeout=0.3):
                return proc
        except Exception:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError('Disposable Django server did not start')


def login(page, base, username):
    page.goto(base + '/login/')
    page.locator('[name="username"]').fill(username)
    page.locator('[name="password"]').fill('BrowserTest!234')
    page.locator('button[type="submit"]').first.click()
    page.wait_for_url(lambda url: '/login/' not in url)


def main():
    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.urlsafe_b64encode(key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )).decode().rstrip('=')
    private = base64.urlsafe_b64encode(
        key.private_numbers().private_value.to_bytes(32, 'big'),
    ).decode().rstrip('=')
    with tempfile.TemporaryDirectory(prefix='fabro-push-browser-') as directory:
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='scripts.push_browser_settings',
                   FABRO_PUSH_TEST_DB=str(Path(directory) / 'test.sqlite3'),
                   WEBPUSH_VAPID_PUBLIC_KEY=public, WEBPUSH_VAPID_PRIVATE_KEY=private)
        run('migrate', '--run-syncdb', '--noinput', env=env)
        run('shell', '-c', (
            "from django.contrib.auth import get_user_model; "
            "U=get_user_model(); "
            "[U.objects.create_user(username=n,password='BrowserTest!234') "
            "for n in ('push_browser_a','push_browser_b')]"
        ), env=env)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        proc = server(env, port)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()
                context.add_init_script(MOCK_PUSH_MANAGER)
                page = context.new_page()
                login(page, base, 'push_browser_a')
                page.goto(base + '/profile/')
                status = page.locator('.profile-page-wrapper .push-status-text')
                status.wait_for()
                expect(status).to_have_text(re.compile('Enable notifications'))
                assert page.evaluate('window.__permissionRequests') == 0
                for width in (320, 375, 430, 768, 1024, 1440, 1920):
                    page.set_viewport_size({'width': width, 'height': 900})
                    box = page.locator('.profile-page-wrapper .fabro-push-widget').bounding_box()
                    assert box and box['x'] >= 0 and box['x'] + box['width'] <= width + 1, width
                page.locator('.profile-page-wrapper .push-btn-enable').click()
                expect(status).to_have_text(re.compile('Notifications enabled'))
                assert page.evaluate('window.__permissionRequests') == 0
                page.reload()
                expect(status).to_have_text(re.compile('Notifications enabled'))
                page.locator('.profile-page-wrapper .push-btn-disable').click()
                expect(status).to_have_text(re.compile('Enable notifications'))
                page.locator('.profile-page-wrapper .push-btn-enable').click()
                expect(status).to_have_text(re.compile('Notifications enabled'))
                page.evaluate("document.getElementById('logout-form').submit()")
                page.wait_for_url(lambda url: '/profile/' not in url)
                login(page, base, 'push_browser_b')
                page.goto(base + '/profile/')
                expect(status).to_have_text(re.compile('Notifications enabled'))
                result = page.request.get(base + '/notifications/push/status/?endpoint=https%3A%2F%2Fexample.invalid%2Fpush%2Fbrowser-test').json()
                assert result['is_subscribed']
                run('shell', '-c', (
                    "from management.models import PushSubscription; "
                    "assert PushSubscription.objects.get(endpoint='https://example.invalid/push/browser-test').user.username == 'push_browser_b'"
                ), env=env)
                page.route('**/notifications/push/status/**', lambda route: route.abort())
                page.reload()
                expect(status).to_have_text('Something went wrong')
                expect(page.locator('.profile-page-wrapper .push-status-desc')).to_contain_text('Network error')
                page.unroute('**/notifications/push/status/**')
                page.locator('.profile-page-wrapper .push-btn-retry').click()
                expect(status).to_have_text('Notifications enabled')
                denied = browser.new_context()
                denied.add_init_script("Object.defineProperty(Notification, 'permission', {configurable:true,get:()=> 'denied'});")
                denied_page = denied.new_page()
                login(denied_page, base, 'push_browser_a')
                denied_page.goto(base + '/profile/')
                expect(denied_page.locator('.profile-page-wrapper .push-status-text')).to_have_text('Notifications blocked')
                denied.close()
                context.close()
                browser.close()
            print('PASS: Chrome configured setup, simulated permission/subscription, service worker, refresh, disable, account switch, network retry, denied state, seven viewports')
        finally:
            proc.terminate()
            proc.wait(timeout=10)
        missing = dict(env, WEBPUSH_VAPID_PUBLIC_KEY='', WEBPUSH_VAPID_PRIVATE_KEY='')
        proc = server(missing, port)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()
                context.add_init_script(MOCK_PUSH_MANAGER)
                page = context.new_page()
                login(page, base, 'push_browser_a')
                page.goto(base + '/profile/')
                status = page.locator('.profile-page-wrapper .push-status-text')
                expect(status).to_have_text('Server setup required')
                page.locator('.profile-page-wrapper .push-btn-retry').click()
                expect(status).to_have_text('Server setup required')
                assert page.evaluate('window.__permissionRequests') == 0
                context.close()
                browser.close()
            print('PASS: Chrome missing-VAPID state, retry without permission prompt')
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == '__main__':
    main()
