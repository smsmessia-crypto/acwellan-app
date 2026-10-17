const API_URL = "http://127.0.0.1:8000/api";
let bankChartInstance = null;

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        const target = this.dataset.tab;
        document.querySelectorAll('.tab-content').forEach(t => {
            t.classList.toggle('active', t.id === 'tab-' + target);
        });
        if (target === 'history') { loadHistory(); loadStats(); populateMonthFilter(); }
        if (target === 'results') loadResults();
        if (target === 'leagues') loadLeagueStats();
        if (target === 'chart') loadChart();
        if (target === 'compare') loadEdgeComparison();
    });
});

async function loadMatches() {
    const league = document.getElementById('league-filter').value;
    const date = document.getElementById('date-filter').value;

    let url = API_URL + '/matches?league=' + league;
    if (date) url += '&date=' + date;

    const box = document.querySelector('.matches-list');
    box.innerHTML = '<p style="color:#71717a;text-align:center;padding:40px;">Загрузка...</p>';

    try {
        const resp = await fetch(url);
        const matches = await resp.json();

        if (!matches.length) {
            box.innerHTML = '<p style="color:#71717a;text-align:center;padding:40px;">Матчей не найдено</p>';
            return;
        }

        let html = '';
        for (let i = 0; i < matches.length; i++) {
            const m = matches[i];
            html += '<div class="match-card">';
            html += '<div class="match-header"><span class="league">' + m.league_name + '</span><span class="time">' + formatDate(m.match_date) + '</span></div>';
            html += '<div class="match-teams">';
            html += '<div class="team">' + m.home_team + '</div>';
            html += '<div class="score">— : —</div>';
            html += '<div class="team">' + m.away_team + '</div>';
            html += '</div>';
            html += '<button type="button" class="predict-btn" data-match-id="' + m.id + '">Прогноз AI</button>';
            html += '<div id="result-' + m.id + '" class="match-result" style="display:none;"></div>';
            html += '</div>';
        }
        box.innerHTML = html;

        document.querySelectorAll('.predict-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                predictMatch(this.getAttribute('data-match-id'));
            });
        });
    } catch (e) {
        box.innerHTML = '<p style="color:#ef4444;text-align:center;padding:40px;">Ошибка загрузки</p>';
    }
}

