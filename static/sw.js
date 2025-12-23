/* Service Worker for GR-BBS */

self.addEventListener('install', (event) => {
    console.log('Service Worker installing.');
    // self.skipWaiting(); // 待機中のService Workerを強制的にアクティブ
});

self.addEventListener('activate', event => {
    console.log('Service Worker activating.');
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
        badge: '/static/icons/icon-96x96.png', 
        // 通知自体にデータを添付する
        data: {
            url: data.data ? data.data.url : '/'
        }
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    console.log('[Service Worker] Notification click Received.');
    event.notification.close();
    const targetUrl = event.notification.data.url || '/';
 
    // このオリジンに属するウィンドウを探す
    event.waitUntil(
        clients.matchAll({
            type: "window",
            includeUncontrolled: true
        }).then((clientList) => {
            // 既に開いているウィンドウがあれば、それにフォーカスを当てる
            for (const client of clientList) {
                if (client.url && 'focus' in client) {
                    // メッセージを送信して、クライアント側でコマンドを実行させる
                    client.postMessage({ type: 'execute_shortcut', url: targetUrl }); 
                    return client.focus();
                }
            }
            // 開いているウィンドウがなければ、新しく開く
            return clients.openWindow(targetUrl);
        })
    );
});