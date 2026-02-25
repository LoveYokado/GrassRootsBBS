/*
SPDX-FileCopyrightText: 2025 mid.yuki (LoveYokado)
SPDX-License-Identifier: MIT
*/ 

/**
 * Base64URLエンコードされた文字列をArrayBufferに変換します。
 * @param {string} base64urlString - Base64URL文字列
 * @returns {ArrayBuffer}
 */
function base64urlToBuffer(base64urlString) {
    const base64 = base64urlString.replace(/-/g, '+').replace(/_/g, '/'); 
    const rawData = window.atob(base64); 
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray.buffer;
}

/** 
 * ArrayBufferをBase64URLエンコードされた文字列に変換します。 
 * @param {ArrayBuffer} buffer - 変換するArrayBuffer
 * @returns {string}
 */
function bufferToBase64url(buffer) { 
    const bytes = new Uint8Array(buffer);
    let str = '';
    for (const charCode of bytes) {
        str += String.fromCharCode(charCode);
    }
    const base64 = window.btoa(str);
    return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

const themes = { 
    default: {
        background: '#000000',
        foreground: '#FFFFFF',
        cursor: '#FFFFFF',
        fkey_bg: '#FFFFFF',
        fkey_fg: '#000000',
        text_shadow_glow: '-1px 0 1px rgba(255,0,0,0.3), 1px 0 1px rgba(0,255,0,0.3), 0 0 3px rgba(255,255,255,0.4)',
        black: '#000000',
        red: '#FF0000',
        green: '#00FF00',
        yellow: '#FFFF00',
        blue: '#0000FF',
        magenta: '#FF00FF',
        cyan: '#00FFFF',
        white: '#FFFFFF',
        brightBlack: '#7F7F7F',
        brightRed: '#FF0000',
        brightGreen: '#00FF00',
        brightYellow: '#FFFF00',
        brightBlue: '#0000FF',
        brightMagenta: '#FF00FF',
        brightCyan: '#00FFFF',
        brightWhite: '#FFFFFF'
    },
    green: {
        background: '#000000',
        foreground: '#00FF00',
        cursor: '#00FF00',
        fkey_bg: '#00FF00',
        fkey_fg: '#000000',
        text_shadow_glow: '0 0 5px rgba(0, 255, 0, 0.5), 0 0 10px rgba(0, 255, 0, 0.3)',
        // 全てのANSIカラーをテーマ色で上書き
        black: '#00FF00',
        red: '#00FF00',
        green: '#00FF00',
        yellow: '#00FF00',
        blue: '#00FF00',
        magenta: '#00FF00',
        cyan: '#00FF00',
        white: '#00FF00',
        brightBlack: '#00FF00',
        brightRed: '#00FF00',
        brightGreen: '#00FF00',
        brightYellow: '#00FF00',
        brightBlue: '#00FF00',
        brightMagenta: '#00FF00',
        brightCyan: '#00FF00',
        brightWhite: '#00FF00'
    },
    amber: {
        background: '#1a1000',
        foreground: '#FFB000',
        cursor: '#FFB000',
        fkey_bg: '#FFB000', // prettier-ignore
        fkey_fg: '#1a1000',
        text_shadow_glow: '0 0 5px rgba(255, 176, 0, 0.5), 0 0 10px rgba(255, 176, 0, 0.3)',
        // 全てのANSIカラーをテーマ色で上書き
        black: '#FFB000',
        red: '#FFB000',
        green: '#FFB000',
        yellow: '#FFB000',
        blue: '#FFB000',
        magenta: '#FFB000',
        cyan: '#FFB000',
        white: '#FFB000',
        brightBlack: '#FFB000',
        brightRed: '#FFB000',
        brightGreen: '#FFB000',
        brightYellow: '#FFB000',
        brightBlue: '#FFB000',
        brightMagenta: '#FFB000',
        brightCyan: '#FFB000',
        brightWhite: '#FFB000'
    }
};

const themeMap = { default: 0, green: 1, amber: 2 };
const fontMap = { 'M PLUS 1m': 0, 'M PLUS 1 Code': 1, 'IBM Plex Mono': 2, DotGothic16: 3 };
const speedMap = { full: 0, 9600: 1, 4800: 2, 2400: 3, 300: 4 };
const effectMap = { bezel: 0, blur: 1, scanline: 2 };
const pushMap = { on: 1, off: 0 };
const fontsizeMap = { 12: 0, 16: 1, 20: 2, 24: 3 };

// 逆引きマップ
const themeMapReverse = Object.fromEntries(Object.entries(themeMap).map(([k, v]) => [v, k]));
const fontMapReverse = Object.fromEntries(Object.entries(fontMap).map(([k, v]) => [v, k]));
const speedMapReverse = Object.fromEntries(Object.entries(speedMap).map(([k, v]) => [v, k]));
const fontsizeMapReverse = Object.fromEntries(Object.entries(fontsizeMap).map(([k, v]) => [v, k]));
const pushMapReverse = Object.fromEntries(Object.entries(pushMap).map(([k, v]) => [v, k]));

let isDipSwitchUpdating = false; // DIPスイッチ操作による再帰呼び出しを防ぐフラグ

const dynamicGlowStyle = document.getElementById('dynamic-glow-style');

function applyTheme(themeName) {
    const theme = themes[themeName] || themes.default;
    term.options.theme = theme;

    document.body.classList.remove('theme-default', 'theme-green', 'theme-amber');
    document.body.classList.add(`theme-${themeName}`);

    // モバイル操作パネルのテーマクラスを更新
    const mobileControls = document.getElementById('mobile-bbs-controls');
    const chatControls = document.getElementById('mobile-chat-controls');
    const userprefControls = document.getElementById('mobile-userpref-controls');
    const mailControls = document.getElementById('mobile-mail-controls');
    const bbsEntryControls = document.getElementById('mobile-bbs-entry-controls');
    const topMenuControls = document.getElementById('mobile-top-menu-controls');
    const pluginMenuControls = document.getElementById('mobile-plugin-menu-controls'); 

    [mobileControls, chatControls, userprefControls, mailControls, bbsEntryControls, topMenuControls, pluginMenuControls].forEach(controls => {
        if (controls) {
            controls.classList.remove('theme-default', 'theme-green', 'theme-amber');
            controls.classList.add(`theme-${themeName}`);
        }
    });

    if (dynamicGlowStyle) { 
        dynamicGlowStyle.innerHTML = `#terminal.blur-effect { text-shadow: ${theme.text_shadow_glow || 'none'}; }`;
    }

    const fkeys = document.querySelectorAll('.f-key');
    fkeys.forEach(key => {
        key.style.backgroundColor = theme.fkey_bg;
        key.style.color = theme.fkey_fg;
    });

    // マルチラインエディタのカラーボタンの色を更新
    const colorBtns = document.querySelectorAll('.ansi-btn[data-ansi-color-name]');
    colorBtns.forEach(btn => {
        const colorName = btn.dataset.ansiColorName;
        if (theme[colorName]) {
            btn.style.color = theme[colorName];
        }
    });

    // テーマに応じてANSIカラーボタンの表示/非表示を切り替えます。 
    const ansiColorButtons = document.getElementById('ansi-color-buttons');
    if (ansiColorButtons) {
        if (themeName === 'green' || themeName === 'amber') {
            ansiColorButtons.style.display = 'none';
        } else {
            ansiColorButtons.style.display = 'block';
        }
    }
    localStorage.setItem('terminalTheme', themeName);
    updateThemeButtons(themeName);
    if (!isDipSwitchUpdating) updateDipSwitches('theme', themeName); 
}

function applyFont(fontName) {
    const fontFamily = `"${fontName}", "Courier New", monospace`;
    term.options.fontFamily = fontFamily;

    localStorage.setItem('terminalFont', fontName); 
    updateFontButtons(fontName);
    if (!isDipSwitchUpdating) updateDipSwitches('font', fontName); 
    setTimeout(() => updateTerminalLayout(), 0);
}

function applyFontSize(size) {
    const baseSize = parseInt(size, 10);

    term.options.fontSize = baseSize;

    document.body.style.fontSize = `${baseSize}px`;

    const isMobile = window.matchMedia('(max-width: 992px)').matches;
    const storageKey = isMobile ? 'terminalFontSizeMobile' : 'terminalFontSizePC';
    localStorage.setItem(storageKey, size);

    updateFontSizeButtons(size);
    if (!isDipSwitchUpdating) updateDipSwitches('fontsize', size);
    setTimeout(() => updateTerminalLayout(), 0);
}

function updateFontSizeButtons(size) {
    document.querySelectorAll('#fontsize-selector button').forEach(btn => btn.classList.remove('active'));
    const activeButton = document.querySelector(`#fontsize-selector button[data-size="${size}"]`);
    if (activeButton) activeButton.classList.add('active');
}

function applySpeed(speedName) {
    socket.emit('set_speed', speedName);
    localStorage.setItem('terminalSpeed', speedName);
    updateSpeedButtons(speedName); 
    if (!isDipSwitchUpdating) updateDipSwitches('speed', speedName); 
}

const effectStates = {
    bezel: true,
    blur: false,
    scanline: false
};

function applyEffect(effectName, isActive) {
    const monitorChassis = document.querySelector('.monitor-chassis');
    const monitorScreen = document.querySelector('.monitor-screen');
    const terminalElement = document.getElementById('terminal');

    switch (effectName) {
        case 'bezel':
            monitorChassis.classList.toggle('bezel-off', !isActive);
            break;
        case 'blur':
            terminalElement.classList.toggle('blur-effect', isActive);
            break;
        case 'scanline':
            monitorScreen.classList.toggle('scanline-effect', isActive);
            break;
    }
}

function toggleEffect(effectName) {
    effectStates[effectName] = !effectStates[effectName];
    applyEffect(effectName, effectStates[effectName]);
    localStorage.setItem('effectStates', JSON.stringify(effectStates));
    updateEffectButtons();
    if (!isDipSwitchUpdating) updateDipSwitches('effect');
    setTimeout(updateTerminalLayout, 50); 
}

function updateEffectButtons() {
    document.querySelectorAll('.effect-btn').forEach(button => {
        const effectName = button.dataset.effect;
        if (effectStates[effectName]) {
            button.classList.add('active');
        } else {
            button.classList.remove('active');
        }
    });
}

function updateThemeButtons(themeName) {
    document.querySelectorAll('#theme-selector button').forEach(btn => btn.classList.remove('active'));
    const activeButton = document.querySelector(`#theme-selector button[data-theme="${themeName}"]`);
    if (activeButton) activeButton.classList.add('active');
}

function updateFontButtons(fontName) {
    document.querySelectorAll('#font-selector button').forEach(btn => btn.classList.remove('active'));
    const activeButton = document.querySelector(`#font-selector button[data-font="${fontName}"]`);
    if (activeButton) activeButton.classList.add('active');
}

function updateSpeedButtons(speedName) {
    document.querySelectorAll('#speed-selector button').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`#speed-selector button[data-speed="${speedName}"]`).classList.add('active');
}

