// Service Worker for GR-BBS

self.addEventListener('install', (event) => {
    console.log('Service Worker installing.');
    // self.skipWaiting(); // Forces the waiting service worker to become the active service worker.
});

self.addEventListener('activate', event => {
    console.log('Service Worker activating.');
});

self.addEventListener('fetch', (event) => {
    // For now, we just pass through network requests.
    // Caching strategies could be implemented here later.
    event.respondWith(fetch(event.request));
});

self.addEventListener('push', (event) => {
    console.log('[Service Worker] Push Received.');
    let data;
    try {
        data = event.data.json();
    } catch (e) {
        console.error('Push event data is not valid JSON', e);
        data = { title: 'GR-BBS', body: event.data.text() };
    }

    const title = data.title || 'GR-BBS Notification';
    const options = {
        body: data.body || 'You have a new notification.',
        icon: '/static/icons/icon-192x192.png',
        badge: '/static/icons/icon-96x96.png'
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    console.log('[Service Worker] Notification click Received.');
    event.notification.close();
    event.waitUntil(
        clients.openWindow('/')
    );
});