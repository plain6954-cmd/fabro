/* Fabro Leather Portal - Dedicated Web Push Service Worker */
'use strict';

// Install and activate immediately
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

// Push notification received
self.addEventListener('push', (event) => {
    let payload = {};
    if (event.data) {
        try {
            payload = event.data.json();
        } catch (e) {
            try {
                payload = { body: event.data.text() };
            } catch (err) {
                payload = {};
            }
        }
    }

    const title = (payload.title && String(payload.title).trim()) || 'Fabro Leather Portal';
    const body = (payload.body && String(payload.body).trim()) || 'You have a new update.';
    const icon = payload.icon || '/static/favicon.ico';
    const badge = payload.badge || '/static/favicon.ico';
    const tag = payload.tag || 'fabro-notification';
    const rawUrl = (payload.data && payload.data.url) ? payload.data.url : '/';

    // Strictly enforce same-origin path only
    let safeUrl = '/';
    try {
        const parsed = new URL(rawUrl, self.location.origin);
        if (parsed.origin === self.location.origin) {
            safeUrl = parsed.pathname + parsed.search + parsed.hash;
        }
    } catch (e) {
        safeUrl = '/';
    }

    const notificationOptions = {
        body: body,
        icon: icon,
        badge: badge,
        tag: tag,
        renotify: true,
        data: {
            url: safeUrl,
            timestamp: Date.now(),
        },
    };

    event.waitUntil(
        self.registration.showNotification(title, notificationOptions)
    );
});

// Notification click event
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    const notifData = event.notification.data || {};
    let targetPath = notifData.url || '/';

    // Verify same-origin URL security
    let targetUrl;
    try {
        targetUrl = new URL(targetPath, self.location.origin);
        if (targetUrl.origin !== self.location.origin) {
            targetUrl = new URL('/', self.location.origin);
        }
    } catch (e) {
        targetUrl = new URL('/', self.location.origin);
    }

    const targetHref = targetUrl.href;

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            // Find existing matching open window on the same origin
            for (const client of clientList) {
                if (client.url && 'focus' in client) {
                    try {
                        const clientUrl = new URL(client.url);
                        if (clientUrl.origin === self.location.origin) {
                            if (client.url === targetHref) {
                                return client.focus();
                            }
                            if ('navigate' in client) {
                                return client.navigate(targetHref).then((c) => c ? c.focus() : client.focus());
                            }
                            return client.focus();
                        }
                    } catch (e) {
                        // Continue checking other clients
                    }
                }
            }
            // If no suitable open window, open a new one
            if (self.clients.openWindow) {
                return self.clients.openWindow(targetHref);
            }
        })
    );
});