function updateDipSwitches(groupName, value) {
    let numericValue;
    if (groupName === 'theme') {
        numericValue = themeMap[value];
    } else if (groupName === 'font') {
        numericValue = fontMap[value];
    } else if (groupName === 'speed') {
        numericValue = speedMap[value]; 
    } else if (groupName === 'fontsize') {
        numericValue = fontsizeMap[value]; 
    } else if (groupName === 'effect') {
        // エフェクトはビットごとのON/OFFなので特別に扱います
        const switches = document.querySelectorAll(`.dip-switch-group[data-group="effect"] input[type="checkbox"]`);
        switches.forEach(sw => {
            const effectName = Object.keys(effectMap).find(key => effectMap[key] === parseInt(sw.dataset.bit));
            sw.checked = effectStates[effectName];
        });
        return;
    } else if (groupName === 'push') {
        // エフェクトはビットごとのON/OFFなので特別に扱います
        const switches = document.querySelectorAll(`.dip-switch-group[data-group="effect"] input[type="checkbox"]`);
        switches.forEach(sw => {
            const effectName = Object.keys(effectMap).find(key => effectMap[key] === parseInt(sw.dataset.bit));
            sw.checked = effectStates[effectName];
        });
        return;
    }

    if (numericValue === undefined) return;

    const switches = document.querySelectorAll(`.dip-switch-group[data-group="${groupName}"] input[type="checkbox"]`);
    switches.forEach(sw => {
        const bit = parseInt(sw.dataset.bit);
        sw.checked = (numericValue & (1 << bit)) !== 0;
    });
}

const isMobileForTermInit = window.matchMedia('(max-width: 992px)').matches; 
const term = new Terminal({
    cursorBlink: true,
    fontSize: 16, 
    scrollback: 1000, // ターミナルのスクロールバックを1000行に設定
});
const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);

term.open(document.getElementById('terminal'));

function updateTerminalLayout() {
    const chassis = document.querySelector('.monitor-chassis');
    const screenContainer = document.querySelector('.monitor-screen'); 
    const terminalContainer = document.getElementById('terminal');
    const isMobile = window.matchMedia('(max-width: 992px)').matches;
    const isFullscreen = chassis.classList.contains('fullscreen');

    if (!isFullscreen) {
        screenContainer.style.width = ''; // フルスクリーンでなければ幅をリセット
    }

    if (isMobile) {
        try {
            fitAddon.fit();
        } catch (e) {
            console.error('fitAddon.fit() failed:', e);
        }
    } else if (isFullscreen) {
        // デスクトップのフルスクリーンモード (現在未使用)
        if (term.renderer && term.renderer.dimensions && term.renderer.dimensions.actualCellHeight > 0) {
            const cellHeight = term.renderer.dimensions.actualCellHeight;
            const cellWidth = term.renderer.dimensions.actualCellWidth;

            const fkeys = document.getElementById('function-keys-container');
            const fkeysHeight = fkeys.offsetHeight;
            const fkeysMargin = parseFloat(window.getComputedStyle(fkeys).marginTop);
            const screenStyle = window.getComputedStyle(screenContainer);
            const screenPaddingVertical = parseFloat(screenStyle.paddingTop) + parseFloat(screenStyle.paddingBottom);
            const availableHeightForTerm = window.innerHeight - fkeysHeight - fkeysMargin - screenPaddingVertical;
            const newRows = Math.floor(availableHeightForTerm / cellHeight);

            const termWidth = 80 * cellWidth;
            const screenPaddingHorizontal = parseFloat(screenStyle.paddingLeft) + parseFloat(screenStyle.paddingRight);
            screenContainer.style.width = `${termWidth + screenPaddingHorizontal}px`;

            term.resize(80, newRows);
        } else {
            setTimeout(updateTerminalLayout, 50);
        }
    } else {
        term.resize(80, 25); // デスクトップの通常表示
    }
}

const socket = io(); 

const attachmentInput = document.getElementById('attachment-input');

attachmentInput.addEventListener('change', () => {
    if (attachmentInput.files.length > 0) {
        const file = attachmentInput.files[0];

        const reader = new FileReader();
        reader.onload = (e) => {
            socket.emit('upload_attachment', {
                filename: file.name,
                data: e.target.result
            });
        };
        reader.onerror = (e) => {
            console.error('File reading error:', e);
        };
        reader.readAsArrayBuffer(file);

    } else {
        socket.emit('clear_pending_attachment'); // ファイル選択がキャンセルされた場合
    }
});
// 
socket.on('attachment_upload_success', (data) => {
    console.log(`Upload complete: ${data.original_filename}`);
});

socket.on('attachment_upload_error', (data) => {
    console.error(`Upload error: ${data.message}`); 
    attachmentInput.value = '';
});
// --- ポップアップ関連の要素取得 --- 

const popupOverlay = document.getElementById('popup-overlay');
const popupWindow = document.getElementById('popup-window');
const popupCloseBtn = document.getElementById('popup-close-btn');

const lineEditorOverlay = document.getElementById('line-editor-overlay');
const lineEditorWindow = document.getElementById('line-editor-window');
const lineEditorCloseBtn = document.getElementById('line-editor-close-btn');
const lineEditorInput = document.getElementById('line-editor-input');
const lineEditorInsertBtn = document.getElementById('line-editor-insert-btn');
const lineEditorCancelBtn = document.getElementById('line-editor-cancel-btn');
const lineEditorHistory = [];
let historyIndex = -1;

const multilineEditorOverlay = document.getElementById('multiline-editor-overlay');
const multilineEditorWindow = document.getElementById('multiline-editor-window');
const multilineEditorCloseBtn = document.getElementById('multiline-editor-close-btn');
const multilineEditorInput = document.getElementById('multiline-editor-input');
const multilineEditorInsertBtn = document.getElementById('multiline-editor-insert-btn');
const multilineEditorCancelBtn = document.getElementById('multiline-editor-cancel-btn');
const ansiControls = document.getElementById('ansi-controls');

const logViewerOverlay = document.getElementById('log-viewer-overlay');
const logViewerWindow = document.getElementById('log-viewer-window');
const logViewerCloseBtn = document.getElementById('log-viewer-close-btn');
const logContentDisplay = document.getElementById('log-content-display');
const logFilesList = document.getElementById('log-files-list');

const bbsListOverlay = document.getElementById('bbs-list-overlay');
const bbsListWindow = document.getElementById('bbs-list-window');
const bbsListCloseBtn = document.getElementById('bbs-list-close-btn');
const bbsStationsList = document.getElementById('bbs-stations-list');

const imagePopupOverlay = document.getElementById('image-popup-overlay');
const imagePopupWindow = document.getElementById('image-popup-window');
const imagePopupImg = document.getElementById('image-popup-img');
const bbsDetailName = document.getElementById('bbs-detail-name');
const bbsDetailDescription = document.getElementById('bbs-detail-description');
const bbsListJumpBtn = document.getElementById('bbs-list-jump-btn');
let currentBbsLinks = [];
/**
 * Base64でエンコードされたUTF-8文字列をデコードします。
 * @param {string} str - Base64エンコードされた文字列
 */

const bbsSubmissionOverlay = document.getElementById('bbs-submission-overlay'); 
const bbsSubmissionWindow = document.getElementById('bbs-submission-window');
const bbsSubmissionCloseBtn = document.getElementById('bbs-submission-close-btn');
const bbsSubmissionName = document.getElementById('bbs-submission-name');
const bbsSubmissionUrl = document.getElementById('bbs-submission-url');
const bbsSubmissionDescription = document.getElementById('bbs-submission-description');

function b64DecodeUnicode(str) {
    return decodeURIComponent(atob(str).split('').map(function (c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2); 
    }).join(''));
}

/**
 * 画像ポップアップを開きます。
 * @param {string} title - ポップアップのタイトル
 * @param {string} imageUrl - 表示する画像のURL
 */
function openImagePopup(title, imageUrl) {
    imagePopupImg.src = imageUrl;
    // ポップアップ表示時にキーボードイベントリスナーを追加
    document.addEventListener('keydown', handlePopupKeydown);
    imagePopupOverlay.classList.add('visible');
}

