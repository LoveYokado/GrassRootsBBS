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

    // ハンバーガーボタンをクリックしてサイドバーを開閉
    hamburgerBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        document.body.classList.toggle('sidebar-open');
    });

    // ドキュメントの他の部分をクリックしてサイドバーを閉じる
    document.addEventListener('click', function (e) {
        if (document.body.classList.contains('sidebar-open')) {
            const isClickInsideSidebar = sidebar.contains(e.target);
            const isClickOnHamburger = hamburgerBtn.contains(e.target);
            if (!isClickInsideSidebar && !isClickOnHamburger) {
                document.body.classList.remove('sidebar-open');
            }
        }
    });
});