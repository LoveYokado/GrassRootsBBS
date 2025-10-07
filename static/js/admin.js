// SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
// SPDX-License-Identifier: MIT

document.addEventListener('DOMContentLoaded', function () {
    const sidebarToggle = document.getElementById('sidebar-toggle');
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function () {
            document.body.classList.toggle('sidebar-closed');
        });
    }
});