/** 画像ポップアップを閉じます。 */
function closeImagePopup() {
    // ポップアップを閉じる時にキーボードイベントリスナーを削除
    document.removeEventListener('keydown', handlePopupKeydown);
    imagePopupOverlay.classList.remove('visible');
}

/** ポップアップ表示中のキー押下を処理する関数 */
function handlePopupKeydown(e) { 
    closeImagePopup();
}

// マルチラインエディタ内のANSIカラーボタンがクリックされたときの処理
ansiControls.addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON' && e.target.dataset.sequence) {
        const sequenceCode = e.target.dataset.sequence;
        const startSequence = '\x1b' + sequenceCode;
        const endSequence = '\x1b[0m';
        const textarea = multilineEditorInput;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const text = textarea.value;
        const selectedText = text.substring(start, end);

        let newText;
        let newStart;
        let newEnd;

        // クリアシーケンスの場合
        if (sequenceCode === '[0m') {
            newText = text.substring(0, start) + startSequence + text.substring(end);
            newStart = start + startSequence.length;
            newEnd = newStart;
        } else if (selectedText) { // テキストが選択されている場合
            const replacement = startSequence + selectedText + endSequence;
            newText = text.substring(0, start) + replacement + text.substring(end);
            newStart = start;
            newEnd = start + replacement.length;
        } else {
            newText = text.substring(0, start) + startSequence + text.substring(end);
            newStart = start + startSequence.length;
            newEnd = newStart;
        }

        textarea.value = newText;
        textarea.selectionStart = newStart;
        textarea.selectionEnd = newEnd;
        textarea.focus();
    }
});

/**
 * マルチラインエディタのポップアップを開きます。
 */
function openMultilineEditor() {
    multilineEditorInput.value = '';
    multilineEditorOverlay.classList.add('visible');
    multilineEditorWindow.classList.add('visible');
    multilineEditorInput.focus();
}

/**
 * マルチラインエディタのポップアップを閉じます。
 */
function closeMultilineEditor() {
    multilineEditorOverlay.classList.remove('visible');
    multilineEditorWindow.classList.remove('visible');
}

multilineEditorInsertBtn.addEventListener('click', () => {
    // 入力されたテキストをサーバーに送信
    const textToInsert = multilineEditorInput.value;
    socket.emit('multiline_input_submit', { 
        content: textToInsert
    });
    closeMultilineEditor();
});

/**
 * 1行エディタのポップアップを開きます。
 */
function openLineEditor() {
    lineEditorInput.value = '';
    historyIndex = lineEditorHistory.length;
    lineEditorWindow.classList.add('visible');
    lineEditorInput.focus();
}

/**
 * 1行エディタのポップアップを閉じます。
 */
function closeLineEditor() {
    lineEditorWindow.classList.remove('visible');
}

lineEditorInsertBtn.addEventListener('click', () => {
    // 入力されたテキストを履歴に追加し、サーバーに送信
    const textToInsert = lineEditorInput.value;
    // 空でない場合のみ履歴に追加
    if (textToInsert && (lineEditorHistory.length === 0 || lineEditorHistory[lineEditorHistory.length - 1] !== textToInsert)) {
        lineEditorHistory.push(textToInsert);
    }
    socket.emit('client_input', textToInsert + '\r'); // サーバー側の process_input を終了させるために改行を追加
    lineEditorInput.value = ''; // 入力欄をクリア
    historyIndex = lineEditorHistory.length; // 履歴インデックスをリセット
    closeLineEditor(); // 入力後はエディタを閉じる
});

// 1行エディタでのキーボードイベント（Enter, 上下矢印）を処理
lineEditorInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        lineEditorInsertBtn.click();
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (historyIndex > 0) {
            historyIndex--;
            lineEditorInput.value = lineEditorHistory[historyIndex];
        }
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (historyIndex < lineEditorHistory.length - 1) {
            historyIndex++;
            lineEditorInput.value = lineEditorHistory[historyIndex];
        } else if (historyIndex === lineEditorHistory.length - 1) {
            historyIndex++;
            lineEditorInput.value = '';
        }
    }
});

/**
 * 設定ポップアップを開きます。
 */
function openPopup() {
    popupOverlay.classList.add('visible');
    popupWindow.classList.add('visible');
}

/**
 * 設定ポップアップを閉じます。
 */
function closePopup() {
    popupOverlay.classList.remove('visible');
    popupWindow.classList.remove('visible');
}

/**
 * ログビューアのポップアップを開きます。
 */
function openLogViewer() {
    logFilesList.innerHTML = ''; // ファイルリストをクリア
    logContentDisplay.value = ''; // 内容をクリア
    socket.emit('get_log_files');
    logViewerOverlay.classList.add('visible');
    logViewerWindow.classList.add('visible');
}

/**
 * ログビューアのポップアップを閉じます。
 */
function closeLogViewer() {
    logViewerOverlay.classList.remove('visible');
    logViewerWindow.classList.remove('visible');
}

/**
 * BBSリストのポップアップを開きます。 
 * サーバーにリストデータを要求し、ポップアップを表示します。
 */
function openBbsListPopup() {
    bbsStationsList.innerHTML = '<li><button>Loading...</button></li>';
    bbsDetailName.textContent = 'Select a BBS';
    bbsDetailDescription.textContent = '';
    bbsListJumpBtn.disabled = true;
    bbsListJumpBtn.removeAttribute('data-url');

    socket.emit('get_bbs_list'); 
    bbsListOverlay.classList.add('visible');
    bbsListWindow.classList.add('visible');
}

/**
 * BBSリストのポップアップを閉じます。
 */
function closeBbsListPopup() {
    bbsListOverlay.classList.remove('visible');
    bbsListWindow.classList.remove('visible');
}

bbsListCloseBtn.addEventListener('click', closeBbsListPopup);
bbsListOverlay.addEventListener('click', closeBbsListPopup);

bbsListJumpBtn.addEventListener('click', () => {
    const url = bbsListJumpBtn.dataset.url;
    if (url) {
        window.open(url, '_blank');
    }
});

// サーバーから受信したBBSリストデータを画面に描画
socket.on('bbs_list_data', (data) => { 
    currentBbsLinks = data.links || [];
    bbsStationsList.innerHTML = ''; // リストをクリア

    if (currentBbsLinks.length === 0) {
        bbsStationsList.innerHTML = '<li>No BBS links found.</li>';
        return;
    }

    currentBbsLinks.forEach(link => {
        const li = document.createElement('li');
        const button = document.createElement('button');
        button.textContent = link.name;
        button.dataset.linkId = link.id;
        li.appendChild(button);
        bbsStationsList.appendChild(li);
    });
});

// BBSリストポップアップ内の「新規リンク申請」ボタンの処理
document.getElementById('bbs-list-submit-new-btn').addEventListener('click', () => {
    bbsSubmissionName.value = '';
    bbsSubmissionUrl.value = '';
    bbsSubmissionDescription.value = '';
    bbsSubmissionOverlay.classList.add('visible');
    bbsSubmissionWindow.classList.add('visible');
});

/**
 * BBSリンク申請用のポップアップを閉じます。
 */
function closeBbsSubmissionPopup() { 
    bbsSubmissionOverlay.classList.remove('visible');
    bbsSubmissionWindow.classList.remove('visible');
}

bbsSubmissionCloseBtn.addEventListener('click', closeBbsSubmissionPopup);
bbsSubmissionOverlay.addEventListener('click', closeBbsSubmissionPopup);

// BBSリンク申請フォームの「申請」ボタンがクリックされたときの処理
document.getElementById('bbs-submission-submit-btn').addEventListener('click', () => {
    const name = bbsSubmissionName.value.trim();
    const url = bbsSubmissionUrl.value.trim();
    const description = bbsSubmissionDescription.value.trim();

    if (name && url) {
        socket.emit('submit_bbs_link', { name, url, description }); 
        closeBbsSubmissionPopup();
    } else {
        alert('BBS Name and URL are required.');
    }
});

// --- ファンクションキーの生成とイベント設定 --- 
const fkeysLeftContainer = document.getElementById('f-keys-left');
const fkeysRightContainer = document.getElementById('f-keys-right');

// ファンクションキーの定義に基づいて、画面下部のボタンを動的に生成
for (let i = 1; i <= 8; i++) {
    const key = document.createElement('div');
    key.classList.add('f-key');
    const fkeyId = `f${i}`; 
    const definition = fkeyDefinitions[fkeyId]; 

    if (definition) {
        key.textContent = `${definition.label}`;
        if (definition.action === 'open_popup') {
            key.addEventListener('click', openPopup);
        } else if (definition.action === 'send_command') {
            key.addEventListener('click', () => socket.emit('client_input', definition.value + '\r')); 
        } else if (definition.action === 'open_multiline_editor') {
            key.addEventListener('click', openMultilineEditor);
        } else if (definition.action === 'open_line_editor') {
            key.addEventListener('click', openLineEditor);
        } else if (definition.action === 'toggle_logging') {
            key.id = 'f2-log-btn';
            key.addEventListener('click', () => {
                socket.emit('toggle_logging'); 
            });
        } else if (definition.action === 'open_log_viewer') {
            key.addEventListener('click', openLogViewer);
        } else if (definition.action === 'open_bbs_list') {
            key.addEventListener('click', openBbsListPopup);

        } else if (definition.action === 'redirect') {
            key.addEventListener('click', () => {
                window.location.href = definition.value;
            });
        }
    } else {
        key.textContent = `NoFunction`;
    }

    if (i <= 4) {
        fkeysLeftContainer.appendChild(key);
    } else {
        fkeysRightContainer.appendChild(key);
    }
}

popupCloseBtn.addEventListener('click', closePopup);
popupOverlay.addEventListener('click', closePopup);

