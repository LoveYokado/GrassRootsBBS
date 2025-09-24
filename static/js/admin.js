// SPDX-FileCopyrightText: 2025 mid.yuki(LoveYokado)
// SPDX-License-Identifier: MIT

document.addEventListener('DOMContentLoaded', function () {
    // --- article_search.html: 「すべて選択」チェックボックスの制御 ---
    const selectAllCheckbox = document.getElementById('select-all-articles');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function (e) {
            const checkboxes = document.querySelectorAll('.article-checkbox');
            checkboxes.forEach(checkbox => {
                checkbox.checked = e.target.checked;
            });
        });
    }

    // --- dashboard.html: Chart.jsの初期化 ---
    // chartData変数は、HTML内の<script>タグで定義されていることを想定
    const activityChartCanvas = document.getElementById('activityChart');
    if (activityChartCanvas && typeof chartData !== 'undefined') {
        const ctx = activityChartCanvas.getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: chartData.labels,
                datasets: [{
                    label: 'New Users',
                    data: chartData.user_registrations,
                    borderColor: '#87cefa', // Light Blue
                    backgroundColor: 'rgba(135, 206, 250, 0.2)',
                    tension: 0.1,
                    fill: true,
                }, {
                    label: 'New Articles',
                    data: chartData.article_posts,
                    borderColor: '#90ee90', // Light Green
                    backgroundColor: 'rgba(144, 238, 144, 0.2)',
                    tension: 0.1,
                    fill: true,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#ffffff', stepSize: 1 }, grid: { color: 'rgba(255, 255, 255, 0.1)' } },
                    x: { ticks: { color: '#ffffff' }, grid: { color: 'rgba(255, 255, 255, 0.1)' } }
                },
                plugins: {
                    legend: { labels: { color: '#ffffff' } }
                }
            }
        });
    }

    // --- system_settings.html: 掲示板IDをテキストエリアにフィルインする機能 ---
    const fillBoardIdsBtn = document.getElementById('fill-board-ids-btn');
    if (fillBoardIdsBtn && typeof allBoardIds !== 'undefined') {
        fillBoardIdsBtn.addEventListener('click', function () {
            const textarea = document.getElementById('default_exploration_list');
            textarea.value = allBoardIds.join(',');
        });
    }

});