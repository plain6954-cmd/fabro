/* Fabro Leather Portal - Web Push Client Manager */
(() => {
    'use strict';

    // Helper: convert url-safe base64 to Uint8Array for pushManager.subscribe
    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding)
            .replace(/-/g, '+')
            .replace(/_/g, '/');
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    // Helper: get CSRF token
    function getCsrfToken() {
        const tokenInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (tokenInput && tokenInput.value) {
            return tokenInput.value;
        }
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    // Capability check
    function getBrowserCapabilities() {
        const isSecure = window.isSecureContext || window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
        const hasServiceWorker = 'serviceWorker' in navigator;
        const hasPushManager = 'PushManager' in window;
        const hasNotification = 'Notification' in window;

        return {
            supported: isSecure && hasServiceWorker && hasPushManager && hasNotification,
            isSecureContext: isSecure,
            hasServiceWorker: hasServiceWorker,
            hasPushManager: hasPushManager,
            hasNotification: hasNotification,
        };
    }

    const state = {
        status: 'checking', // 'unsupported' | 'insecure-context' | 'permission-denied' | 'not-subscribed' | 'subscribed' | 'error'
        permission: 'default',
        subscription: null,
        vapidPublicKey: '',
        isConfigured: false,
        errorMessage: '',
        isLoading: false,
    };

    let swRegistrationPromise = null;
    let refreshPromise = null;

    async function fetchPushStatus(endpoint) {
        let response;
        try {
            const query = endpoint ? `?endpoint=${encodeURIComponent(endpoint)}` : '';
            response = await fetch(`/notifications/push/status/${query}`, {
                headers: { 'Accept': 'application/json' }, credentials: 'same-origin',
            });
        } catch (_) {
            throw new Error('Network error while checking browser notifications. Please retry.');
        }
        if (response.redirected || !response.ok) {
            throw new Error(response.status === 401 || response.status === 403 || response.redirected
                ? 'Please sign in again to manage browser notifications.'
                : 'Could not check browser notifications. Please retry.');
        }
        return response.json();
    }

    async function saveSubscription(sub) {
        const response = await fetch('/notifications/push/subscribe/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken(), 'Accept': 'application/json' },
            credentials: 'same-origin', body: JSON.stringify(sub.toJSON()),
        });
        if (response.redirected || !response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(response.redirected
                ? 'Please sign in again to manage browser notifications.'
                : data.error || 'Could not save this browser subscription. Please retry.');
        }
    }

    function usesCurrentVapidKey(sub) {
        const previous = sub && sub.options && sub.options.applicationServerKey;
        if (!previous) return true;
        const expected = urlBase64ToUint8Array(state.vapidPublicKey);
        const actual = new Uint8Array(previous);
        return actual.length === expected.length && actual.every((byte, index) => byte === expected[index]);
    }

    async function deactivateEndpoint(endpoint) {
        const response = await fetch('/notifications/push/unsubscribe/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken(), 'Accept': 'application/json' },
            credentials: 'same-origin', body: JSON.stringify({ endpoint }),
        });
        if (response.redirected || !response.ok) {
            throw new Error('Could not disable notifications on the server. Please retry.');
        }
    }

    // Get or register Service Worker safely
    async function getServiceWorkerRegistration() {
        if (!('serviceWorker' in navigator)) {
            return null;
        }
        if (!swRegistrationPromise) {
            swRegistrationPromise = navigator.serviceWorker.register('/sw.js', { scope: '/' })
                .catch(err => {
                    console.warn('[Fabro Push] Service worker registration error:', err);
                    swRegistrationPromise = null;
                    throw err;
                });
        }
        return swRegistrationPromise;
    }

    // Refresh push state comprehensively
    async function refreshPushNotificationState() {
        if (state.isLoading) return state;
        if (refreshPromise) return refreshPromise;
        refreshPromise = refreshPushNotificationStateOnce();
        try {
            return await refreshPromise;
        } finally {
            refreshPromise = null;
        }
    }

    async function refreshPushNotificationStateOnce() {
        const caps = getBrowserCapabilities();

        if (!caps.isSecureContext) {
            state.status = 'insecure-context';
            state.permission = 'denied';
            notifyStateChange();
            return state;
        }

        if (!caps.supported) {
            state.status = 'unsupported';
            state.permission = 'unsupported';
            notifyStateChange();
            return state;
        }

        state.permission = Notification.permission;

        if (state.permission === 'denied') {
            state.status = 'permission-denied';
            notifyStateChange();
            return state;
        }

        try {
            const reg = await getServiceWorkerRegistration();
            if (!reg) {
                state.status = 'unsupported';
                notifyStateChange();
                return state;
            }

            const currentSub = await reg.pushManager.getSubscription();
            state.subscription = currentSub;

            // Check backend registration status
            const data = await fetchPushStatus(currentSub && currentSub.endpoint);
            state.isConfigured = Boolean(data.configured);
            state.vapidPublicKey = data.vapid_public_key || '';
            if (!state.isConfigured) {
                state.status = 'server-unconfigured';
            } else if (currentSub && !usesCurrentVapidKey(currentSub)) {
                state.status = 'not-subscribed';
            } else if (currentSub && !data.is_subscribed && state.permission === 'granted') {
                // Existing browser subscriptions follow the signed-in account.
                await saveSubscription(currentSub);
                state.status = 'subscribed';
            } else {
                state.status = currentSub && data.is_subscribed ? 'subscribed' : 'not-subscribed';
            }
            state.errorMessage = '';
        } catch (err) {
            console.warn('[Fabro Push] State refresh error:', err);
            state.status = 'error';
            state.errorMessage = err.message || 'Error checking push status';
        }

        notifyStateChange();
        return state;
    }

    // Enable notifications on intentional user gesture
    async function enablePushNotifications() {
        if (state.isLoading) return false;
        state.isLoading = true;
        notifyStateChange();

        const caps = getBrowserCapabilities();
        if (!caps.supported) {
            state.isLoading = false;
            state.status = caps.isSecureContext ? 'unsupported' : 'insecure-context';
            notifyStateChange();
            return false;
        }

        try {
            // Confirm server configuration before showing a browser permission prompt.
            const config = await fetchPushStatus();
            state.isConfigured = Boolean(config.configured);
            state.vapidPublicKey = config.vapid_public_key || '';
            if (!state.isConfigured || !state.vapidPublicKey) {
                state.status = 'server-unconfigured';
                return false;
            }

            const perm = state.permission === 'granted' ? 'granted' : await Notification.requestPermission();
            state.permission = perm;

            if (perm !== 'granted') {
                state.status = perm === 'denied' ? 'permission-denied' : 'not-subscribed';
                state.isLoading = false;
                notifyStateChange();
                return false;
            }

            // 2. Ensure Service Worker is ready
            const reg = await getServiceWorkerRegistration();
            await navigator.serviceWorker.ready;

            // Subscribe with PushManager
            let sub = await reg.pushManager.getSubscription();
            if (sub && !usesCurrentVapidKey(sub)) {
                await deactivateEndpoint(sub.endpoint);
                await sub.unsubscribe();
                sub = null;
            }
            if (!sub) {
                const convertedKey = urlBase64ToUint8Array(state.vapidPublicKey);
                sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: convertedKey,
                });
            }

            state.subscription = sub;
            await saveSubscription(sub);

            state.status = 'subscribed';
            state.isLoading = false;
            notifyStateChange();
            return true;
        } catch (err) {
            console.error('[Fabro Push] Subscription error:', err);
            state.status = 'error';
            state.errorMessage = err.message || 'Subscription failed';
            state.isLoading = false;
            notifyStateChange();
            return false;
        } finally {
            state.isLoading = false;
            notifyStateChange();
        }
    }

    // Disable notifications
    async function disablePushNotifications() {
        if (state.isLoading) return false;
        state.isLoading = true;
        notifyStateChange();

        try {
            const reg = await getServiceWorkerRegistration();
            if (reg) {
                const sub = await reg.pushManager.getSubscription();
                if (sub) {
                    // Deactivate server ownership before dropping the browser endpoint.
                    await deactivateEndpoint(sub.endpoint);
                    await sub.unsubscribe();
                }
            }

            state.subscription = null;
            state.status = 'not-subscribed';
            state.isLoading = false;
            notifyStateChange();
            return true;
        } catch (err) {
            console.error('[Fabro Push] Unsubscribe error:', err);
            state.status = 'error';
            state.errorMessage = err.message || 'Failed to disable notifications';
            state.isLoading = false;
            notifyStateChange();
            return false;
        }
    }

    // Dispatch event and update DOM widgets
    function notifyStateChange() {
        const event = new CustomEvent('fabro:push-state-change', { detail: { ...state } });
        window.dispatchEvent(event);
        updatePushWidgets();
    }

    // Update any UI widgets present in page
    function updatePushWidgets() {
        const widgets = document.querySelectorAll('.fabro-push-widget');
        widgets.forEach((widget) => {
            const statusEl = widget.querySelector('.push-status-text');
            const descEl = widget.querySelector('.push-status-desc');
            const btnEnable = widget.querySelector('.push-btn-enable');
            const btnDisable = widget.querySelector('.push-btn-disable');
            const btnRetry = widget.querySelector('.push-btn-retry');
            const iconEl = widget.querySelector('.push-status-icon');

            if (!statusEl) return;

            // Reset buttons
            if (btnEnable) btnEnable.style.display = 'none';
            if (btnDisable) btnDisable.style.display = 'none';
            if (btnRetry) btnRetry.style.display = 'none';

            if (state.isLoading) {
                statusEl.textContent = 'Updating notifications...';
                if (descEl) descEl.textContent = 'Please wait...';
                if (iconEl) iconEl.className = 'fas fa-spinner fa-spin push-status-icon';
                return;
            }

            switch (state.status) {
                case 'subscribed':
                    statusEl.textContent = 'Notifications enabled';
                    if (descEl) descEl.textContent = 'You will receive browser notifications for assigned complaints and updates.';
                    if (iconEl) iconEl.className = 'fas fa-check-circle push-status-icon text-success';
                    if (btnDisable) btnDisable.style.display = 'inline-flex';
                    break;

                case 'not-subscribed':
                    statusEl.textContent = 'Enable notifications';
                    if (descEl) descEl.textContent = 'Get notified on this browser when complaints are assigned or require attention.';
                    if (iconEl) iconEl.className = 'fas fa-bell push-status-icon text-primary';
                    if (btnEnable) btnEnable.style.display = 'inline-flex';
                    break;

                case 'server-unconfigured':
                    statusEl.textContent = 'Server setup required';
                    if (descEl) descEl.textContent = 'Browser notifications are not configured on the server. Contact an administrator.';
                    if (iconEl) iconEl.className = 'fas fa-exclamation-triangle push-status-icon text-warning';
                    if (btnRetry) btnRetry.style.display = 'inline-flex';
                    break;

                case 'permission-denied':
                    statusEl.textContent = 'Notifications blocked';
                    if (descEl) descEl.textContent = 'Notifications are blocked in this browser. Enable them in your browser site settings.';
                    if (iconEl) iconEl.className = 'fas fa-ban push-status-icon text-danger';
                    break;

                case 'insecure-context':
                    statusEl.textContent = 'Secure connection required';
                    if (descEl) descEl.textContent = 'Browser notifications require HTTPS or a local development connection.';
                    if (iconEl) iconEl.className = 'fas fa-lock push-status-icon text-warning';
                    break;

                case 'unsupported':
                    statusEl.textContent = 'Notifications unavailable';
                    if (descEl) descEl.textContent = 'This browser or device does not support Web Push notifications.';
                    if (iconEl) iconEl.className = 'fas fa-info-circle push-status-icon text-secondary';
                    break;

                case 'error':
                    statusEl.textContent = 'Something went wrong';
                    if (descEl) descEl.textContent = state.errorMessage || 'Unable to update push notifications.';
                    if (iconEl) iconEl.className = 'fas fa-exclamation-triangle push-status-icon text-danger';
                    if (btnRetry) btnRetry.style.display = 'inline-flex';
                    break;

                default:
                    statusEl.textContent = 'Checking notifications...';
                    if (iconEl) iconEl.className = 'fas fa-bell push-status-icon';
                    break;
            }
        });
    }

    // Expose global API
    window.FabroPush = {
        refreshState: refreshPushNotificationState,
        enable: enablePushNotifications,
        disable: disablePushNotifications,
        getState: () => ({ ...state }),
    };

    // Auto-initialize on load and window state changes
    document.addEventListener('DOMContentLoaded', () => {
        refreshPushNotificationState();

        // Delegate click handlers
        document.addEventListener('click', (e) => {
            const enableBtn = e.target.closest('.push-btn-enable');
            if (enableBtn) {
                e.preventDefault();
                enablePushNotifications();
                return;
            }
            const disableBtn = e.target.closest('.push-btn-disable');
            if (disableBtn) {
                e.preventDefault();
                disablePushNotifications();
                return;
            }
            const retryBtn = e.target.closest('.push-btn-retry');
            if (retryBtn) {
                e.preventDefault();
                refreshPushNotificationState();
                return;
            }
        });
    });

    // Real-time refresh without wasteful 1s polling:
    window.addEventListener('focus', () => {
        refreshPushNotificationState();
    });

    window.addEventListener('pageshow', () => {
        refreshPushNotificationState();
    });

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            refreshPushNotificationState();
        }
    });
})();