async function predictMatch(matchId, isRefresh = false) {
    const box = document.getElementById('result-' + matchId);
    if (!box) return;

    box.style.display = 'block';

    const url = isRefresh ? API_URL + '/predict-refresh/' + matchId : API_URL + '/predict/' + matchId;

    if (!isRefresh) {
        box.innerHTML = '<p style="color:#71717a;padding:12px 0;">Нейросеть анализирует матч...</p>';
    }

    try {
        const resp = await fetch(url, { method: 'POST' });
        const data = await resp.json();

        let html = '';

        const refreshedAt = data.refreshed_at ? new Date(data.refreshed_at) : new Date();
        const timeStr = refreshedAt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

        html += '<div class="refresh-header">';
        html += '<span class="refresh-time">Обновлено: ' + timeStr + '</span>';
        html += '<button type="button" class="refresh-btn" onclick="predictMatch(' + matchId + ', true)">🔄 Обновить</button>';
        html += '</div>';

        html += '<div class="bet-list-wrapper">';
        html += '<h4 class="section-title">СТАВКИ</h4>';
        if (data.predictions && data.predictions.length) {
            for (let i = 0; i < data.predictions.length; i++) {
                const p = data.predictions[i];
                const edge = p.edge_pct !== undefined ? p.edge_pct : 0;
                const score = p.score !== undefined ? p.score : 0;
                const vClass = p.value_class || 'value-neutral';
                const vSign = edge > 0 ? '+' : '';
                const marketProb = p.market_prob !== undefined ? Math.round(p.market_prob * 100) : 0;
                const modelProb = Math.round(p.confidence * 100);
                const source = p.source || 'model';
                const sourceLabel = source === 'real'
                    ? '<span class="source-real">✓ реальный</span>'
                    : '<span class="source-model">⚙ модель</span>';

                html += '<div class="bet-card ' + vClass + '-card">';
                html += '<div class="bet-rank">#' + (i + 1) + '</div>';
                html += '<div class="bet-info">';
                html += '<div class="bet-name">' + p.bet_name + ' ' + sourceLabel + '</div>';
                html += '<div class="bet-meta">';
                html += '<span class="odds">Кэф: ' + Number(p.odds).toFixed(2) + '</span>';
                html += '<span class="confidence">Модель: ' + modelProb + '%</span>';
                html += '<span class="market">Рынок: ' + marketProb + '%</span>';
                html += '<span class="value ' + vClass + '">Edge: ' + vSign + edge.toFixed(1) + '%</span>';
                html += '<span class="score">Score: ' + score.toFixed(2) + '</span>';
                html += '</div></div></div>';
            }
        } else {
            html += '<p style="color:#71717a;">Ставок не найдено</p>';
        }
        html += '</div>';

        if (data.simulation) {
            const s = data.simulation;
            html += '<h4 class="section-title">СИМУЛЯЦИЯ ' + s.n_sims + ' МАТЧЕЙ</h4>';
            html += '<p class="sim-text">';
            html += '<b>Исходы:</b> П1 ' + (s.outcomes.home_win * 100).toFixed(1) + '% | ';
            html += 'Х ' + (s.outcomes.draw * 100).toFixed(1) + '% | ';
            html += 'П2 ' + (s.outcomes.away_win * 100).toFixed(1) + '%<br>';
            html += '<b>Тоталы:</b> ТБ 1.5 ' + (s.over_1_5 * 100).toFixed(1) + '% | ';
            html += 'ТБ 2.5 ' + (s.over_2_5 * 100).toFixed(1) + '% | ';
            html += 'ТБ 3.5 ' + (s.over_3_5 * 100).toFixed(1) + '%<br>';
            html += '<b>Обе забьют:</b> ' + (s.btts_yes * 100).toFixed(1) + '%';
            html += '</p>';
        }

        box.innerHTML = html;
    } catch (e) {
        box.innerHTML = '<p style="color:#ef4444;padding:12px 0;">Ошибка: ' + e.message + '</p>';
    }
}

async function predictBatch() {
    const league = document.getElementById('league-filter').value;
    const date = document.getElementById('date-filter').value;

    const btn = document.getElementById('batch-predict-btn');
    const progress = document.getElementById('batch-progress');

    btn.disabled = true;
    btn.textContent = '⏳ Обработка...';
    progress.style.display = 'block';
    progress.innerHTML = '<p style="color:#71717a;">Нейросеть обрабатывает матчи...</p>';

    let url = API_URL + '/predict-batch?league=' + league;
    if (date) url += '&date=' + date;

    try {
        const resp = await fetch(url, { method: 'POST' });
        const data = await resp.json();

        progress.innerHTML = `
            <div class="batch-result">
                <h3>✅ Обработка завершена</h3>
                <div class="batch-stats">
                    <div>Всего матчей: <b>${data.total_matches}</b></div>
                    <div>Обработано: <b class="win">${data.processed}</b></div>
                    <div>Пропущено: <b>${data.skipped}</b></div>
                    <div>Создано ставок: <b class="win">${data.created_predictions}</b></div>
                </div>
                <button type="button" class="batch-close" onclick="document.getElementById('batch-progress').style.display='none'">Закрыть</button>
            </div>
        `;

        loadMatches();
    } catch (e) {
        progress.innerHTML = '<p style="color:#ef4444;">Ошибка: ' + e.message + '</p>';
    } finally {
        btn.disabled = false;
        btn.textContent = '⚡ Прогноз на все матчи';
    }
}

