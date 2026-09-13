import { chromium } from '@playwright/test';
import fs from 'node:fs';
const outputDirectory = 'scratch/offline-audit';
fs.mkdirSync(outputDirectory, {recursive: true});
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({reducedMotion: 'reduce'});
const origin = 'http://127.0.0.1:8766';
// Never load remote assets, integrations, or real portal URLs in these checks.
await context.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.origin === origin || ['data:', 'blob:'].includes(url.protocol)
        ? route.continue() : route.abort();
});
const page = await context.newPage();
page.setDefaultTimeout(8000);
const errors = [];
const results = [];
page.on('pageerror', error => errors.push({url: page.url(), message: error.message}));
await page.goto(origin + '/login/');
await page.locator('[name=username]').fill('offline-admin');
await page.locator('[name=password]').fill('Offline-Test-123!');
await Promise.all([page.waitForURL(origin + '/'), page.locator('button[type=submit]').click()]);
const routes = ['/', '/complaints/', '/car-details/', '/approvals/', '/chat/', '/add-complaint/', '/add-sku/', '/master-settings/', '/profile/', '/admin_panel/'];
for (const width of [360, 390, 768, 834, 1366]) {
    await page.setViewportSize({width, height: 844});
    for (const route of routes) {
        const response = await page.goto(origin + route);
        await page.waitForTimeout(80);
        const metrics = await page.evaluate(() => ({
            overflow: document.documentElement.scrollWidth - innerWidth,
            title: document.title,
        }));
        results.push({width, route, status: response.status(), ...metrics});
    }
}
await page.setViewportSize({width: 390, height: 844});
await page.goto(origin + '/');
for (const label of ['Patterns', 'Approvals', 'Dashboard', 'Patterns', 'Approvals', 'Dashboard']) {
    await page.locator('.mobile-bottom-nav a').filter({hasText: label}).click();
    await page.waitForTimeout(350);
}
const interactions = [];
async function check(name, action) {
    try { await action(); interactions.push({name, passed: true}); }
    catch (error) { interactions.push({name, passed: false, error: error.message}); }
}
await check('Back and forward navigation restores page assets and interactions', async () => {
    await page.goto(origin + '/');
    await page.locator('.mobile-bottom-nav a').filter({hasText: 'Patterns'}).click();
    const iconContent = await page.locator('.pattern-add-btn i').evaluate(el => getComputedStyle(el, '::before').content);
    if (!iconContent || iconContent === 'none' || iconContent === 'normal') throw Error('Shared navigation icons lost their stylesheet');
    await page.locator('#mobileFiltersBtn').waitFor();
    await page.locator('.mobile-bottom-nav a').filter({hasText: 'Approvals'}).click();
    await page.locator('#mobileFiltersTrigger').waitFor();
    await page.goBack();
    await page.locator('#mobileFiltersBtn').click();
    if (!await page.locator('head link[href*="pattern-master.css"]').count()) throw Error('History restored Pattern Master without its stylesheet');
    await page.keyboard.press('Escape');
    await page.goForward();
    await page.locator('#mobileFiltersTrigger').click();
    await page.keyboard.press('Escape');
});
await check('Pattern cards expand and filters open after repeat navigation', async () => {
    await page.locator('.mobile-bottom-nav a').filter({hasText: 'Patterns'}).click();
    await page.locator('.pattern-card-details-toggle').first().click();
    if (await page.locator('.pattern-card-details-toggle').first().getAttribute('aria-expanded') !== 'true') throw Error('Details did not expand');
    await page.locator('#mobileFiltersBtn').click();
    await page.locator('#mfBrand').selectOption({label: 'OFFLINE BRAND'});
    await page.locator('#mfApplyBtn').click();
    if (await page.locator('#mobileFiltersSheet').evaluate(el => el.classList.contains('is-open'))) throw Error('Filter sheet stayed open');
    await page.screenshot({path: outputDirectory + '/offline-pattern-mobile.png'});
});
await check('Approval filter sheet opens and closes by Escape', async () => {
    await page.locator('.mobile-bottom-nav a').filter({hasText: 'Approvals'}).click();
    await page.locator('#mobileFiltersTrigger').click();
    await page.locator('#filtersSheetCloseBtn').waitFor({state: 'visible'});
    await page.keyboard.press('Escape');
    if (await page.locator('body').evaluate(el => el.classList.contains('sheet-open'))) throw Error('Body remained locked');
});
await check('Repeated add-form navigation and thumbnail removal', async () => {
    for (let i = 0; i < 2; i++) {
        await page.evaluate(() => htmx.ajax('GET', '/add-complaint/', {target:'#app-content', swap:'innerHTML'}));
        await page.locator('#media_files').waitFor();
        await page.locator('#media_files').setInputFiles({name: 'synthetic.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6EhsAAAAASUVORK5CYII=', 'base64')});
        await page.locator('.media-remove-btn').first().click();
        const count = await page.locator('#media_files').evaluate(el => el.files.length);
        if (count !== 0) throw Error('Removed attachment remained in the file input');
        await page.locator('.mobile-bottom-nav a').filter({hasText: 'Dashboard'}).click();
        await page.locator('.dashboard-container').waitFor();
    }
});
await check('Admin tabs remain contained on a small phone', async () => {
    await page.setViewportSize({width: 360, height: 844});
    await page.goto(origin + '/admin_panel/');
    for (const tab of ['users','skus','brands','master','sessions','logs','dashboard']) {
        await page.locator('#side-' + tab).click();
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
        if (overflow > 1) throw Error(`${tab} overflows by ${overflow}px`);
    }
    await page.screenshot({path: outputDirectory + '/offline-admin-mobile.png'});
});
await check('Mobile chat directory does not poll hidden conversations', async () => {
    const calls = [];
    const listener = request => { if (request.url().includes('/api/chat/messages/')) calls.push(request.url()); };
    page.on('request', listener);
    await page.goto(origin + '/chat/');
    await page.waitForTimeout(250);
    if (calls.length) throw Error('Hidden conversation was read');
    await page.locator('.chat-user-item').first().click();
    await page.waitForTimeout(250);
    if (!calls.length) throw Error('Opening a conversation did not fetch its messages');
    await page.locator('#chat-back-btn').click();
    page.off('request', listener);
});
fs.writeFileSync(outputDirectory + '/offline-browser-results.json', JSON.stringify({results, interactions, errors}, null, 2));
console.log(JSON.stringify({checks: results.length, issues: results.filter(r => r.status !== 200 || r.overflow > 1), interactions, errors}, null, 2));
await browser.close();
process.exitCode = Number(errors.length > 0 || interactions.some(r => !r.passed) || results.some(r => r.status !== 200 || r.overflow > 1));