// 1行エディタの閉じる/キャンセルボタンは、入力をキャンセル（空行を送信）して閉じる
lineEditorCloseBtn.addEventListener('click', () => {
    socket.emit('client_input', '\r'); // サーバーの入力待ちを解除
    closeLineEditor();
});
lineEditorCancelBtn.addEventListener('click', () => {
    lineEditorCloseBtn.click(); // 閉じるボタンと同じ動作
});

// マルチラインエディタの閉じる/キャンセルボタンは、空の内容を送信して閉じる
multilineEditorCloseBtn.addEventListener('click', () => {
    socket.emit('multiline_input_submit', { content: '' }); 
    closeMultilineEditor();
});
multilineEditorCancelBtn.addEventListener('click', () => {
    socket.emit('multiline_input_submit', { content: '' }); 
    closeMultilineEditor();
});
multilineEditorOverlay.addEventListener('click', () => {
    socket.emit('multiline_input_submit', { content: '' }); 
    closeMultilineEditor();
});
logViewerCloseBtn.addEventListener('click', closeLogViewer);
logViewerOverlay.addEventListener('click', closeLogViewer);

// --- ユーザー選択ポップアップのロジック ---
const userSelectorOverlay = document.getElementById('user-selector-overlay');
const userSelectorWindow = document.getElementById('user-selector-window');
const userSelectorCloseBtn = document.getElementById('user-selector-close-btn');
const userSelectorTitle = document.getElementById('user-selector-title');
const userSelectorSearch = document.getElementById('user-selector-search');
const userSelectorList = document.getElementById('user-selector-list');
const userSelectorOkBtn = document.getElementById('user-selector-ok-btn');
const userSelectorCancelBtn = document.getElementById('user-selector-cancel-btn');
let selectedUser = null;
let allUsersForSelector = []; // ユーザーリストを保持する変数

/**
 * オンラインユーザー選択ポップアップを開きます。
 * @param {string} prompt - ポップアップに表示するプロンプトメッセージ
 * @param {Array} userList - 選択肢となるユーザーのリスト
 */
function openUserSelector(prompt, userList) {
    userSelectorTitle.textContent = prompt;
    allUsersForSelector = userList; // 全ユーザーリストを保存
    populateUserList(allUsersForSelector); // 全リストを表示
    userSelectorSearch.value = '';
    selectedUser = null;
    userSelectorOkBtn.disabled = true;
    userSelectorOverlay.classList.add('visible');
    userSelectorWindow.classList.add('visible');
    userSelectorSearch.focus();
}

/**
 * オンラインユーザー選択ポップアップを閉じます。
 */
function closeUserSelector() {
    userSelectorOverlay.classList.remove('visible');
    userSelectorWindow.classList.remove('visible');
}

/**
 * ユーザーリストを画面に描画します。
 * @param {Array} users - 表示するユーザーのリスト
 */
function populateUserList(users) {
    userSelectorList.innerHTML = '';
    users.forEach(user => {
        const li = document.createElement('li');
        li.textContent = user.name;
        li.dataset.username = user.name;
        userSelectorList.appendChild(li);
    });
}

// ユーザー選択ポップアップ内の検索機能
userSelectorSearch.addEventListener('input', () => {
    const searchTerm = userSelectorSearch.value.toLowerCase();
    const filteredUsers = allUsersForSelector.filter(user =>
        user.name.toLowerCase().includes(searchTerm)
    );
    populateUserList(filteredUsers);
    // 検索結果が変わったら選択をリセット
    selectedUser = null;
    userSelectorOkBtn.disabled = true;
});

// ユーザーリスト内の項目がクリックされたときの処理
userSelectorList.addEventListener('click', (e) => {
    if (e.target.tagName === 'LI') {
        document.querySelectorAll('#user-selector-list li').forEach(li => li.classList.remove('selected'));
        e.target.classList.add('selected');
        selectedUser = e.target.dataset.username;
        userSelectorOkBtn.disabled = false;
    }
});

// ユーザー選択ポップアップの「OK」ボタンがクリックされたときの処理
userSelectorOkBtn.addEventListener('click', () => {
    if (selectedUser) {
        socket.emit('client_input', selectedUser + '\r'); 
        closeUserSelector();
    }
});

// ユーザー選択ポップアップの「キャンセル」ボタンがクリックされたときの処理
userSelectorCancelBtn.addEventListener('click', () => {
    socket.emit('client_input', '\r'); 
    closeUserSelector();
});
userSelectorCloseBtn.addEventListener('click', () => { userSelectorCancelBtn.click(); });
userSelectorOverlay.addEventListener('click', () => { userSelectorCancelBtn.click(); });

/**
 * BBSリストポップアップ内のリスト項目（BBS名ボタン）がクリックされたときの処理です。
 */
bbsStationsList.addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON') {
        const linkId = parseInt(e.target.dataset.linkId, 10);
        const selectedLink = currentBbsLinks.find(link => link.id === linkId);

        if (selectedLink) {
            document.querySelectorAll('#bbs-stations-list button').forEach(btn => btn.classList.remove('active'));
            e.target.classList.add('active');

            bbsDetailName.textContent = selectedLink.name;
            bbsDetailDescription.textContent = selectedLink.description || 'No description available.';
            bbsListJumpBtn.dataset.url = selectedLink.url;
            bbsListJumpBtn.disabled = false;
        }
    }
});

// --- 設定ポップアップ内のボタンイベント --- 
document.getElementById('theme-selector').addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON') {
        applyTheme(e.target.dataset.theme);
    }
});

document.getElementById('fontsize-selector').addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON') {
        applyFontSize(e.target.dataset.size);
    }
});

document.getElementById('font-selector').addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON') {
        const fontName = e.target.dataset.font;
        applyFont(fontName);
    }
});

document.getElementById('speed-selector').addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON') {
        applySpeed(e.target.dataset.speed);
    }
});

document.getElementById('effect-selector').addEventListener('click', (e) => {
    if (e.target.classList.contains('effect-btn')) {
        toggleEffect(e.target.dataset.effect);
    }
});

// --- パスワード入力モードの管理 --- 
let isPasswordInputMode = false;

socket.on('start_password_input', () => {
    // サーバーからパスワード入力モード開始の指示を受信
    isPasswordInputMode = true;
});

socket.on('end_password_input', () => {
    isPasswordInputMode = false;
});

// ターミナルへのキー入力をサーバーに送信する処理
term.onData(data => {
    if (isPasswordInputMode) {
        if (data === '\r') { 
            socket.emit('client_input', data); 
        } else if (data === '\x7f' || data === '\x08') { // バックスペース
            socket.emit('client_input', data); 
            term.write('\b \b');
        } else {
            socket.emit('client_input', data); 
            term.write('*');
        }
    } else {
        socket.emit('client_input', data); 
    }
});

// --- モバイル用操作パネルの表示/非表示管理 --- 
function hideAllMobileControls() {
    const controls = [
        document.getElementById('mobile-bbs-controls'),
        document.getElementById('mobile-chat-controls'),
        document.getElementById('mobile-userpref-controls'),
        document.getElementById('mobile-mail-controls'),
        document.getElementById('mobile-bbs-entry-controls'),
        document.getElementById('mobile-top-menu-controls'),
        document.getElementById('mobile-plugin-menu-controls'),
        document.getElementById('mobile-confirm-controls')
    ];
    const monitorScreen = document.querySelector('.monitor-screen');

    controls.forEach(control => {
        if (control) {
            control.classList.remove('visible');
        }
    });
    monitorScreen.style.paddingBottom = '';
}

