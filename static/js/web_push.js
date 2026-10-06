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
            const endpointParam = currentSub ? `?endpoint=${encodeURIComponent(currentSub.endpoint)}` : '';
            const statusResp = await fetch(`/notifications/push/status/${endpointParam}`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
            });

            if (statusResp.ok) {
                const data = await statusResp.json();
                state.isConfigured = Boolean(data.configured);
                state.vapidPublicKey = data.vapid_public_key || '';

                if (currentSub && data.is_subscribed) {
                    state.status = 'subscribed';
                } else {
                    state.status = 'not-subscribed';
                }
            } else {
                state.status = currentSub ? 'subscribed' : 'not-subscribed';
            }
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
            // 1. Request permission
            const perm = await Notification.requestPermission();
            state.permission = perm;

            if (perm !== 'granted') {
                state.status = 'permission-denied';
                state.isLoading = false;
                notifyStateChange();
                return false;
            }

            // 2. Ensure Service Worker is ready
            const reg = await getServiceWorkerRegistration();
            await navigator.serviceWorker.ready;

            // 3. Fetch VAPID public key if not cached
            if (!state.vapidPublicKey) {
                const statusResp = await fetch('/notifications/push/status/', {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' },
                    credentials: 'same-origin',
                });
                if (statusResp.ok) {
                    const statusData = await statusResp.json();
                    state.vapidPublicKey = statusData.vapid_public_key || '';
                }
            }

            if (!state.vapidPublicKey) {
                throw new Error('Web Push is not configured on the server.');
            }

            // 4. Subscribe with PushManager
            let sub = await reg.pushManager.getSubscription();
            if (!sub) {
                const convertedKey = urlBase64ToUint8Array(state.vapidPublicKey);
                sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: convertedKey,
                });
            }

            state.subscription = sub;
            const subData = sub.toJSON();

            // 5. Send subscription to Django backend
            const csrfToken = getCsrfToken();
            const subscribeResp = await fetch('/notifications/push/subscribe/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'Accept': 'application/json',
                },
                credentials: 'same-origin',
                body: JSON.stringify(subData),
            });

            if (!subscribeResp.ok) {
                const errData = await subscribeResp.json().catch(() => ({}));
                throw new Error(errData.error || 'Failed to save subscription on server.');
            }

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
        }
    }

    // Disable notifications
    async function disablePushNotifications() {
        state.isLoading = true;
        notifyStateChange();

        try {
            const reg = await getServiceWorkerRegistration();
            if (reg) {
                const sub = await reg.pushManager.getSubscription();
                if (sub) {
                    const endpoint = sub.endpoint;
                    // Unsubscribe browser PushManager
                    await sub.unsubscribe().catch(() => {});

                    // Notify Django backend
                    const csrfToken = getCsrfToken();
                    await fetch('/notifications/push/unsubscribe/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken,
                            'Accept': 'application/json',
                        },
                        credentials: 'same-origin',
                        body: JSON.stringify({ endpoint: endpoint }),
                    }).catch(() => {});
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
                enablePushNotifications();
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