async function loadHistory() {
    const box = document.querySelector('.history-list');
    box.innerHTML = '<p style="color:#71717a;text-align:center;padding:40px;">Загрузка...</p>';

    const league = document.getElementById('history-league-filter').value;
    const result = document.getElementById('history-result-filter').value;
    const month = document.getElementById('history-month-filter').value;

    let url = API_URL + '/history?league=' + league + '&result=' + result + '&month=' + month;

    try {
        const resp = await fetch(url);
        const history = await resp.json();

        if (!history.length) {
            box.innerHTML = '<p style="color:#71717a;text-align:center;padding:40px;">Прогнозов не найдено</p>';
            return;
        }

        let html = '';
        for (const item of history) {
            html += '<div class="history-card">';
            html += '<div class="history-match">';
            html += '<span>' + item.match.home_team + ' — ' + item.match.away_team + '</span>';
            html += '<div class="history-actions">';
            html += '<span class="history-date">' + formatDate(item.match.match_date) + '</span>';
            html += '<button type="button" class="delete-btn" data-delete-id="' + item.match.id + '">✕</button>';
            html += '</div></div>';
            html += '<div class="history-bets">';
            for (const p of item.predictions) {
                const nameLower = p.bet_name.toLowerCase();
                const isManual = nameLower.includes('углов') || nameLower.includes('карточ');

                html += '<div class="history-bet">';
                html += '<span class="bet-name">' + p.bet_name + '</span>';
                html += '<span class="odds">' + Number(p.odds).toFixed(2) + '</span>';
                html += '<span class="result ' + (p.result || 'pending') + '">';
                html += (p.result ? p.result.toUpperCase() : 'ОЖИДАНИЕ');
                html += '</span>';

                if (isManual) {
                    html += '<div class="manual-btns">';
                    html += '<button type="button" class="manual-btn win" data-pred-id="' + p.id + '" data-result="win" title="Зашло">✓</button>';
                    html += '<button type="button" class="manual-btn lose" data-pred-id="' + p.id + '" data-result="lose" title="Не зашло">✕</button>';
                    if (p.result) {
                        html += '<button type="button" class="manual-btn reset" data-pred-id="' + p.id + '" data-result="reset" title="Сбросить">↺</button>';
                    }
                    html += '</div>';
                }

                html += '</div>';
            }
            html += '</div></div>';
        }
        box.innerHTML = html;

        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                deleteHistory(this.getAttribute('data-delete-id'));
            });
        });

        document.querySelectorAll('.manual-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const predId = this.getAttribute('data-pred-id');
                const resultVal = this.getAttribute('data-result');
                updatePredictionResult(predId, resultVal);
            });
        });
    } catch (e) {
        box.innerHTML = '<p style="color:#ef4444;text-align:center;padding:40px;">Ошибка загрузки</p>';
    }
}

