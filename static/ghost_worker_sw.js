// Service Worker for Termux Ghost Worker
// Keeps the compute node alive in the background

self.addEventListener('install', (event) => {
    console.log('Ghost Worker Service Worker installed');
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    console.log('Ghost Worker Service Worker activated');
    event.waitUntil(clients.claim());
});

self.addEventListener('message', (event) => {
    console.log('Message received in SW:', event.data);
});

// Keep-alive ping every 30 seconds
setInterval(() => {
    self.clients.matchAll().then(clients => {
        clients.forEach(client => {
            client.postMessage({ type: 'ping' });
        });
    });
}, 30000);
