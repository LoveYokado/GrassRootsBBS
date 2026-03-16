/* global PWA_URLS, textData */

let vapidPublicKey = null;

/**
 * Base64URLエンコードされた文字列をUint8Arrayに変換
 * @param {string} base64String 
 * @returns {Uint8Array}
 */
function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
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

/**
 * ユーザーをプッシュ通知に登録
 */
async function subscribeUser() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        console.error('Push Messaging is not supported');
        return;
    }

    try {
        // VAPID公開鍵をサーバーから取得
        if (!vapidPublicKey) {
            const response = await fetch(PWA_URLS.vapidPublicKey);
            const key = await response.json();
            vapidPublicKey = key.public_key;
        }

        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(vapidPublicKey)
        });

        // サブスクリプション情報をサーバーに送信
        await fetch(PWA_URLS.subscribe, {
            method: 'POST',
            body: JSON.stringify(subscription),
            headers: {
                'Content-Type': 'application/json'
            }
        });
        console.log('User is subscribed.');
    } catch (error) {
        console.error('Failed to subscribe the user: ', error);
        const pushStatus = document.getElementById('push-status');
        if (pushStatus) {
            pushStatus.textContent = textData?.terminal_ui?.settings_popup?.push_failed_message || 'Failed to enable notifications.';
        }
    }
}

/**
 * ユーザーのプッシュ通知登録を解除
 */
async function unsubscribeUser() {
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    if (subscription) {
        await subscription.unsubscribe();
        // サーバーに購読解除を通知
        await fetch(PWA_URLS.unsubscribe, {
            method: 'POST',
            body: JSON.stringify({ endpoint: subscription.endpoint }),
            headers: { 'Content-Type': 'application/json' }
        });
        console.log('User is unsubscribed.');
    }
}

if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register(PWA_URLS.serviceWorker);
    });
}