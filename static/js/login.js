function base64urlToBuffer(base64urlString) {
    const base64 = base64urlString.replace(/-/g, '+').replace(/_/g, '/'); 
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray.buffer;
}

function bufferToBase64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let str = ''; 
    for (const charCode of bytes) {
        str += String.fromCharCode(charCode);
    }
    const base64 = window.btoa(str);
    return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

async function startPasskeyLogin(username = '') {
    const loginButton = document.getElementById('login-button');
    const passkeyLoginButton = document.getElementById('passkey-login-btn');
    loginButton.disabled = true;
    passkeyLoginButton.disabled = true;
    loginButton.textContent = 'お待ち下さい...';

    let options;
    try {
        // ユーザー名が空文字列の場合、サーバーはDiscoverable Credential用のオプションを返す
        const resp = await fetch(LOGIN_URLS.passkeyLoginOptions, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username.toUpperCase() }),
        });
        if (!resp.ok) {
            const errorData = await resp.json();
            throw new Error(errorData.error || 'Failed to get login options.');
        } 
        options = await resp.json();
        loginButton.disabled = false;
        passkeyLoginButton.disabled = false;
    } catch (e) {
        alert(`Passkeyオプションの取得に失敗しました: ${e.message}`);
        loginButton.disabled = false;
        loginButton.textContent = 'Login';
        passkeyLoginButton.disabled = false;
        return;
    }

    options.challenge = base64urlToBuffer(options.challenge);
    if (options.allowCredentials) {
        for (let cred of options.allowCredentials) {
            cred.id = base64urlToBuffer(cred.id);
        }
    }

    let credential;
    try {
        credential = await navigator.credentials.get({ publicKey: options });
    } catch (e) {
        if (e.name !== "NotAllowedError") {
            alert(`Passkey認証に失敗しました: ${e.name}`);
        }
        loginButton.disabled = false;
        loginButton.textContent = 'Login';
        passkeyLoginButton.disabled = false;
        return;
    }

    const credentialForServer = {
        id: credential.id,
        rawId: bufferToBase64url(credential.rawId),
        response: {
            clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
            authenticatorData: bufferToBase64url(credential.response.authenticatorData),
            userHandle: credential.response.userHandle ? bufferToBase64url(credential.response.userHandle) : null,
            signature: bufferToBase64url(credential.response.signature),
        },
        type: credential.type,
    };

    try {
        const verificationResp = await fetch(LOGIN_URLS.passkeyVerifyLogin, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(credentialForServer),
        });
        const verificationJSON = await verificationResp.json();
        if (verificationJSON && verificationJSON.verified) {
            window.location.href = LOGIN_URLS.index; // ログイン成功

        } else {
            throw new Error(verificationJSON.error || "サーバーでの認証に失敗しました。");
        }
    } catch (e) {
        alert(`Passkey認証に失敗しました: ${e.message}`);
        loginButton.disabled = false;
        passkeyLoginButton.disabled = false;
        loginButton.textContent = 'Login';
    }
}

// イベントリスナーの登録 
document.addEventListener('DOMContentLoaded', () => {
    if (PASSKEY_USERNAME) {
        startPasskeyLogin(PASSKEY_USERNAME);
    }

    document.getElementById('passkey-login-btn').addEventListener('click', async () => {
        await startPasskeyLogin();
    });
});