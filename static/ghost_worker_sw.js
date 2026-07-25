// ghost_worker_sw.js
// Service Worker for background ghost worker persistence.

const CACHE_NAME = "ghost-worker-v1";
const urlsToCache = ["/ghost", "/static/ghost_worker.html"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(urlsToCache))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});

self.addEventListener("sync", (event) => {
  if (event.tag === "ghost-sync") {
    event.waitUntil(syncJobs());
  }
});

async function syncJobs() {
  const clients = await self.clients.matchAll({ type: "window" });
  clients.forEach((client) => {
    client.postMessage({ type: "SYNC_JOBS" });
  });
}

self.addEventListener("periodicsync", (event) => {
  if (event.tag === "ghost-periodic") {
    event.waitUntil(syncJobs());
  }
});