// --- サーバーからの出力処理 --- 
socket.on('server_output', data => {
        const passkeyRegisterPattern = /\x1b\[\?2027h/;
    if (passkeyRegisterPattern.test(data)) {
            // Passkey登録フローを開始し、完了後にメッセージを表示してEnterを送信するコールバックを渡す
            registerNewPasskey(result => {
                term.writeln(`\r\n\x1b[1m${result.message}\x1b[0m`);
                // サーバー側の process_input() を解除するためにEnterを送信
                socket.emit('client_input', '\r');
            });
        data = data.replace(passkeyRegisterPattern, '');
    }

    const userprefControlPattern = /\x1b\[\?2028(h|l)/;
    const userprefMatch = data.match(userprefControlPattern);
    if (userprefMatch) {
        const mobileControls = document.getElementById('mobile-userpref-controls');
        const monitorScreen = document.querySelector('.monitor-screen');

        if (userprefMatch[1] === 'h') {
            mobileControls.classList.add('visible');
            const controlsHeight = mobileControls.offsetHeight;
            monitorScreen.style.paddingBottom = `${controlsHeight}px`;
            monitorScreen.dataset.controlsHeight = controlsHeight;
        } else {
            mobileControls.classList.remove('visible');
            monitorScreen.style.paddingBottom = '';
        }
        data = data.replace(userprefControlPattern, '');
        updateTerminalLayout();
    }

    const chatControlPattern = /\x1b\[\?2026(h|l)/;
    const chatMatch = data.match(chatControlPattern);
    if (chatMatch) {
        const mobileControls = document.getElementById('mobile-chat-controls');
        const monitorScreen = document.querySelector('.monitor-screen');

        if (chatMatch[1] === 'h') {
            mobileControls.classList.add('visible');
            const controlsHeight = mobileControls.offsetHeight;
            monitorScreen.style.paddingBottom = `${controlsHeight}px`;
            monitorScreen.dataset.controlsHeight = controlsHeight;
        } else {
            mobileControls.classList.remove('visible');
            monitorScreen.style.paddingBottom = '';
        }
        data = data.replace(chatControlPattern, '');
        updateTerminalLayout();
    }

    const mailControlPattern = /\x1b\[\?2029(h|l)/;
    const mailMatch = data.match(mailControlPattern);
    if (mailMatch) {
        const mobileControls = document.getElementById('mobile-mail-controls');
        const monitorScreen = document.querySelector('.monitor-screen');

        if (mailMatch[1] === 'h') {
            mobileControls.classList.add('visible');
            const controlsHeight = mobileControls.offsetHeight;
            monitorScreen.style.paddingBottom = `${controlsHeight}px`;
            monitorScreen.dataset.controlsHeight = controlsHeight;
        } else {
            mobileControls.classList.remove('visible');
            monitorScreen.style.paddingBottom = '';
        }
        data = data.replace(mailControlPattern, '');
        updateTerminalLayout();
    }

    const bbsEntryControlPattern = /\x1b\[\?2030(h|l)/;
    const bbsEntryMatch = data.match(bbsEntryControlPattern);
    if (bbsEntryMatch) {
        const mobileControls = document.getElementById('mobile-bbs-entry-controls');
        const monitorScreen = document.querySelector('.monitor-screen');

        if (bbsEntryMatch[1] === 'h') {
            mobileControls.classList.add('visible');
            const controlsHeight = mobileControls.offsetHeight;
            monitorScreen.style.paddingBottom = `${controlsHeight}px`;
            monitorScreen.dataset.controlsHeight = controlsHeight;
        } else {
            mobileControls.classList.remove('visible');
            monitorScreen.style.paddingBottom = '';
        }
        data = data.replace(bbsEntryControlPattern, '');
        updateTerminalLayout();
    }

    const pluginMenuControlPattern = /\x1b\[\?2032(h|l)/;
    const pluginMenuMatch = data.match(pluginMenuControlPattern);
    if (pluginMenuMatch) {
        const mobileControls = document.getElementById('mobile-plugin-menu-controls');
        const monitorScreen = document.querySelector('.monitor-screen');

        if (pluginMenuMatch[1] === 'h') {
            mobileControls.classList.add('visible');
            const controlsHeight = mobileControls.offsetHeight;
            monitorScreen.style.paddingBottom = `${controlsHeight}px`;
            monitorScreen.dataset.controlsHeight = controlsHeight;
        } else {
            mobileControls.classList.remove('visible');
            monitorScreen.style.paddingBottom = '';
        }
        data = data.replace(pluginMenuControlPattern, '');
        updateTerminalLayout();
    }

    const topMenuControlPattern = /\x1b\[\?2031(h|l)/;
    const topMenuMatch = data.match(topMenuControlPattern);
    if (topMenuMatch) {
        const mobileControls = document.getElementById('mobile-top-menu-controls');
        const monitorScreen = document.querySelector('.monitor-screen');

        if (topMenuMatch[1] === 'h') {
            mobileControls.classList.add('visible');
            const controlsHeight = mobileControls.offsetHeight;
            monitorScreen.style.paddingBottom = `${controlsHeight}px`;
            monitorScreen.dataset.controlsHeight = controlsHeight;
        } else {
            mobileControls.classList.remove('visible');
            monitorScreen.style.paddingBottom = '';
        }
        data = data.replace(topMenuControlPattern, '');
        updateTerminalLayout();
    }

    const bbsControlPattern = /\x1b\[\?2024(h|l)/;
    const match = data.match(bbsControlPattern);
    if (match) {
        const mobileControls = document.getElementById('mobile-bbs-controls');
        const monitorScreen = document.querySelector('.monitor-screen');

        if (match[1] === 'h') {
            mobileControls.classList.add('visible');
            const controlsHeight = mobileControls.offsetHeight;
            monitorScreen.style.paddingBottom = `${controlsHeight}px`;
            monitorScreen.dataset.controlsHeight = controlsHeight;
        } else {
            mobileControls.classList.remove('visible');
            monitorScreen.style.paddingBottom = '';
        }
        data = data.replace(bbsControlPattern, '');
        updateTerminalLayout();
    }

    const downloadPattern = /\x1b_GRBBS_DOWNLOAD;(.*?)\x1b\\/;
    const downloadMatch = data.match(downloadPattern);
    if (downloadMatch) {
        const url = downloadMatch[1];
        const link = document.createElement('a');
        link.href = url;
        link.download = ''; // download属性を付けるとファイル保存ダイアログが出る
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        data = data.replace(downloadPattern, '');
    }

    const attachmentDialogPattern = /\x1b\[\?2033h/;
    if (attachmentDialogPattern.test(data)) {
        const attachmentInput = document.getElementById('attachment-input');

        const onFocus = () => {
            window.removeEventListener('focus', onFocus);
            setTimeout(() => {
                socket.emit('client_input', '\r'); 
            }, 150);
        };
        window.addEventListener('focus', onFocus);

        attachmentInput.click();
        data = data.replace(attachmentDialogPattern, '');
    }

    const attachmentUiHidePattern = /\x1b\[\?2032l/;
    if (attachmentUiHidePattern.test(data)) {
        const attachmentInput = document.getElementById('attachment-input');
        attachmentInput.value = ''; 
        socket.emit('clear_pending_attachment');
        data = data.replace(attachmentUiHidePattern, '');

    }

    const multilineEditorPattern = /\x1b\[\?2034(h|l)/;
    const multilineMatch = data.match(multilineEditorPattern);
    if (multilineMatch) {
        if (multilineMatch[1] === 'h') {
            openMultilineEditor();
        } else { // 'l' for hide
            closeMultilineEditor();
        }
        data = data.replace(multilineEditorPattern, '');
    }

    const confirmButtonsPattern = /\x1b\]GRBBS;CONFIRM_BUTTONS;(.*?);(.*?)\x07/;
    const confirmButtonsMatch = data.match(confirmButtonsPattern);
    if (confirmButtonsMatch) {
        const yesLabelB64 = confirmButtonsMatch[1];
        const noLabelB64 = confirmButtonsMatch[2];
        try {
            document.getElementById('confirm-btn-y').textContent = b64DecodeUnicode(yesLabelB64);
            document.getElementById('confirm-btn-n').textContent = b64DecodeUnicode(noLabelB64);
        } catch (e) {
            console.error("Failed to set confirm button labels:", e);
            document.getElementById('confirm-btn-y').textContent = 'Yes';
            document.getElementById('confirm-btn-n').textContent = 'No';
        }
        data = data.replace(confirmButtonsPattern, '');
    }

    const confirmControlPattern = /\x1b\[\?2035(h|l)/;
    const confirmMatch = data.match(confirmControlPattern);
    if (confirmMatch) {
        const mobileControls = document.getElementById('mobile-confirm-controls');
        const monitorScreen = document.querySelector('.monitor-screen');

        if (confirmMatch[1] === 'h') {
            mobileControls.classList.add('visible');
            const controlsHeight = mobileControls.offsetHeight;
            monitorScreen.style.paddingBottom = `${controlsHeight}px`;
            monitorScreen.dataset.controlsHeight = controlsHeight;
        } else {
            mobileControls.classList.remove('visible');
            monitorScreen.style.paddingBottom = '';
        }
        data = data.replace(confirmControlPattern, '');
        updateTerminalLayout();
    }

    const lineEditorPattern = /\x1b\]GRBBS;LINE_EDIT;(.*?);(.*?)\x07/;
    const lineEditorMatch = data.match(lineEditorPattern);
    if (lineEditorMatch) {
        const promptB64 = lineEditorMatch[1];
        const valueB64 = lineEditorMatch[2];
        try {
            const promptText = b64DecodeUnicode(promptB64);
            const initialValue = b64DecodeUnicode(valueB64);
            document.getElementById('line-editor-prompt').textContent = promptText;
            lineEditorInput.value = initialValue;
            openLineEditor();
        } catch (e) {
            console.error("Failed to open line editor with decoded data:", e);
        }
        data = data.replace(lineEditorPattern, '');
    }

    const userSelectorPattern = /\x1b\]GRBBS;USER_SELECT;(.*?);(.*?)\x07/;
    const userSelectorMatch = data.match(userSelectorPattern);
    if (userSelectorMatch) {
        const promptB64 = userSelectorMatch[1];
        const userListB64 = userSelectorMatch[2];
        try {
            const promptText = b64DecodeUnicode(promptB64);
            const userList = JSON.parse(b64DecodeUnicode(userListB64));
            openUserSelector(promptText, userList);
        } catch (e) {
            console.error("Failed to open user selector with decoded data:", e);
        }
        data = data.replace(userSelectorPattern, '');
    }

    const uploadFilePattern = /\x1b\]GRBBS;UPLOAD_FILE\x07/;
    if (uploadFilePattern.test(data)) {
        const fileInput = document.getElementById('plugin-file-input');
        // 以前のリスナーを削除して多重実行を防ぐ
        const newFileInput = fileInput.cloneNode(true);
        fileInput.parentNode.replaceChild(newFileInput, fileInput);

        newFileInput.addEventListener('change', () => {
            if (newFileInput.files.length > 0) {
                const file = newFileInput.files[0];
                const reader = new FileReader();
                reader.onload = (e) => {
                    socket.emit('upload_file_from_plugin', { filename: file.name, data: e.target.result });
                };
                reader.readAsArrayBuffer(file);
            }
        }, { once: true }); // イベントリスナーを一度だけ実行
        newFileInput.click();
        data = data.replace(uploadFilePattern, '');
    }
    const imagePopupPattern = /\x1b\]GRBBS;SHOW_IMAGE_POPUP;(.*?);(.*?)\x07/;
    const imagePopupMatch = data.match(imagePopupPattern);
    if (imagePopupMatch) {
        const titleB64 = imagePopupMatch[1];
        const urlB64 = imagePopupMatch[2];
        try {
            const title = b64DecodeUnicode(titleB64);
            const imageUrl = b64DecodeUnicode(urlB64);
            openImagePopup(title, imageUrl);
        } catch (e) {
            console.error("Failed to open image popup:", e);
        }
        data = data.replace(imagePopupPattern, '');
    }
    // --- 自動スクロール & レイアウト補正ロジック --- 
    const buffer = term.buffer.active;
    // 処理前に、ユーザーが既に一番下までスクロールしているか確認
    const isScrolledToBottom = buffer.viewportY + term.rows >= buffer.baseY + buffer.length;

    if ('visualViewport' in window) {
        const vv = window.visualViewport;
        const isMobile = window.matchMedia("(max-width: 992px)").matches;
        const isKeyboardVisible = (window.innerHeight - vv.height) > 80;

        if (isMobile && isKeyboardVisible) {
            // キーボード表示中は、表示領域の高さをキーボードの上端までに制限
            document.body.style.height = `${vv.height}px`;
            document.querySelector('.monitor-screen').style.paddingBottom = '0px'; // prettier-ignore
            // DOMの更新を待ってからターミナルのリサイズを実行
            setTimeout(() => {
                try {
                    fitAddon.fit();
                } catch (e) {
                    console.error("fitAddon.fit() failed during server_output:", e);
                }
            }, 0);
        }
    }

   // カスタムエスケープシーケンスを処理してJavaScriptを実行
    const runJsPattern = /\x1b\]GRBBS;RUN_JS;(.*?)\x07/g;
    let jsMatch;
    // `g`フラグを使っているので、ループで全てののマッチを処理
    while ((jsMatch = runJsPattern.exec(data)) !== null) {
        const jsCodeB64 = jsMatch[1];
        try {
            const jsCode = atob(jsCodeB64);  // Base64デコード
            eval(jsCode);  // デコードしたJSコードを実行
        } catch (e) {
            console.error("Failed to execute JS from server:", e);
        }
    }
    // 画面に表示しないように、処理したシーケンスをデータから削除

    data = data.replace(runJsPattern, '');



    // 管理画面オープン専用シーケンス
    const openAdminPattern = /\x1b\]GRBBS;OPEN_ADMIN;(.*?)\x07/;
    const openAdminMatch = data.match(openAdminPattern);
    if (openAdminMatch) {
        const urlB64 = openAdminMatch[1];
        try {
            const adminUrl = atob(urlB64);
            // ユーザー操作と紐づいているのでブロックされない
            window.open(adminUrl, '_blank');
        } catch (e) {
            console.error("Failed to open admin URL:", e);
        }
        data = data.replace(openAdminPattern, '');
    }



    term.write(data);

    if (isScrolledToBottom) {
        term.scrollToBottom();
    }
});

// BBSリンク申請の結果をユーザーに通知
socket.on('bbs_link_submission_result', (data) => { 
    if (data.success) {
        alert('Link submitted for approval. Thank you!');
    } else {
        alert(`Submission failed: ${data.message}`);
    }
});

socket.on('upload_error_from_plugin', (data) => {
    const message = data.message || 'An unknown error occurred during file upload.';
    alert(`Upload Error: ${message}`);
    // ファイル選択ダイアログをリセット
    document.getElementById('plugin-file-input').value = '';
});
// --- ログビューワー関連のイベント ---
socket.on('log_files_list', (data) => {
    // サーバーから受信したログファイルリストを画面に描画
    logFilesList.innerHTML = ''; // 既存のリストをクリア

    if (isLogging) {
        const li = document.createElement('li');
        const button = document.createElement('button');
        button.textContent = textData.log_logging_now;
        button.style.color = '#ff4444';
        button.style.fontWeight = 'bold';
        button.style.width = '100%';
        button.style.textAlign = 'left';
        button.style.marginBottom = '5px';
        button.addEventListener('click', () => {
            logContentDisplay.value = textData.log_loading_current;
            socket.emit('get_current_log_buffer');
        });
        li.appendChild(button);
        logFilesList.appendChild(li);
    }

    if (data.files && data.files.length > 0) {
        data.files.forEach(file => {
            const li = document.createElement('li');
            const button = document.createElement('button');
            const date = new Date(file.mtime * 1000).toLocaleString('ja-JP');
            button.textContent = `${file.filename}`;
            button.title = `サイズ: ${(file.size / 1024).toFixed(1)} KB, 更新日時: ${date}`;
            button.style.width = '100%';
            button.style.textAlign = 'left';
            button.style.marginBottom = '5px';
            button.addEventListener('click', () => {
                logContentDisplay.value = textData.log_loading_file.replace('{filename}', file.filename);
                socket.emit('get_log_content', { filename: file.filename });
            });
            li.appendChild(button);
            logFilesList.appendChild(li);
        });
    } else if (!isLogging) {
        const li = document.createElement('li');
        li.textContent = textData.log_no_files;
        logFilesList.appendChild(li);
    }
});

socket.on('log_content', (data) => {
    // サーバーから受信したログファイルの内容を表示
    logContentDisplay.value = data.content;
});

socket.on('error_message', (data) => {
    term.writeln(`\r\n\x1b[31m[Error] ${data.message}\x1b[0m`);
    socket.emit('client_input', '\r'); 
}); 
// --- ロギング状態の管理 ---

let isLogging = false;

socket.on('logging_started', () => {
    // サーバーからロギング開始の通知を受け、UIを更新
    const f2LogBtn = document.getElementById('f2-log-btn');
    const sidenavLogBtn = document.getElementById('sidenav-log-btn');
    isLogging = true;
    if (f2LogBtn) {
        f2LogBtn.textContent = 'LOGGING...';
    }
    if (sidenavLogBtn) {
        sidenavLogBtn.textContent = 'LOGGING...';
    }
});

socket.on('log_saved', (data) => {
    // サーバーからログ保存完了の通知を受け、UIを更新し、ファイルをダウンロード
    isLogging = false;
    const f2LogBtn = document.getElementById('f2-log-btn');
    const sidenavLogBtn = document.getElementById('sidenav-log-btn');
    if (f2LogBtn) {
        f2LogBtn.textContent = 'LOGGING';
    }
    if (sidenavLogBtn) {
        sidenavLogBtn.textContent = 'LOGGING';
    }

    const link = document.createElement('a');
    link.href = data.url;
    link.download = data.filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
});

socket.on('logging_stopped', (data) => {
    // サーバーからロギング停止の通知を受け、UIを更新
    isLogging = false;
    const f2LogBtn = document.getElementById('f2-log-btn');
    const sidenavLogBtn = document.getElementById('sidenav-log-btn');
    if (f2LogBtn) {
        f2LogBtn.textContent = 'LOGGING';
    }
    if (sidenavLogBtn) {
        sidenavLogBtn.textContent = 'LOGGING';
    }
});

socket.on('force_disconnect', (data) => {
    // サーバーから強制切断された場合の処理
    const message = (data && data.message) ? data.message : '[Connection closed by server]';
    term.writeln(`\r\n\n${message}`);
    term.writeln('\r\nPress any key or click to return to the login screen...'); 
    socket.disconnect();
    const redirectToLogout = () => {
        window.location.href = URLS.logout;
    };
    // ログアウト画面へ遷移するイベントリスナーを設定
    document.addEventListener('keydown', redirectToLogout, { once: true });
    document.addEventListener('mousedown', redirectToLogout, { once: true });
});
/**
 * ローカルストレージから各種設定を読み込み、ターミナルUIに適用します。
 * テーマ、フォント、フォントサイズ、速度、画面効果などが対象です。
 */
function loadSettings() {
    // テーマ
    const savedTheme = localStorage.getItem('terminalTheme') || 'default';
    applyTheme(savedTheme);

    // フォント
    const isMobileForLoad = window.matchMedia('(max-width: 992px)').matches;
    const defaultFontSize = isMobileForLoad ? '28' : '16';
    const savedFontName = localStorage.getItem('terminalFont') || 'M PLUS 1m';
    applyFont(savedFontName);

    // フォントサイズ
    const storageKey = isMobileForLoad ? 'terminalFontSizeMobile' : 'terminalFontSizePC';
    const savedFontSize = localStorage.getItem(storageKey) || defaultFontSize;
    applyFontSize(savedFontSize);

    // 速度
    const savedSpeed = localStorage.getItem('terminalSpeed') || 'full';
    applySpeed(savedSpeed);

    // 画面効果
    const savedEffects = localStorage.getItem('effectStates');
    if (savedEffects) {
        Object.assign(effectStates, JSON.parse(savedEffects));
    }
    for (const effectName in effectStates) {
        applyEffect(effectName, effectStates[effectName]);
    }
    updateEffectButtons();
    updateDipSwitches('theme', savedTheme);
    updateDipSwitches('font', savedFontName);
    updateDipSwitches('speed', savedSpeed);
    updateDipSwitches('fontsize', savedFontSize);
    updateDipSwitches('effect');
    updatePushStatus(); // これがDIPスイッチの状態も更新する
}

// DIPスイッチパネルの変更を検知し、対応する設定を適用
document.querySelector('.dip-switch-panel').addEventListener('change', (e) => {
    if (e.target.type !== 'checkbox') return;

    isDipSwitchUpdating = true;

    const groupElement = e.target.closest('.dip-switch-group');
    const groupName = groupElement.dataset.group;

    if (groupName === 'effect') { // エフェクトはビットごとのON/OFFなので特別扱い
        const effectBit = parseInt(e.target.dataset.bit);
        const effectName = Object.keys(effectMap).find(key => effectMap[key] === effectBit);
        if (effectName) {
            toggleEffect(effectName);
        }
    } else if (groupName === 'push') {
        const isEnabled = e.target.checked;
        if (isEnabled) {
            enablePushNotifications();
        } else {
            disablePushNotifications();
        }
    } else {
        // 他のグループは数値として計算
        const switches = groupElement.querySelectorAll('input[type="checkbox"]');
        let numericValue = 0;
        switches.forEach(sw => {
            if (sw.checked) {
                numericValue |= (1 << parseInt(sw.dataset.bit));
            }
        });

        if (groupName === 'theme') { const themeName = themeMapReverse[numericValue]; if (themeName) applyTheme(themeName); }
        else if (groupName === 'font') { const fontName = fontMapReverse[numericValue]; if (fontName) applyFont(fontName); }
        else if (groupName === 'speed') { const speedName = speedMapReverse[numericValue]; if (speedName) applySpeed(speedName); }
        else if (groupName === 'fontsize') { const size = fontsizeMapReverse[numericValue]; if (size) applyFontSize(size); }
        // pushは個別処理なのでここでは何もしない
    }

    setTimeout(() => { isDipSwitchUpdating = false; }, 50);
});

/**
 * DIPスイッチの現在の状態をローカルストレージに保存します。
 */
function saveDipSwitchSettings() {
    const settings = {};
    document.querySelectorAll('.dip-switch-group').forEach(group => {
        const groupName = group.dataset.group;
        settings[groupName] = {};
        group.querySelectorAll('input[type="checkbox"]').forEach(sw => {
            settings[groupName][sw.id] = sw.checked;
        });
    });
    localStorage.setItem('dipSwitchSettings', JSON.stringify(settings));
}

/**
 * ローカルストレージからDIPスイッチの状態を復元します。
 */
function loadDipSwitchSettings() { 
    const savedSettings = localStorage.getItem('dipSwitchSettings');
    if (savedSettings) {
        const settings = JSON.parse(savedSettings);
        for (const groupName in settings) {
            for (const switchId in settings[groupName]) {
                const switchEl = document.getElementById(switchId);
                if (switchEl) {
                    switchEl.checked = settings[groupName][switchId];
                }
            }
        }
    }
}

// WebSocket接続が確立したときの初期化処理
socket.on('connect', () => {
    loadSettings();

    // クライアントの表示モード（モバイル/デスクトップ）をサーバーに通知
    const isMobile = window.matchMedia('(max-width: 992px)').matches;
    socket.emit('set_client_mode', { is_mobile: isMobile });

    const urlParams = new URLSearchParams(window.location.search);
    const shortcut = urlParams.get('shortcut');
    if (shortcut) {
        const command = `;${shortcut}\r`;
        setTimeout(() => {
            socket.emit('client_input', command); 
            window.history.replaceState({}, document.title, "/");
        }, 500);
    }

    // DIPスイッチの状態を復元してから、UIに反映させる
    loadDipSwitchSettings();
    document.querySelector('.dip-switch-panel').dispatchEvent(new Event('change', { bubbles: true }));
});

// --- ポップアップウィンドウのドラッグ移動機能 --- 
function makePopupDraggable(popup) {
    const header = popup.querySelector('.popup-header');
    if (!header) return;

    let isDragging = false;
    let offsetX, offsetY;

    header.addEventListener('mousedown', (e) => {
        if (e.target.tagName.toLowerCase() === 'button') {
            return;
        }
        isDragging = true;
        offsetX = e.clientX - popup.offsetLeft;
        offsetY = e.clientY - popup.offsetTop;
        header.style.cursor = 'grabbing';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        popup.style.left = `${e.clientX - offsetX}px`;
        popup.style.top = `${e.clientY - offsetY}px`;
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            header.style.cursor = 'grab';
        }
    });
}
document.querySelectorAll('.popup-window').forEach(popup => {
    if (popup.id !== 'line-editor-window') {
        makePopupDraggable(popup);
    }
});
makePopupDraggable(logViewerWindow);

// 画像ポップアップのクリックイベント（オーバーレイまたは画像自体をクリックで閉じる）
imagePopupOverlay.addEventListener('click', () => {
    closeImagePopup();
});

// --- DOM読み込み完了後の初期化処理 --- 
// --- PWAインストール関連のロジック --- 
let deferredPrompt;
let settingsInstallButton;
let pwaInstallDescription;
let pushEnableBtn;
let pushDisableBtn;
let pushStatus;


const sidenavInstallContainer = document.createElement('div');
sidenavInstallContainer.id = 'pwa-install-container-sidenav';
sidenavInstallContainer.style.display = 'none';
sidenavInstallContainer.style.padding = '8px 15px';

const sidenavInstallButton = document.createElement('a');
sidenavInstallButton.href = 'javascript:void(0)';
// テキストはDOMContentLoadedで設定
sidenavInstallContainer.appendChild(sidenavInstallButton);

window.addEventListener('beforeinstallprompt', (e) => {
    // デフォルトのインストールプロンプトを抑制
    e.preventDefault();
    // イベントを後で使うために保持
    deferredPrompt = e;
    // サイドナビのインストールボタンを表示
    sidenavInstallContainer.style.display = 'block';
    // 設定ポップアップのインストールボタンを有効化
    if (settingsInstallButton) {
        settingsInstallButton.disabled = false;
    }
});

async function handleInstallPrompt() {
    if (deferredPrompt) {
        // インストールプロンプトを表示
        deferredPrompt.prompt();
        // ユーザーの選択結果を待つ
        const choiceResult = await deferredPrompt.userChoice;
        console.log(`User response to the install prompt: ${choiceResult.outcome}`);

        // ユーザーがインストールを選択した場合のみ、UIを更新
        if (choiceResult.outcome === 'accepted') {
            // プロンプトは一度しか使えないのでクリア
            deferredPrompt = null;
            // ボタンを非表示に
            sidenavInstallContainer.style.display = 'none';
            // 設定ポップアップのボタンを無効化し、テキストを変更
            if (settingsInstallButton) {
                settingsInstallButton.disabled = true;
            }
            if (pwaInstallDescription) {
                pwaInstallDescription.textContent = textData?.terminal_ui?.settings_popup?.pwa_installed_description || 'The app is already installed.';
            }
        }
    }
}
sidenavInstallButton.addEventListener('click', handleInstallPrompt);

/**
 * プッシュ通知の現在の状態をチェックし、UIを更新
 */
async function updatePushStatus() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        pushEnableBtn.style.display = 'none';
        pushDisableBtn.style.display = 'none';
        pushStatus.textContent = 'Push Notifications not supported.';
        return;
    }

    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();

    if (Notification.permission === 'denied') {
        pushEnableBtn.style.display = 'none';
        pushDisableBtn.style.display = 'none';
        pushStatus.textContent = textData?.terminal_ui?.settings_popup?.push_denied_message || 'Browser notifications are blocked.';
    } else if (subscription) {
        pushEnableBtn.style.display = 'none';
        pushDisableBtn.style.display = 'inline-block';
        if (!isDipSwitchUpdating) {
            const pushSwitch = document.getElementById('dip-push-0');
            if (pushSwitch) pushSwitch.checked = true;
        }
        pushStatus.textContent = '';
    } else {
        pushEnableBtn.style.display = 'inline-block';
        pushDisableBtn.style.display = 'none';
        if (!isDipSwitchUpdating) {
            const pushSwitch = document.getElementById('dip-push-0');
            if (pushSwitch) pushSwitch.checked = false;
        }
        pushStatus.textContent = '';
    }
}

/**
 * プッシュ通知を有効化する処理
 */
async function enablePushNotifications() {
    const permission = await Notification.requestPermission();
    if (permission === 'granted') {
        await subscribeUser(); // pwa.jsの関数を呼び出し、完了を待つ
        await updatePushStatus(); // 購読状態が変更された後にUIを更新
    }
}

/**
 * プッシュ通知を無効化する処理
 */
async function disablePushNotifications() {
    await unsubscribeUser(); // pwa.jsの関数を呼び出す
    updatePushStatus();
}

document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadDipSwitchSettings(); // ページ読み込み時にDIPスイッチ設定を復元
    updateTerminalLayout();

    // PWAインストール関連の要素を取得
    settingsInstallButton = document.getElementById('pwa-install-btn');
    pwaInstallDescription = document.getElementById('pwa-install-description');

    // プッシュ通知関連の要素を取得
    pushEnableBtn = document.getElementById('push-enable-btn');
    pushDisableBtn = document.getElementById('push-disable-btn');
    pushStatus = document.getElementById('push-status');

    pushEnableBtn.addEventListener('click', enablePushNotifications);
    pushDisableBtn.addEventListener('click', disablePushNotifications);

    if (term.textarea) {
        term.textarea.addEventListener('compositionend', () => {
            setTimeout(() => {
                if (term.textarea) { term.textarea.value = ''; }
            }, 0);
        });
    }

    // DIPスイッチの変更を検知して設定を保存
    document.querySelector('.dip-switch-panel').addEventListener('change', () => {
        // isDipSwitchUpdatingフラグが立っている間は保存しない（無限ループ防止）
        if (!isDipSwitchUpdating) saveDipSwitchSettings();
    });
    const hamburgerBtn = document.getElementById('hamburger-btn');
    if (hamburgerBtn) {
        hamburgerBtn.addEventListener('click', openNav);
    }

    // サイドナビに閉じるボタンを追加
    const sidenav = document.getElementById('sidenav');
    const closeBtn = document.createElement('a');
    closeBtn.href = 'javascript:void(0)';
    closeBtn.className = 'closebtn';
    closeBtn.innerHTML = '&times;';
    closeBtn.onclick = closeNav;
    sidenav.appendChild(closeBtn);

    // サイドナビのPWAインストールボタンのテキストを設定
    const installButtonText = textData?.terminal_ui?.settings_popup?.pwa_install_button || 'Install App';
    sidenavInstallButton.textContent = installButtonText;

    // PWAインストールボタン用のコンテナをサイドナビに追加
    sidenav.appendChild(sidenavInstallContainer);

    // ファンクションキーの定義からサイドナビの項目を動的に生成
    for (const fkeyId in fkeyDefinitions) {
        const definition = fkeyDefinitions[fkeyId];
        const link = document.createElement('a');
        link.href = 'javascript:void(0)';
        link.textContent = definition.label;

        if (definition.action === 'toggle_logging') {
            link.id = 'sidenav-log-btn'; 
        }

        link.addEventListener('click', (e) => {
            e.preventDefault(); 
            if (definition.action === 'open_popup') { openPopup(); }
            else if (definition.action === 'toggle_logging') { socket.emit('toggle_logging'); }
            else if (definition.action === 'open_line_editor') { openLineEditor(); }
            else if (definition.action === 'open_multiline_editor') { openMultilineEditor(); }
            else if (definition.action === 'open_log_viewer') { openLogViewer(); }
            else if (definition.action === 'redirect') { window.location.href = definition.value; }
            else if (definition.action === 'open_bbs_list') {
                openBbsListPopup();
            }

            closeNav();
        });
        sidenav.appendChild(link);
    }

    // --- 設定ポップアップ内のタブ切り替え機能 --- 
    document.querySelector('.tab-buttons').addEventListener('click', (e) => {
        if (e.target.classList.contains('tab-button')) {
            const tabId = e.target.dataset.tab;
            document.querySelectorAll('.tab-button').forEach(button => button.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            e.target.classList.add('active');
            const activeContent = document.getElementById(tabId);
            if (activeContent) activeContent.classList.add('active');
        }
    });

    // 設定ポップアップのPWAインストールボタンにイベントリスナーを追加
    if (settingsInstallButton) settingsInstallButton.addEventListener('click', handleInstallPrompt);

    // --- Service Workerの登録と関連UIの更新 ---
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register(URLS.serviceWorker)
            .then(() => {
                console.log('Service Worker registered successfully.');
                // Service Workerが準備できたらプッシュ通知UIを更新
                updatePushStatus();
            })
            .catch(error => console.log('Service Worker registration failed:', error));
    }

    // --- モバイル用操作パネルのボタンイベント設定 --- 
    const keyMaps = {
        'bbs-btn-end-write': '^', 'bbs-btn-up': 'k', 'bbs-btn-down': 'j', 'bbs-btn-left': 'h',
        'bbs-btn-right': 'l', 'bbs-btn-read': '\r', 'bbs-btn-write': 'w', 'bbs-btn-delete': '*',
        'bbs-btn-help': '?', 'bbs-btn-exit': 'e', 'bbs-btn-y': 'y', 'bbs-btn-n': 'n',
        'chat-btn-exit': '^\r', 'chat-btn-telegram': '!\r', 'chat-btn-lock': '!l\r',
        'chat-btn-unlock': '!u\r', 'chat-btn-who': '!w\r', 'chat-btn-roominfo': '!r\r',
        'userpref-btn-1': '1', 'userpref-btn-2': '2', 'userpref-btn-3': '3', 'userpref-btn-4': '4',
        'userpref-btn-5': '5', 'userpref-btn-6': '6', 'userpref-btn-7': '7', 'userpref-btn-8': '8',
        'userpref-btn-9': '9', 'userpref-btn-0': '0', 'userpref-btn-backspace': '\x7f',
        'userpref-btn-help': '?', 'userpref-btn-enter': '\r',
        'mail-btn-write': 'w\r', 'mail-btn-read': 'r\r', 'mail-btn-list': 'l\r', 'mail-btn-exit': 'e\r',
        'bbs-entry-btn-write': 'w\r', 'bbs-entry-btn-read': 'r\r', 'bbs-entry-btn-exit': 'e\r',
        'top-btn-bbs': 'b\r', 'top-btn-chat': 'c\r', 'top-btn-mail': 'm\r', 'top-btn-program': 'p\r',
        'top-btn-userpref': 'u\r', 'top-btn-who': 'w\r', 'top-btn-telegram': '#\r',
        'top-btn-help': '?\r', 'top-btn-logoff': 'e\r',
        'plugin-btn-1': '1', 'plugin-btn-2': '2', 'plugin-btn-3': '3', 'plugin-btn-4': '4',
        'plugin-btn-5': '5', 'plugin-btn-6': '6', 'plugin-btn-7': '7', 'plugin-btn-8': '8',
        'plugin-btn-9': '9', 'plugin-btn-backspace': '\x7f', 'plugin-btn-0': '0',
        'plugin-btn-help': '?', 'plugin-btn-enter': '\r'
    };
    for (const [id, key] of Object.entries(keyMaps)) {
        const btn = document.getElementById(id);
        if (btn) { btn.addEventListener('click', () => { socket.emit('client_input', key); }); } 
    }
    document.getElementById('confirm-btn-y').addEventListener('click', () => { socket.emit('client_input', 'y\r'); }); 
    document.getElementById('confirm-btn-n').addEventListener('click', () => { socket.emit('client_input', 'n\r'); }); 

    // --- ウィンドウリサイズとキーボード表示のイベントハンドラ --- 
    window.addEventListener('resize', debounce(updateTerminalLayout, 100));
    if ('visualViewport' in window) {
        const vv = window.visualViewport;
        const handleViewportResize = () => {
            const isMobile = window.matchMedia('(max-width: 992px)').matches;
            if (!isMobile) {
                document.body.style.height = '';
                return;
            }
            document.body.style.height = `${vv.height}px`;
            const keyboardHeight = window.innerHeight - vv.height;
            const isKeyboardVisible = keyboardHeight > 80;
            const monitorScreen = document.querySelector('.monitor-screen');
            if (isKeyboardVisible) {
                monitorScreen.style.paddingBottom = '0px';
            } else {
                const storedHeight = monitorScreen.dataset.controlsHeight;
                if (storedHeight) {
                    monitorScreen.style.paddingBottom = `${storedHeight}px`;
                }
                document.body.style.height = '';
            }
            setTimeout(() => {
                try {
                    fitAddon.fit();
                    if (isKeyboardVisible) {
                        window.scrollTo(0, document.body.scrollHeight);
                    }
                } catch (e) { /* ignore */ }
            }, 150);
        };
        vv.addEventListener('resize', handleViewportResize);
    }

    // 画面右上の「一番下に移動」ボタンのイベントリスナー
    const scrollToBottomBtn = document.getElementById('scroll-to-bottom-btn');
    if (scrollToBottomBtn) {
        scrollToBottomBtn.addEventListener('click', () => {
            term.scrollToBottom();
        });
    }
});