async function updatePredictionResult(predId, result) {
    try {
        const resp = await fetch(API_URL + '/prediction/' + predId + '?result=' + result, {
            method: 'PATCH'
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        loadHistory();
        loadStats();
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}

async function populateMonthFilter() {
    const sel = document.getElementById('history-month-filter');
    if (!sel) return;
    const currentVal = sel.value;

    try {
        const resp = await fetch(API_URL + '/history?league=all&result=all&month=all');
        const history = await resp.json();

        const months = new Set();
        for (const item of history) {
            if (item.match && item.match.match_date) {
                const d = new Date(item.match.match_date);
                const m = String(d.getMonth() + 1).padStart(2, '0');
                const y = d.getFullYear();
                months.add(`${m}.${y}`);
            }
        }

        const sorted = Array.from(months).sort().reverse();

        sel.innerHTML = '<option value="all">Все месяцы</option>';
        for (const m of sorted) sel.innerHTML += `<option value="${m}">${m}</option>`;
        sel.value = currentVal;
    } catch (e) {}
}

async function loadStats() {
    const box = document.getElementById('stats-block');
    if (!box) return;

    try {
        const resp = await fetch(API_URL + '/stats');
        const s = await resp.json();

        box.innerHTML = `
            <div class="stat-card"><div class="stat-value">${s.total}</div><div class="stat-label">Всего</div></div>
            <div class="stat-card"><div class="stat-value win">${s.wins}</div><div class="stat-label">WIN</div></div>
            <div class="stat-card"><div class="stat-value lose">${s.loses}</div><div class="stat-label">LOSE</div></div>
            <div class="stat-card"><div class="stat-value">${s.accuracy}%</div><div class="stat-label">Точность</div></div>
        `;
    } catch (e) {}
}

async function loadResults() {
    const overallBox = document.getElementById('overall-block');
    const tableBox = document.getElementById('monthly-table');

    overallBox.innerHTML = '<p style="color:#71717a;text-align:center;">Загрузка...</p>';
    tableBox.innerHTML = '';

    try {
        const resp = await fetch(API_URL + '/monthly-results');
        const data = await resp.json();
        const o = data.overall;

        const bankSign = o.bank >= 0 ? '+' : '';
        const bankClass = o.bank > 0 ? 'win' : (o.bank < 0 ? 'lose' : '');

        overallBox.innerHTML = `
            <div class="stat-card"><div class="stat-value">${o.total}</div><div class="stat-label">Ставок</div></div>
            <div class="stat-card"><div class="stat-value win">${o.wins}</div><div class="stat-label">WIN</div></div>
            <div class="stat-card"><div class="stat-value lose">${o.loses}</div><div class="stat-label">LOSE</div></div>
            <div class="stat-card"><div class="stat-value">${o.accuracy}%</div><div class="stat-label">Точность</div></div>
            <div class="stat-card wide"><div class="stat-value ${bankClass}">${bankSign}${o.bank}$</div><div class="stat-label">Общий банк</div></div>
        `;

        if (!data.monthly.length) {
            tableBox.innerHTML = '<p style="color:#71717a;text-align:center;padding:40px;">Пока нет завершённых прогнозов</p>';
            return;
        }

        let html = '<table class="monthly"><thead><tr>';
        html += '<th>Месяц</th><th>Ставок</th><th>WIN</th><th>LOSE</th><th>Банк</th>';
        html += '</tr></thead><tbody>';

        for (const m of data.monthly) {
            const sign = m.bank >= 0 ? '+' : '';
            const cls = m.bank > 0 ? 'win' : (m.bank < 0 ? 'lose' : '');
            html += `<tr><td>${m.month}</td><td>${m.total}</td><td class="win">${m.wins}</td><td class="lose">${m.loses}</td><td class="${cls}"><b>${sign}${m.bank}$</b></td></tr>`;
        }

        const sign = o.bank >= 0 ? '+' : '';
        const cls = o.bank > 0 ? 'win' : (o.bank < 0 ? 'lose' : '');
        html += `<tr class="total-row"><td>Итого</td><td>${o.total}</td><td class="win">${o.wins}</td><td class="lose">${o.loses}</td><td class="${cls}"><b>${sign}${o.bank}$</b></td></tr>`;

        html += '</tbody></table>';
        tableBox.innerHTML = html;
    } catch (e) {}
}

async function loadLeagueStats() {
    const box = document.getElementById('leagues-table');
    box.innerHTML = '<p style="color:#71717a;text-align:center;padding:40px;">Загрузка...</p>';

    try {
        const resp = await fetch(API_URL + '/league-stats');
        const data = await resp.json();

        if (!data.leagues.length) {
            box.innerHTML = '<p style="color:#71717a;text-align:center;padding:40px;">Пока нет завершённых прогнозов</p>';
            return;
        }

        let html = '<table class="monthly"><thead><tr>';
        html += '<th>Лига</th><th>Ставок</th><th>WIN</th><th>LOSE</th><th>Точность</th><th>Банк</th>';
        html += '</tr></thead><tbody>';

        for (const l of data.leagues) {
            const sign = l.bank >= 0 ? '+' : '';
            const cls = l.bank > 0 ? 'win' : (l.bank < 0 ? 'lose' : '');
            let accCls = '';
            if (l.accuracy >= 55) accCls = 'win';
            else if (l.accuracy < 45) accCls = 'lose';

            html += `<tr><td>${l.league_name}</td><td>${l.total}</td><td class="win">${l.wins}</td><td class="lose">${l.loses}</td><td class="${accCls}"><b>${l.accuracy}%</b></td><td class="${cls}"><b>${sign}${l.bank}$</b></td></tr>`;
        }

        const o = data.overall;
        const sign = o.bank >= 0 ? '+' : '';
        const cls = o.bank > 0 ? 'win' : (o.bank < 0 ? 'lose' : '');
        html += `<tr class="total-row"><td>Итого</td><td>${o.total}</td><td class="win">${o.wins}</td><td class="lose">${o.loses}</td><td><b>${o.accuracy}%</b></td><td class="${cls}"><b>${sign}${o.bank}$</b></td></tr>`;

        html += '</tbody></table>';
        box.innerHTML = html;
    } catch (e) {
        box.innerHTML = '<p style="color:#ef4444;text-align:center;padding:40px;">Ошибка загрузки</p>';
    }
}

async function loadChart() {
    const accuracyBox = document.getElementById('accuracy-block');

    try {
        const accResp = await fetch(API_URL + '/accuracy-30d');
        const acc = await accResp.json();

        const d30 = acc.last_30_days;
        const dall = acc.all_time;

        const d30Sign = d30.bank >= 0 ? '+' : '';
        const d30Cls = d30.bank > 0 ? 'win' : (d30.bank < 0 ? 'lose' : '');
        const allSign = dall.bank >= 0 ? '+' : '';
        const allCls = dall.bank > 0 ? 'win' : (dall.bank < 0 ? 'lose' : '');

        accuracyBox.innerHTML = `
            <div class="stat-card wide2">
                <div class="stat-label">Последние 30 дней</div>
                <div class="stat-row">
                    <span>Ставок: <b>${d30.total}</b></span>
                    <span class="win">WIN: <b>${d30.wins}</b></span>
                    <span class="lose">LOSE: <b>${d30.loses}</b></span>
                    <span>Точность: <b>${d30.accuracy}%</b></span>
                    <span class="${d30Cls}">Банк: <b>${d30Sign}${d30.bank}$</b></span>
                </div>
            </div>
            <div class="stat-card wide2">
                <div class="stat-label">За всё время</div>
                <div class="stat-row">
                    <span>Ставок: <b>${dall.total}</b></span>
                    <span class="win">WIN: <b>${dall.wins}</b></span>
                    <span class="lose">LOSE: <b>${dall.loses}</b></span>
                    <span>Точность: <b>${dall.accuracy}%</b></span>
                    <span class="${allCls}">Банк: <b>${allSign}${dall.bank}$</b></span>
                </div>
            </div>
        `;

        const chartResp = await fetch(API_URL + '/bank-chart');
        const chartData = await chartResp.json();

        const canvas = document.getElementById('bank-chart');
        const ctx = canvas.getContext('2d');

        if (bankChartInstance) bankChartInstance.destroy();

        if (!chartData.data.length) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#71717a';
            ctx.font = '16px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Пока нет завершённых прогнозов', canvas.width / 2, canvas.height / 2);
            return;
        }

        const labels = chartData.data.map(d => d.month);
        const banks = chartData.data.map(d => d.cumulative);

        bankChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Банк ($)',
                    data: banks,
                    borderColor: '#60a5fa',
                    backgroundColor: 'rgba(96, 165, 250, 0.15)',
                    borderWidth: 3,
                    tension: 0.3,
                    fill: true,
                    pointBackgroundColor: '#60a5fa',
                    pointBorderColor: '#1e3a8a',
                    pointRadius: 6,
                    pointHoverRadius: 9,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#e4e4e7', font: { size: 14 } } },
                    tooltip: { callbacks: { label: ctx => 'Банк: ' + (ctx.parsed.y >= 0 ? '+' : '') + ctx.parsed.y + '$' } }
                },
                scales: {
                    x: { ticks: { color: '#9ca3af', font: { size: 12 } }, grid: { color: '#27272a' } },
                    y: { ticks: { color: '#9ca3af', font: { size: 12 }, callback: v => (v >= 0 ? '+' : '') + v + '$' }, grid: { color: '#27272a' } }
                }
            }
        });
    } catch (e) {
        accuracyBox.innerHTML = '<p style="color:#ef4444;">Ошибка загрузки</p>';
    }
}

