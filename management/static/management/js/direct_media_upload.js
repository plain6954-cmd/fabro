(function () {
    'use strict';

    const form = document.getElementById('complaint-form');
    if (!form || form.dataset.directMediaUploads !== 'true') {
        return;
    }

    const fileInput = form.querySelector('input[type="file"][name="media_files"]');
    const batchInput = form.querySelector('input[name="media_upload_batch"]');
    const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
    const submitButton = form.querySelector('button[type="submit"]');
    let uploadInProgress = false;

    function notify(message, type) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type || 'error');
        } else {
            window.alert(message);
        }
    }

    async function responseJson(response) {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || `Upload request failed (${response.status}).`);
        }
        return data;
    }

    async function createSignedUpload(file, deleteMediaIds) {
        const response = await fetch(form.dataset.signUploadUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfInput.value,
            },
            body: JSON.stringify({
                batch_id: batchInput.value,
                filename: file.name,
                size: file.size,
                content_type: file.type,
                delete_media_ids: deleteMediaIds,
            }),
        });
        return responseJson(response);
    }

    async function uploadDirectly(file, ticket) {
        const body = new FormData();
        body.append('cacheControl', '3600');
        body.append('', file, file.name);
        const response = await fetch(ticket.signed_url, {
            method: 'PUT',
            headers: {'x-upsert': 'false'},
            body,
        });
        if (!response.ok) {
            const detail = await response.text().catch(() => '');
            throw new Error(`Supabase rejected ${file.name} (${response.status}). ${detail}`.trim());
        }
    }

    async function discardUploads(uploadIds) {
        if (!uploadIds.length) {
            return;
        }
        await fetch(form.dataset.discardUploadUrl, {
            method: 'POST',
            credentials: 'same-origin',
            keepalive: true,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfInput.value,
            },
            body: JSON.stringify({upload_ids: uploadIds}),
        }).catch(() => {});
    }

    form.addEventListener('submit', async function (event) {
        const files = Array.from(fileInput?.files || []);
        if (!files.length || uploadInProgress) {
            return;
        }
        event.preventDefault();
        uploadInProgress = true;
        if (submitButton) {
            submitButton.disabled = true;
        }

        const deleteMediaIds = Array.from(
            form.querySelectorAll('input[name="delete_media"]:checked')
        ).map(input => input.value);
        const uploadIds = [];
        try {
            for (const file of files) {
                const ticket = await createSignedUpload(file, deleteMediaIds);
                uploadIds.push(ticket.upload_id);
                await uploadDirectly(file, ticket);
            }
            uploadIds.forEach(uploadId => {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'media_upload_ids';
                input.value = uploadId;
                form.appendChild(input);
            });

            // This is the critical Vercel bypass: remove File objects before the
            // final Django request so it contains only upload IDs and form data.
            fileInput.value = '';
            HTMLFormElement.prototype.submit.call(form);
        } catch (error) {
            await discardUploads(uploadIds);
            uploadInProgress = false;
            if (submitButton) {
                submitButton.disabled = false;
            }
            const overlay = document.getElementById('loadingOverlay');
            if (overlay) {
                overlay.style.display = 'none';
            }
            notify(error.message || 'Unable to upload complaint media.', 'error');
        }
    });
})();
