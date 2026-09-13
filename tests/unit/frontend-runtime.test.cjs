const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');

test('page disposal removes global listeners and executes registered cleanup', () => {
    const document = new EventTarget();
    const context = {window: {}, document, AbortController, fetch: () => {}};
    vm.runInNewContext(fs.readFileSync(path.join(root, 'static/js/fabro-page.js'), 'utf8'), context);
    const scope = context.window.fabroCreatePageScope();
    let events = 0;
    let cleanups = 0;
    scope.listen(document, 'click', () => events++);
    scope.listen(document, 'fabro:before-page-swap', () => cleanups++);
    document.dispatchEvent(new Event('click'));
    document.dispatchEvent(new Event('fabro:before-page-swap'));
    document.dispatchEvent(new Event('click'));
    scope.dispose();
    assert.equal(events, 1);
    assert.equal(cleanups, 1);
    assert.equal(scope.signal.aborted, true);
});

function uploadForm() {
    let submit;
    let requests = 0;
    const button = {disabled: false};
    const fileInput = {files: [{name: 'synthetic.png', type: 'image/png', size: 10}]};
    const form = {
        dataset: {directMediaUploads: 'true', signUploadUrl: '/synthetic/sign'},
        querySelector: selector => selector.includes('type="file"') ? fileInput
            : selector.includes('button') ? button : {value: 'synthetic'},
        querySelectorAll: () => [],
        addEventListener: (type, listener) => { if (type === 'submit') submit = listener; },
    };
    vm.runInNewContext(fs.readFileSync(path.join(root, 'management/static/management/js/direct_media_upload.js'), 'utf8'), {
        document: {getElementById: () => form},
        fetch: () => { requests++; return new Promise(() => {}); },
    });
    return {submit, button, requests: () => requests};
}

test('a second submit cannot bypass an in-progress direct upload', async () => {
    const form = uploadForm();
    form.submit({defaultPrevented: false, preventDefault() {}});
    let prevented = false;
    await form.submit({preventDefault() { prevented = true; }});
    assert.equal(prevented, true);
    assert.equal(form.requests(), 1);
    assert.equal(form.button.disabled, true);
});

test('client validation cancellation does not start an upload', async () => {
    const form = uploadForm();
    await form.submit({defaultPrevented: true});
    assert.equal(form.requests(), 0);
    assert.equal(form.button.disabled, false);
});