// --- ハンバーガーメニュー（サイドナビ）の開閉ロジック --- 
function openNav() {
    document.getElementById("sidenav").style.width = "250px";
}

function closeNav() {
    document.getElementById("sidenav").style.width = "0";
} 

/**
 * 関数が連続して呼び出されるのを防ぎ、最後の呼び出しから指定時間後に一度だけ実行
 * @param {Function} func - デバウンス対象の関数
 * @param {number} wait - 待機時間 (ミリ秒)
 * @returns {Function}
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => { clearTimeout(timeout); func(...args); };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * 新しいPasskeyの登録フローを開始
 */
async function registerNewPasskey(callback) {
    let options;
    try {
        const resp = await fetch(URLS.passkeyRegisterOptions, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Could not get registration options.');
        }
        options = await resp.json();
    } catch (e) {
        const errorMessage = `Error getting registration options: ${e.message}`;
        console.error(errorMessage);
        if (callback) callback({ success: false, message: errorMessage });
        return;
    }

    // サーバーから受け取ったBase64URL文字列をArrayBufferに変換
    options.challenge = base64urlToBuffer(options.challenge);
    if (options.excludeCredentials) {
        for (let cred of options.excludeCredentials) {
            cred.id = base64urlToBuffer(cred.id);
        }
    }
    options.user.id = base64urlToBuffer(options.user.id);

    let credential;
    try {
        // ブラウザのAPIを呼び出してPasskey作成を要求
        credential = await navigator.credentials.create({ publicKey: options });
    } catch (e) {
        const errorMessage = `Registration ceremony failed: ${e.name}`;
        if (callback) callback({ success: false, message: errorMessage });
        return;
    }

    // サーバーに検証をリクエストするために、レスポンスをBase64URL文字列に変換
    const registrationResponse = {
        id: credential.id,
        rawId: bufferToBase64url(credential.rawId),
        response: {
            clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
            attestationObject: bufferToBase64url(credential.response.attestationObject),
        },
        type: credential.type,
    };

    try {
        const verificationResp = await fetch(URLS.passkeyVerifyRegistration, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                credential: registrationResponse,
                nickname: 'My Passkey' 
            }),
        });
        const verificationJSON = await verificationResp.json();
        if (verificationJSON && verificationJSON.verified) {
            if (callback) callback({ success: true, message: textData.passkey_management.register_success || 'Passkey registered successfully.' });
        } else {
            const serverError = verificationJSON.error || "Verification failed on server.";
            throw new Error(serverError);
        }
    } catch (e) {
        const errorMessage = `Error during verification: ${e.message}`;
        console.error(errorMessage);
        if (callback) callback({ success: false, message: errorMessage });
    }
}