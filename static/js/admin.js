// SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
// SPDX-License-Identifier: MIT

document.addEventListener('DOMContentLoaded', function () {
    const hamburgerBtn = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    
    if (!hamburgerBtn || !sidebar) {
        console.error('Required elements for sidebar functionality not found.', {
            hamburgerBtn: !!hamburgerBtn,
            sidebar: !!sidebar
        });
        return;
    }

    // ハンバーガーボタンがクリックされたら、サイドバーの表示/非表示を切り替える
    hamburgerBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        document.body.classList.toggle('sidebar-open');
    });

    // サイドバーの外側がクリックされたら、サイドバーを閉じる
    document.addEventListener('click', function (e) {
        if (document.body.classList.contains('sidebar-open')) {
            const isClickInsideSidebar = sidebar.contains(e.target);
            const isClickOnHamburger = hamburgerBtn.contains(e.target);
            if (!isClickInsideSidebar && !isClickOnHamburger) {
                document.body.classList.remove('sidebar-open');
            }
        }
    });

    // --- System Settings ---
    // 'Fill with all board IDs' ボタン
    const fillButton = document.getElementById('fill-board-ids-btn');
    const explorationListTextarea = document.getElementById('default_exploration_list');

    if (fillButton && explorationListTextarea && typeof allBoardIds !== 'undefined') {
        fillButton.addEventListener('click', function () {
            explorationListTextarea.value = allBoardIds.join(',');
        });
    }
});

/**
 * 指定されたURLにPOSTリクエストを送信する動的なフォームを作成してサブミット
 * @param {string} url - フォームの送信先URL。
 * @param {string} confirmMessage - ユーザーに表示する確認メッセージ。
 */
function submitActionForm(url, confirmMessage) {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = url;
    document.body.appendChild(form);
    form.submit();
}