async function loadEdgeComparison() {
    const overallBox = document.getElementById('edge-overall-block');
    const tableBox = document.getElementById('edge-table');

    overallBox.innerHTML = '<p style="color:#71717a;text-align:center;">Загрузка...</p>';
    tableBox.innerHTML = '';

    try {
        const resp = await fetch(API_URL + '/edge-comparison');
        const data = await resp.json();
        const o = data.overall;

        const bankSign = o.bank >= 0 ? '+' : '';
        const bankClass = o.bank > 0 ? 'win' : (o.bank < 0 ? 'lose' : '');
        const roiSign = o.roi >= 0 ? '+' : '';
        const roiClass = o.roi > 0 ? 'win' : (o.roi < 0 ? 'lose' : '');

        overallBox.innerHTML = `
            <div class="stat-card"><div class="stat-value">${o.total}</div><div class="stat-label">Всего ставок</div></div>
            <div class="stat-card"><div class="stat-value win">${o.wins}</div><div class="stat-label">WIN</div></div>
            <div class="stat-card"><div class="stat-value lose">${o.loses}</div><div class="stat-label">LOSE</div></div>
            <div class="stat-card"><div class="stat-value">${o.accuracy}%</div><div class="stat-label">Точность</div></div>
            <div class="stat-card"><div class="stat-value">${o.avg_edge}%</div><div class="stat-label">Средний Edge</div></div>
            <div class="stat-card"><div class="stat-value ${bankClass}">${bankSign}${o.bank}$</div><div class="stat-label">Общий банк</div></div>
            <div class="stat-card"><div class="stat-value ${roiClass}">${roiSign}${o.roi}%</div><div class="stat-label">ROI</div></div>
        `;

        if (!data.groups.length) {
            tableBox.innerHTML = '<p style="color:#71717a;text-align:center;padding:40px;">Пока нет завершённых прогнозов</p>';
            return;
        }

        let html = '<table class="monthly"><thead><tr>';
        html += '<th>Группа</th><th>Ставок</th><th>WIN</th><th>LOSE</th><th>Точность</th><th>Ср. Edge</th><th>Банк</th>';
        html += '</tr></thead><tbody>';

        for (const g of data.groups) {
            const sign = g.bank >= 0 ? '+' : '';
            const cls = g.bank > 0 ? 'win' : (g.bank < 0 ? 'lose' : '');
            let accCls = '';
            if (g.accuracy >= 55) accCls = 'win';
            else if (g.accuracy < 45) accCls = 'lose';

            let rowCls = '';
            if (g.key === 'edge_gt_5') rowCls = 'row-best';
            else if (g.key === 'edge_neg') rowCls = 'row-worst';

            html += `<tr class="${rowCls}">`;
            html += `<td><b>${g.label}</b></td>`;
            html += `<td>${g.total}</td>`;
            html += `<td class="win">${g.wins}</td>`;
            html += `<td class="lose">${g.loses}</td>`;
            html += `<td class="${accCls}"><b>${g.accuracy}%</b></td>`;
            html += `<td>${g.avg_edge}%</td>`;
            html += `<td class="${cls}"><b>${sign}${g.bank}$</b></td>`;
            html += '</tr>';
        }

        html += '</tbody></table>';
        tableBox.innerHTML = html;
    } catch (e) {
        overallBox.innerHTML = '<p style="color:#ef4444;">Ошибка загрузки</p>';
    }
}

async function deleteHistory(matchId) {
    if (!confirm('Удалить этот прогноз?')) return;
    try {
        await fetch(API_URL + '/history/' + matchId, { method: 'DELETE' });
        loadHistory();
        loadStats();
    } catch (e) {
        alert('Ошибка удаления: ' + e.message);
    }
}

function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
         + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

document.getElementById('date-filter').valueAsDate = new Date();
document.getElementById('league-filter').addEventListener('change', loadMatches);
document.getElementById('date-filter').addEventListener('change', loadMatches);
document.getElementById('history-league-filter').addEventListener('change', loadHistory);
document.getElementById('history-result-filter').addEventListener('change', loadHistory);
document.getElementById('history-month-filter').addEventListener('change', loadHistory);
document.getElementById('export-csv-btn').addEventListener('click', function() {
    window.open(API_URL + '/export-csv', '_blank');
});
document.getElementById('batch-predict-btn').addEventListener('click', predictBatch);

loadMatches();