// Ghost Worker Service Worker v2.4
// Keeps the compute node alive in the background, handles push notifications

const CACHE_NAME = 'ghost-worker-v2.4';

self.addEventListener('install', (event) => {
    console.log('[Ghost SW] Installed');
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    console.log('[Ghost SW] Activated');
    event.waitUntil(clients.claim());
});

// Keep-alive ping every 30 seconds
setInterval(() => {
    self.clients.matchAll().then(clients => {
        clients.forEach(client => {
            client.postMessage({ type: 'ping' });
        });
    });
}, 30000);

// Handle messages from the main page
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'inference_job') {
        // Forward to all clients (the main page handles actual inference)
        self.clients.matchAll().then(clients => {
            clients.forEach(client => {
                if (client.id !== event.source.id) {
                    client.postMessage(event.data);
                }
            });
        });
    }
});

// Background sync for offline queueing (if supported)
self.addEventListener('sync', (event) => {
    if (event.tag === 'ghost-sync') {
        event.waitUntil(
            self.clients.matchAll().then(clients => {
                clients.forEach(client => {
                    client.postMessage({ type: 'sync' });
                });
            })
        );
    }
});

// Push notification handler (for waking up the worker remotely)
self.addEventListener('push', (event) => {
    const data = event.data ? event.data.json() : {};
    console.log('[Ghost SW] Push received:', data);

    event.waitUntil(
        self.clients.matchAll({ type: 'window' }).then(clients => {
            if (clients.length === 0) {
                // No open windows — open one
                return self.clients.openWindow('/static/ghost_worker.html');
            }
            // Focus existing window
            clients[0].focus();
            clients[0].postMessage({ type: 'wake_up', data });
        })
    );
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    event.waitUntil(
        self.clients.openWindow('/static/ghost_worker.html')
    );
});
