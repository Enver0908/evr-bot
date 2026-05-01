/**
 * EVR Trading Platform — Dashboard Application
 * ==============================================
 * Auth, Dashboard, Chart.js EVR Total Map, Strategy Explainer
 */

const API = '';  // Same origin

// ─── State ──────────────────────────────────────────────────
let token = localStorage.getItem('evr_token') || null;
let currentUser = null;
let evrChart = null;
let chartData = null;
let currentRange = 0; // 0 = ALL

// ─── DOM Refs ───────────────────────────────────────────────
const $  = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const authScreen   = $('#auth-screen');
const dashScreen    = $('#dashboard-screen');
const loginForm     = $('#login-form');
const registerForm  = $('#register-form');
const authError     = $('#auth-error');

// ─── Helpers ────────────────────────────────────────────────

function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return String(unsafe)
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

async function api(path, method = 'GET', body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (token) opts.headers['Authorization'] = `Bearer ${token}`;
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(`${API}${path}`, opts);
    let data;
    try {
        data = await res.json();
    } catch (e) {
        throw new Error(`HTTP ${res.status}: Sunucu hatasi`);
    }
    if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
    }
    return data;
}

function showToast(msg, type = 'success') {
    const t = $('#toast');
    t.textContent = msg;
    t.className = `toast ${type}`;
    t.classList.remove('hidden');
    setTimeout(() => t.classList.add('hidden'), 3500);
}

function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('tr-TR') + ' ' + d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
}

function formatNum(n, dec = 2) {
    if (n === null || n === undefined) return '—';
    return Number(n).toLocaleString('tr-TR', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function evrLabel(val) {
    if (val <= 2.0) return 'Asiri Korku';
    if (val <= 4.0) return 'Korku';
    if (val <= 6.0) return 'Notr';
    if (val <= 8.0) return 'Acgozluluk';
    return 'Asiri Acgozluluk';
}

function evrColor(val) {
    if (val <= 3.2) return '#15803d'; // Asiri Korku (Koyu Yesil)
    if (val >= 8.5) return '#b91c1c'; // Asiri Acgoz (Koyu Kirmizi)
    return '#ffffff'; // Bekleme / Standart (Beyaz)
}


// ─── Screen Switching ───────────────────────────────────────

function showAuth() {
    authScreen.classList.add('active');
    dashScreen.classList.remove('active');
}

function showDashboard() {
    authScreen.classList.remove('active');
    dashScreen.classList.add('active');
    loadDashboard();
    loadChartData();

    // Set default end date to today
    const endInput = document.getElementById('bt-end-date');
    if (endInput && !endInput.value) {
        endInput.value = new Date().toISOString().split('T')[0];
    }
}

// ─── Nav Tab Switching ──────────────────────────────────────

const navTabs = document.querySelectorAll('.nav-tab');
navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        navTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const screen = tab.dataset.screen;
        const dashContent = document.getElementById('dashboard-content');
        const btContent = document.getElementById('backtest-content');
        const pfContent = document.getElementById('portfolio-content');
        dashContent.classList.add('hidden');
        btContent.classList.add('hidden');
        if (pfContent) pfContent.classList.add('hidden');
        if (screen === 'dashboard') {
            dashContent.classList.remove('hidden');
        } else if (screen === 'backtest') {
            btContent.classList.remove('hidden');
        } else if (screen === 'portfolio') {
            if (pfContent) pfContent.classList.remove('hidden');
            portfolioLoaded = false;
            loadPortfolio();
        }
    });
});


// ─── Auth ───────────────────────────────────────────────────

$$('.auth-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        $$('.auth-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const target = tab.dataset.tab;
        if (target === 'login') {
            loginForm.classList.add('active');
            registerForm.classList.remove('active');
        } else {
            loginForm.classList.remove('active');
            registerForm.classList.add('active');
        }
        authError.classList.add('hidden');
    });
});

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    authError.classList.add('hidden');
    const btn = loginForm.querySelector('.btn');
    const span = btn.querySelector('span');
    span.textContent = 'Giris yapiliyor...';
    btn.disabled = true;

    try {
        const data = await api('/login', 'POST', {
            email: $('#login-email').value,
            password: $('#login-password').value,
        });
        if (data.access_token) {
            token = data.access_token;
            localStorage.setItem('evr_token', token);
            showDashboard();
        } else {
            throw new Error('Token alinamadi.');
        }
    } catch (err) {
        console.error('Login error:', err);
        authError.textContent = err.message;
        authError.classList.remove('hidden');
    } finally {
        span.textContent = 'Giris Yap';
        btn.disabled = false;
    }
});

registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    authError.classList.add('hidden');
    const btn = registerForm.querySelector('.btn');
    const span = btn.querySelector('span');
    span.textContent = 'Kayit yapiliyor...';
    btn.disabled = true;

    try {
        const data = await api('/register', 'POST', {
            email: $('#reg-email').value,
            password: $('#reg-password').value,
        });
        if (data.access_token) {
            token = data.access_token;
            localStorage.setItem('evr_token', token);
            showToast('Kayit basarili!');
            setTimeout(() => showDashboard(), 600);
        } else {
            showToast('Kayit basarili, lutfen giris yapin.');
            $('[data-tab="login"]').click();
        }
    } catch (err) {
        console.error('Register error:', err);
        authError.textContent = err.message;
        authError.classList.remove('hidden');
    } finally {
        span.textContent = 'Kayit Ol';
        btn.disabled = false;
    }
});


// ─── Logout ─────────────────────────────────────────────────

$('#btn-logout').addEventListener('click', () => {
    token = null;
    localStorage.removeItem('evr_token');
    showAuth();
});


// ═══════════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════════

async function loadDashboard() {
    if (!token) return showAuth();
    let hasRealBotState = false;
    try {
        const data = await api('/dashboard');
        currentUser = data;
        hasRealBotState = Boolean(data && data.bot_state);
        renderDashboard(data);
    } catch (err) {
        console.error('Dashboard load error:', err);
        if (err.message.includes('401') || err.message.includes('token') || err.message.includes('Unauthorized')) {
            token = null;
            localStorage.removeItem('evr_token');
            showAuth();
        } else {
            showToast('Veri yuklenemedi: ' + err.message, 'error');
        }
    }

    // Canli durumu SQL'den yukle (public endpoint, her zaman calisir)
    try {
        const live = await api('/api/live-status');
        renderLiveStatus(live, { preserveBotState: hasRealBotState });
    } catch (err) {
        console.error('Live status error:', err);
    }
}

function renderLiveStatus(data, options = {}) {
    const preserveBotState = Boolean(options.preserveBotState);

    // Simülasyon disclaimer — live-status verisi simülasyondur
    const disclaimerEl = $('#simulation-disclaimer');
    if (disclaimerEl && data.source === 'simulation' && !preserveBotState) {
        disclaimerEl.classList.remove('hidden');
    }

    // EVR karti
    if (data.action === 'SKIP') {
        $('#stat-evr').textContent = 'N/A';
        $('#stat-evr').style.color = '#888';
        $('#stat-evr-label').textContent = data.action_label;
        $('#evr-bar').style.width = `0%`;
        $('#evr-bar').style.background = `#333`;
    } else {
        const evr = data.evr_index;
        $('#stat-evr').textContent = evr.toFixed(1);
        $('#stat-evr').style.color = evrColor(evr);
        $('#stat-evr-label').textContent = evrLabel(evr);
        $('#evr-bar').style.width = `${(evr / 10) * 100}%`;
        $('#evr-bar').style.background = `linear-gradient(90deg, ${evrColor(evr)}, ${evrColor(evr)}66)`;
    }

    // BTC karti
    $('#stat-btc').textContent = '$' + formatNum(data.btc_price, 0);

    // MA600 karti
    if (data.ma600) {
        $('#stat-ma600').textContent = '$' + formatNum(data.ma600, 0);
    } else {
        $('#stat-ma600').textContent = 'N/A';
    }

    // Gercek kullanici bot state'i varsa, live-status sadece piyasa kartlarini gunceller.
    // Bot durumu/strateji alanlari simülasyonla ezilmez.
    if (preserveBotState) {
        return;
    }

    // Bot durumu karti
    const stateMap = { NORMAL: '1 - NORMAL', SHIELD: '2 - SHIELD', BLIND: '3 - BLIND' };
    const stateLabels = { NORMAL: 'EVR Kurallari Aktif', SHIELD: 'Nakit Modunda', BLIND: 'Dipten Mal Toplama' };
    const sn = data.state;
    $('#stat-state').textContent = stateMap[sn] || sn;
    $('#stat-state-label').textContent = stateLabels[sn] || '';

    // State machine visual — aktif durumu vurgula
    $$('.state-node').forEach(n => n.classList.remove('active-state'));
    const nodeId = { NORMAL: 'sn-normal', SHIELD: 'sn-shield', BLIND: 'sn-blind' };
    if (nodeId[sn]) $(`#${nodeId[sn]}`).classList.add('active-state');

    // Info rows
    $('#info-ath').textContent = data.ath > 0 ? '$' + formatNum(data.ath, 0) : '—';
    $('#info-breakdown').textContent = data.breakdown_ref > 0 ? '$' + formatNum(data.breakdown_ref, 0) : '—';
    $('#info-lastrun').textContent = data.date;

    // Strategy explainer
    if (data.action === 'SKIP') {
        // #explainer-text opsiyonel; yoksa why-badge/why-text fallback
        const ex = $('#explainer-text');
        if (ex) {
            // textContent kullan — XSS guvenligi, escapeHtml gerektirmez
            ex.textContent = `${data.action_label}: ${data.action_text}`;
            ex.className = 'explainer-box warn';
        } else {
            // Fallback: strategy panel guncelle
            const badge = $('#why-badge');
            const text  = $('#why-text');
            if (badge) { badge.textContent = data.action_label; badge.className = 'why-badge warn'; }
            if (text)  { text.textContent  = data.action_text; }
        }
    } else {
        updateStrategyExplainer(data.evr_index, data.btc_price, data.ma600, sn);
    }
}

function renderDashboard(data) {
    const { user, bot_state, recent_trades } = data;
    const isLifetime = Boolean(user.is_lifetime_member);

    // Nav
    $('#nav-email').textContent = user.email;
    const badge = $('#nav-sub-badge');
    if (isLifetime) {
        badge.textContent = 'Omur Boyu';
        badge.className = 'sub-badge lifetime';
    } else if (user.subscription_status === 'active') {
        badge.textContent = 'Aktif';
        badge.className = 'sub-badge active';
    } else {
        badge.textContent = 'Inaktif';
        badge.className = 'sub-badge inactive';
    }

    // Subscription panel
    const subText = $('#sub-status-text');
    const subBtn = $('#btn-sub-toggle');
    if (isLifetime) {
        subText.textContent = 'Omur Boyu Erisim';
        subText.style.color = 'var(--accent-indigo)';
        subBtn.textContent = 'Kilidi Acik';
        subBtn.className = 'btn btn-sm btn-ghost';
        subBtn.disabled = true;
    } else if (user.subscription_status === 'active') {
        subText.textContent = 'Aktif';
        subText.style.color = 'var(--accent-green)';
        subBtn.textContent = 'Iptal Et';
        subBtn.className = 'btn btn-sm btn-danger';
        subBtn.disabled = false;
    } else {
        subText.textContent = 'Inaktif';
        subText.style.color = 'var(--accent-red)';
        subBtn.textContent = 'Aktif Et';
        subBtn.className = 'btn btn-sm btn-accent';
        subBtn.disabled = false;
    }

    // API keys status
    const apiStatus = $('#api-keys-status');
    if (user.has_api_keys) {
        apiStatus.innerHTML = '<span class="api-dot green"></span><span>Tanimli</span>';
    } else {
        apiStatus.innerHTML = '<span class="api-dot red"></span><span>Tanimlanmadi</span>';
    }

    // Bot state cards
    if (bot_state) {
        const evr = bot_state.last_evr_value || 0;
        $('#stat-evr').textContent = evr.toFixed(1);
        $('#stat-evr').style.color = evrColor(evr);
        $('#stat-evr-label').textContent = evrLabel(evr);
        $('#evr-bar').style.width = `${(evr / 10) * 100}%`;
        $('#evr-bar').style.background = `linear-gradient(90deg, ${evrColor(evr)}, ${evrColor(evr)}66)`;

        $('#stat-btc').textContent = '$' + formatNum(bot_state.last_btc_price, 0);
        $('#stat-ma600').textContent = '$' + formatNum(bot_state.last_ma600, 0);

        const stateMap = { NORMAL: '1 - NORMAL', SHIELD: '2 - SHIELD', BLIND: '3 - BLIND' };
        const stateLabels = { NORMAL: 'EVR Kurallari Aktif', SHIELD: 'Nakit Modunda', BLIND: 'Dipten Mal Toplama' };
        const sn = bot_state.current_state;
        $('#stat-state').textContent = stateMap[sn] || sn;
        $('#stat-state-label').textContent = stateLabels[sn] || '';

        // State machine visual
        $$('.state-node').forEach(n => n.classList.remove('active-state'));
        const nodeId = { NORMAL: 'sn-normal', SHIELD: 'sn-shield', BLIND: 'sn-blind' };
        if (nodeId[sn]) $(`#${nodeId[sn]}`).classList.add('active-state');

        // Info rows
        $('#info-ath').textContent = bot_state.eski_zirve_fiyati > 0 ? '$' + formatNum(bot_state.eski_zirve_fiyati, 0) : '—';
        $('#info-breakdown').textContent = bot_state.breakdown_reference_price > 0 ? '$' + formatNum(bot_state.breakdown_reference_price, 0) : '—';
        $('#info-lastrun').textContent = formatDate(bot_state.last_run_at);

        // Strategy explainer
        updateStrategyExplainer(evr, bot_state.last_btc_price, bot_state.last_ma600, sn);

        // Shield pending uyarisi
        const shieldPendingEl = $('#shield-pending-warning');
        if (shieldPendingEl) {
            if (bot_state.shield_pending) {
                shieldPendingEl.classList.remove('hidden');
            } else {
                shieldPendingEl.classList.add('hidden');
            }
        }

        // Bot state varsa simülasyon disclaimer'i gizle (gerçek veri gösteriliyor)
        const disclaimerEl = $('#simulation-disclaimer');
        if (disclaimerEl) disclaimerEl.classList.add('hidden');
    }

    // Trades table
    renderTrades(recent_trades);
}

function renderTrades(trades) {
    const tbody = $('#trades-body');
    if (trades && trades.length > 0) {
        tbody.innerHTML = trades.map(t => {
            const actionClass = {
                BUY: 'badge-buy', SELL: 'badge-sell',
                SHIELD_SELL: 'badge-shield', STATE_CHANGE: 'badge-state',
            }[t.action] || '';
            return `<tr>
                <td>${formatDate(t.timestamp)}</td>
                <td><span class="badge ${actionClass}">${t.action}</span></td>
                <td>${t.side || '—'}</td>
                <td>${t.amount_btc ? t.amount_btc.toFixed(6) : '—'}</td>
                <td>${t.amount_usdt ? formatNum(t.amount_usdt) : '—'}</td>
                <td>${t.price ? '$' + formatNum(t.price, 0) : '—'}</td>
                <td>${t.evr_value !== null && t.evr_value !== undefined ? t.evr_value.toFixed(1) : '—'}</td>
                <td title="${escapeHtml(t.note || '')}">${t.note ? escapeHtml(t.note.length > 30 ? t.note.substr(0, 30) + '...' : t.note) : '—'}</td>
            </tr>`;
        }).join('');
    } else {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-row">Henuz islem yok</td></tr>';
    }
}

function updateStrategyExplainer(evr, btcPrice, ma600, state) {
    const badge = $('#why-badge');
    const text = $('#why-text');

    if (state === 'SHIELD') {
        badge.textContent = 'SHIELD';
        badge.className = 'why-badge shield';
        text.textContent = `Fiyat ($${formatNum(btcPrice, 0)}) MA_600'un ($${formatNum(ma600, 0)}) altinda. Tum BTC satildi, nakit modunda bekleniyor. Fiyat MA_600 ustune cikarsa Normal'e donulur.`;
        return;
    }
    if (state === 'BLIND') {
        badge.textContent = 'BLIND';
        badge.className = 'why-badge shield';
        text.textContent = `Dip bolgesi tespit edildi. MA_600 devre disi, sadece EVR kurallari gecerli. ATH'ye ulasinca Normal moda donulecek.`;
        return;
    }

    // NORMAL state — show EVR decision
    if (evr <= 3.2) {
        badge.textContent = 'AL';
        badge.className = 'why-badge buy';
        text.textContent = `EVR ${evr.toFixed(1)} — Asiri korku bolgesi (esik: 3.2). Kasanin %2'si ile BTC alinacak. Piyasa korkudayken satin alarak dusuk maliyetli pozisyon olusturuluyor.`;
    } else if (evr >= 8.5) {
        badge.textContent = 'SAT';
        badge.className = 'why-badge sell';
        text.textContent = `EVR ${evr.toFixed(1)} — Asiri acgozluluk bolgesi (esik: 8.5). Eldeki BTC'nin %15'i satilacak. Piyasa coskudayken kar realizasyonu yapiliyor.`;
    } else {
        badge.textContent = 'BEKLE';
        badge.className = 'why-badge';
        text.textContent = `EVR ${evr.toFixed(1)} — Notr bolge (3.2 < EVR < 8.5). Islem sinyal yok. Bot alimlara veya satimlara neden olacak bir asiri duygu seviyesi gormuyor.`;
    }
}


// ═══════════════════════════════════════════════════════════════
// EVR TOTAL MAP — CHART
// ═══════════════════════════════════════════════════════════════

async function loadChartData() {
    const loading = $('#chart-loading');
    loading.classList.remove('hidden');

    try {
        chartData = await api('/api/chart-data');
        loading.classList.add('hidden');
        renderChart(chartData, currentRange);
    } catch (err) {
        console.error('Chart data error:', err);
        loading.innerHTML = '<span style="color: var(--accent-red)">Grafik verisi yuklenemedi</span>';
    }
}

function renderChart(data, rangeDays) {
    const canvas = $('#evr-chart');
    const ctx = canvas.getContext('2d');

    // Slice data based on range
    let { dates, btc_prices, evr_raw, ma_600 } = data;
    if (rangeDays > 0 && dates.length > rangeDays) {
        const start = dates.length - rangeDays;
        dates = dates.slice(start);
        btc_prices = btc_prices.slice(start);
        evr_raw = evr_raw.slice(start);
        ma_600 = ma_600.slice(start);
    }

    // Hide zoom reset button
    const zoomResetBtn = $('#btn-zoom-reset');
    if (zoomResetBtn) zoomResetBtn.classList.add('hidden');

    // Destroy old chart
    if (evrChart) {
        evrChart.destroy();
        evrChart = null;
    }

    // Generate EVR gradient colors for the EVR line
    function evrPointColor(val) {
        if (val === null || val === undefined) return '#555555'; // Gri
        if (val <= 32) return '#15803d'; // Koyu yesil
        if (val >= 85) return '#b91c1c'; // Koyu kirmizi
        return '#ffffff'; // Orta alan (Beyaz)
    }

    const evrColors = evr_raw.map(v => evrPointColor(v));

    // Custom tooltip via external handler
    const tooltipEl = $('#chart-tooltip');
    const tooltipDate = $('#tooltip-date');
    const tooltipBtc = $('#tooltip-btc');
    const tooltipMa = $('#tooltip-ma');
    const tooltipEvr = $('#tooltip-evr');

    evrChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [
                {
                    label: 'BTC Fiyat',
                    data: btc_prices,
                    borderColor: '#e8962e',
                    backgroundColor: 'rgba(232,150,46,0.05)',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointHoverBackgroundColor: '#e8962e',
                    tension: 0.1,
                    fill: true,
                    yAxisID: 'yBTC',
                    order: 2,
                },
                {
                    label: 'MA 600',
                    data: ma_600,
                    borderColor: '#e2e8f0',
                    borderWidth: 1.5,
                    borderDash: [6, 3],
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: '#e2e8f0',
                    tension: 0.3,
                    fill: false,
                    yAxisID: 'yBTC',
                    order: 1,
                    spanGaps: true,
                },
                {
                    label: 'EVR Endeksi',
                    data: evr_raw,
                    borderColor: '#ffffff',
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: evrColors,
                    segment: {
                        borderColor: function(ctx2) {
                            const val = ctx2.p1.parsed.y;
                            return evrPointColor(val);
                        },
                    },
                    tension: 0.05,
                    fill: false,
                    yAxisID: 'yEVR',
                    order: 3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                tooltip: {
                    enabled: false,
                    external: function(context) {
                        const { tooltip } = context;
                        if (tooltip.opacity === 0) {
                            tooltipEl.classList.remove('visible');
                            return;
                        }

                        const idx = tooltip.dataPoints[0].dataIndex;
                        tooltipDate.textContent = dates[idx];
                        tooltipBtc.textContent = '$' + formatNum(btc_prices[idx], 0);
                        tooltipMa.textContent = ma_600[idx] !== null ? '$' + formatNum(ma_600[idx], 0) : '—';
                        if (evr_raw[idx] !== null && evr_raw[idx] !== undefined) {
                            tooltipEvr.textContent = (evr_raw[idx] / 10).toFixed(1) + ' (' + evr_raw[idx] + ')';
                        } else {
                            tooltipEvr.textContent = 'N/A (Veri Yok)';
                        }

                        // Position tooltip
                        const chartArea = evrChart.chartArea;
                        const caretX = tooltip.caretX;

                        if (caretX < chartArea.width / 2) {
                            tooltipEl.style.left = (caretX + 80) + 'px';
                        } else {
                            tooltipEl.style.left = (caretX - 200) + 'px';
                        }
                        tooltipEl.style.top = '70px';
                        tooltipEl.style.transform = 'none';
                        tooltipEl.classList.add('visible');
                    },
                },
                legend: {
                    display: false,
                },
                zoom: {
                    zoom: {
                        drag: {
                            enabled: true,
                            backgroundColor: 'rgba(129,140,248,0.12)',
                            borderColor: 'rgba(129,140,248,0.4)',
                            borderWidth: 1,
                        },
                        mode: 'x',
                        onZoomComplete: function() {
                            const rb = document.getElementById('btn-zoom-reset');
                            if (rb) rb.classList.remove('hidden');
                        },
                    },
                    pan: {
                        enabled: true,
                        mode: 'x',
                    },
                },
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(30,42,66,0.3)',
                        drawTicks: false,
                    },
                    ticks: {
                        color: '#4d5a75',
                        font: { size: 10, family: 'Inter' },
                        maxTicksLimit: 12,
                        maxRotation: 0,
                        callback: function(value, index) {
                            const label = this.getLabelForValue(value);
                            // Show only year-month
                            if (label && label.length >= 7) {
                                return label.substring(0, 7);
                            }
                            return label;
                        },
                    },
                    border: { display: false },
                },
                yBTC: {
                    type: 'linear',
                    position: 'left',
                    grid: {
                        color: 'rgba(30,42,66,0.25)',
                        drawTicks: false,
                    },
                    ticks: {
                        color: '#e8962e',
                        font: { size: 10, family: 'Inter' },
                        callback: function(value) {
                            if (value >= 1000) return '$' + (value / 1000).toFixed(0) + 'K';
                            return '$' + value;
                        },
                    },
                    border: { display: false },
                },
                yEVR: {
                    type: 'linear',
                    position: 'right',
                    min: 0,
                    max: 100,
                    grid: { display: false },
                    ticks: {
                        color: '#2dd4bf',
                        font: { size: 10, family: 'Inter' },
                        stepSize: 20,
                        callback: function(value) {
                            const labels = { 0: 'Korku', 20: '', 40: '', 50: 'Notr', 60: '', 80: '', 100: 'Acgoz' };
                            return labels[value] !== undefined ? labels[value] : '';
                        },
                    },
                    border: { display: false },
                },
            },
        },
    });

    // Hide tooltip when mouse leaves
    canvas.addEventListener('mouseleave', () => {
        tooltipEl.classList.remove('visible');
    });
}


// ─── Chart Range Buttons ────────────────────────────────────

$$('.chart-range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        $$('.chart-range-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentRange = parseInt(btn.dataset.range, 10);
        if (chartData) {
            renderChart(chartData, currentRange);
        }
    });
});


// ─── Zoom Reset Button ─────────────────────────────────────

const btnZoomReset = $('#btn-zoom-reset');
if (btnZoomReset) {
    btnZoomReset.addEventListener('click', () => {
        if (evrChart) {
            evrChart.resetZoom();
            btnZoomReset.classList.add('hidden');
        }
    });
}


// ─── Settings Actions ───────────────────────────────────────

$('#btn-sub-toggle').addEventListener('click', async () => {
    if (currentUser && currentUser.user && currentUser.user.is_lifetime_member) {
        showToast('Bu hesap omur boyu uyelikte.', 'success');
        return;
    }

    try {
        const isActive = currentUser && currentUser.user.subscription_status === 'active';
        const endpoint = isActive ? '/subscription/deactivate' : '/subscription/activate';
        const data = await api(endpoint, 'POST');
        showToast(data.message);
        loadDashboard();
    } catch (err) {
        showToast(err.message, 'error');
    }
});

$('#btn-save-keys').addEventListener('click', async () => {
    const apiKey = $('#input-api-key').value.trim();
    const apiSecret = $('#input-api-secret').value.trim();

    if (!apiKey || !apiSecret) {
        showToast('API Key ve Secret giriniz.', 'error');
        return;
    }

    try {
        const data = await api('/api-keys', 'POST', {
            api_key: apiKey,
            api_secret: apiSecret,
        });
        showToast(data.message);
        $('#input-api-key').value = '';
        $('#input-api-secret').value = '';
        portfolioLoaded = false;
        loadDashboard();
    } catch (err) {
        showToast(err.message, 'error');
    }
});

$('#btn-delete-keys').addEventListener('click', async () => {
    if (!confirm('API anahtarlarini silmek istediginizden emin misiniz?')) return;
    try {
        const data = await api('/api-keys', 'DELETE');
        showToast(data.message);
        portfolioLoaded = false;
        loadDashboard();
    } catch (err) {
        showToast(err.message, 'error');
    }
});


// ═══════════════════════════════════════════════════════════════
// BACKTEST SIMULATOR
// ═══════════════════════════════════════════════════════════════

let btEquityChart = null;

document.getElementById('btn-run-backtest').addEventListener('click', async () => {
    const btn = document.getElementById('btn-run-backtest');
    const span = btn.querySelector('span');
    const loader = btn.querySelector('.btn-loader');
    const startDate = document.getElementById('bt-start-date').value;
    const endDate = document.getElementById('bt-end-date').value;
    const capital = parseFloat(document.getElementById('bt-capital').value);

    if (!startDate || !endDate) {
        showToast('Baslangic ve bitis tarihi secin.', 'error');
        return;
    }
    if (capital < 100) {
        showToast('Minimum sermaye 100 USDT.', 'error');
        return;
    }

    span.textContent = 'Hesaplaniyor...';
    loader.classList.remove('hidden');
    btn.disabled = true;

    try {
        const data = await api('/api/backtest', 'POST', {
            start_date: startDate,
            end_date: endDate,
            initial_capital: capital,
        });

        document.getElementById('bt-results').classList.remove('hidden');
        renderBacktestSummary(data);
        renderEquityCurve(data);
        renderStateTimeline(data.state_timeline);
        renderBacktestTrades(data.trades);
        renderBacktestWarnings(data.warnings);

        // Smooth scroll to results
        document.getElementById('bt-results').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
        showToast('Backtest hatasi: ' + err.message, 'error');
    } finally {
        span.textContent = '⚡ Simulasyonu Baslat';
        loader.classList.add('hidden');
        btn.disabled = false;
    }
});

function renderBacktestSummary(data) {
    const pnlVal = data.final_capital - data.initial_capital;
    const pnlColor = pnlVal >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';

    const pnlEl = document.getElementById('bt-pnl');
    pnlEl.textContent = '$' + formatNum(data.final_capital, 0);
    pnlEl.style.color = pnlColor;

    const pnlPct = document.getElementById('bt-pnl-pct');
    const sign = data.net_pnl_pct >= 0 ? '+' : '';
    pnlPct.textContent = `${sign}${data.net_pnl_pct.toFixed(2)}% ($${sign}${formatNum(pnlVal, 0)})`;
    pnlPct.style.color = pnlColor;

    // PnL card border glow
    const pnlCard = document.getElementById('bt-card-pnl');
    pnlCard.style.borderColor = pnlVal >= 0 ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)';

    document.getElementById('bt-total-trades').textContent = data.total_trades;
    document.getElementById('bt-buy-sell').textContent = `${data.buy_count} Alis / ${data.sell_count} Satis`;

    document.getElementById('bt-drawdown').textContent = `-${data.max_drawdown_pct.toFixed(2)}%`;
    document.getElementById('bt-drawdown').style.color = 'var(--accent-red)';

    const bh = document.getElementById('bt-buyhold');
    const bhSign = data.buy_and_hold_pct >= 0 ? '+' : '';
    bh.textContent = `${bhSign}${data.buy_and_hold_pct.toFixed(2)}%`;
    bh.style.color = data.buy_and_hold_pct >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
}

function renderEquityCurve(data) {
    const canvas = document.getElementById('bt-equity-chart');
    const ctx = canvas.getContext('2d');

    if (btEquityChart) {
        btEquityChart.destroy();
        btEquityChart = null;
    }

    const dates = data.equity_curve.map(p => p.date);
    const equity = data.equity_curve.map(p => p.equity);

    // Create gradient
    const grad = ctx.createLinearGradient(0, 0, 0, 400);
    const isProfit = data.net_pnl_pct >= 0;
    if (isProfit) {
        grad.addColorStop(0, 'rgba(16,185,129,0.25)');
        grad.addColorStop(1, 'rgba(16,185,129,0.01)');
    } else {
        grad.addColorStop(0, 'rgba(239,68,68,0.25)');
        grad.addColorStop(1, 'rgba(239,68,68,0.01)');
    }

    btEquityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                label: 'Portfoy Degeri',
                data: equity,
                borderColor: isProfit ? '#10b981' : '#ef4444',
                backgroundColor: grad,
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                tension: 0.1,
                fill: true,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    displayColors: false,
                    callbacks: {
                        label: function(ctx) {
                            if (ctx.datasetIndex === 0) {
                                const pt = data.equity_curve[ctx.dataIndex];
                                const isProfitable = pt.equity >= data.initial_capital;
                                const kasaBox = isProfitable ? '🟩' : '🟥';
                                return [
                                    kasaBox + ' Kasa Degeri: $' + formatNum(pt.equity, 2),
                                    '⬜ Total USD: $' + formatNum(pt.usdt, 2),
                                    '⬜ Total BTC: ' + pt.btc.toFixed(6)
                                ];
                            }
                            return '';
                        },
                    },
                },
            },
            scales: {
                x: {
                    grid: { color: 'rgba(30,42,66,0.3)', drawTicks: false },
                    ticks: { color: '#4d5a75', font: { size: 10, family: 'Inter' }, maxTicksLimit: 10, maxRotation: 0,
                        callback: function(value) { const l = this.getLabelForValue(value); return l && l.length >= 7 ? l.substring(0, 7) : l; },
                    },
                    border: { display: false },
                },
                y: {
                    grid: { color: 'rgba(30,42,66,0.25)', drawTicks: false },
                    ticks: { color: '#8692ad', font: { size: 10, family: 'Inter' },
                        callback: function(value) { return '$' + (value >= 1000 ? (value/1000).toFixed(1) + 'K' : value); },
                    },
                    border: { display: false },
                },
            },
        },
    });
}

function renderStateTimeline(timeline) {
    const container = document.getElementById('bt-timeline');
    if (!timeline || timeline.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted)">Durum degisikligi yok.</p>';
        return;
    }

    const stateColors = {
        'NORMAL': { bg: 'rgba(16,185,129,0.1)', border: 'var(--accent-green)', dot: '#10b981', label: 'NORMAL' },
        'SHIELD': { bg: 'rgba(245,158,11,0.1)', border: 'var(--accent-amber)', dot: '#f59e0b', label: 'SHIELD' },
        'BLIND':  { bg: 'rgba(129,140,248,0.1)', border: 'var(--accent-indigo)', dot: '#818cf8', label: 'BLIND' },
    };

    container.innerHTML = timeline.map((item, i) => {
        const sc = stateColors[item.state] || stateColors['NORMAL'];
        return `
            <div class="bt-tl-item" style="border-left: 3px solid ${sc.border}; background: ${sc.bg}">
                <div class="bt-tl-header">
                    <span class="bt-tl-dot" style="background:${sc.dot}"></span>
                    <span class="bt-tl-state">${sc.label}</span>
                    <span class="bt-tl-date">${item.date}</span>
                </div>
                <p class="bt-tl-reason">${escapeHtml(item.reason)}</p>
            </div>
        `;
    }).join('');
}

function renderBacktestTrades(trades) {
    const tbody = document.getElementById('bt-trades-body');
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-row">Bu donemde islem yapilmadi</td></tr>';
        return;
    }

    tbody.innerHTML = trades.map(t => {
        const actionClass = {
            BUY: 'badge-buy', SELL: 'badge-sell',
            SHIELD_SELL: 'badge-shield', STATE_CHANGE: 'badge-state',
        }[t.action] || '';
        const stateClass = {
            NORMAL: 'badge-buy', SHIELD: 'badge-shield', BLIND: 'badge-state',
        }[t.state] || '';
        return `<tr>
            <td>${t.date}</td>
            <td><span class="badge ${actionClass}">${t.action}</span></td>
            <td>${t.side || '—'}</td>
            <td>${t.amount_btc ? t.amount_btc.toFixed(6) : '—'}</td>
            <td>${t.amount_usdt ? formatNum(t.amount_usdt) : '—'}</td>
            <td>$${formatNum(t.price, 0)}</td>
            <td>${t.evr !== null && t.evr !== undefined ? t.evr.toFixed(1) : '—'}</td>
            <td><span class="badge ${stateClass}">${t.state || '—'}</span></td>
            <td title="${t.note || ''}">${t.note ? (t.note.length > 35 ? t.note.substr(0, 35) + '...' : t.note) : '—'}</td>
        </tr>`;
    }).join('');
}

function renderBacktestWarnings(warnings) {
    const panel = document.getElementById('bt-warnings-panel');
    const container = document.getElementById('bt-warnings');
    if (!warnings || warnings.length === 0) {
        panel.classList.add('hidden');
        return;
    }
    panel.classList.remove('hidden');
    container.innerHTML = warnings.map(w => `<div class="bt-warning-item">⚠️ ${w}</div>`).join('');
}


// ═══════════════════════════════════════════════════════════════
// PORTFOLIO
// ═══════════════════════════════════════════════════════════════

let portfolioLoaded = false;
let pfEquityChart = null;

async function loadPortfolio() {
    if (portfolioLoaded) return;
    if (!token) return;

    const loading = document.getElementById('pf-loading');
    const noKeys = document.getElementById('pf-no-keys');
    const errorBox = document.getElementById('pf-error');
    const dataBox = document.getElementById('pf-data');
    const chartEmpty = document.getElementById('pf-chart-empty');
    const chartContainer = document.getElementById('pf-chart-container');

    // Reset states
    loading.classList.remove('hidden');
    noKeys.classList.add('hidden');
    errorBox.classList.add('hidden');
    dataBox.classList.add('hidden');

    try {
        // Parallel API calls
        const [summaryData, historyData] = await Promise.all([
            api('/api/portfolio/summary'),
            api('/api/portfolio/history'),
        ]);

        loading.classList.add('hidden');

        // No API keys
        if (summaryData.has_api_keys === false) {
            noKeys.classList.remove('hidden');
            return;
        }

        // API error
        if (summaryData.error) {
            document.getElementById('pf-error-text').textContent = summaryData.error;
            errorBox.classList.remove('hidden');
            return;
        }

        // Show data
        dataBox.classList.remove('hidden');
        renderPortfolioSummary(summaryData);
        renderPortfolioTrades(summaryData.recent_trades);

        // Chart
        const snapshots = historyData.snapshots || [];
        if (snapshots.length < 2) {
            chartEmpty.classList.remove('hidden');
            chartContainer.classList.add('hidden');
        } else {
            chartEmpty.classList.add('hidden');
            chartContainer.classList.remove('hidden');
            renderPortfolioChart(snapshots);
        }

        portfolioLoaded = true;
    } catch (err) {
        console.error('Portfolio load error:', err);
        loading.classList.add('hidden');
        document.getElementById('pf-error-text').textContent = 'Portföy verisi yüklenemedi: ' + err.message;
        errorBox.classList.remove('hidden');
    }
}

function renderPortfolioSummary(data) {
    // Total equity
    document.getElementById('pf-total-equity').textContent = '$' + formatNum(data.total_equity_usdt, 2);

    // BTC amount
    const btcVal = data.btc_amount || 0;
    document.getElementById('pf-btc-amount').textContent = btcVal.toFixed(6);
    document.getElementById('pf-btc-usd').textContent = '≈ $' + formatNum(btcVal * (data.btc_price || 0), 2);

    // USDT amount
    document.getElementById('pf-usdt-amount').textContent = '$' + formatNum(data.usdt_amount, 2);

    // Allocation
    const btcPct = data.btc_allocation_pct || 0;
    const usdtPct = data.usdt_allocation_pct || 0;
    document.getElementById('pf-btc-pct').textContent = btcPct.toFixed(1) + '%';
    document.getElementById('pf-usdt-pct').textContent = usdtPct.toFixed(1) + '%';
    document.getElementById('pf-alloc-bar-btc').style.width = btcPct + '%';
    document.getElementById('pf-alloc-bar-usdt').style.width = usdtPct + '%';
}

function renderPortfolioChart(snapshots) {
    const canvas = document.getElementById('pf-equity-chart');
    const ctx = canvas.getContext('2d');

    if (pfEquityChart) {
        pfEquityChart.destroy();
        pfEquityChart = null;
    }

    const dates = snapshots.map(s => s.date);
    const equityValues = snapshots.map(s => s.total_equity_usdt);
    const btcAmounts = snapshots.map(s => s.btc_amount);
    const usdtAmounts = snapshots.map(s => s.usdt_amount);
    const btcPrices = snapshots.map(s => s.btc_price);

    // Gradient
    const grad = ctx.createLinearGradient(0, 0, 0, 380);
    grad.addColorStop(0, 'rgba(129,140,248,0.25)');
    grad.addColorStop(1, 'rgba(129,140,248,0.01)');

    // Custom tooltip elements
    const tooltipEl = document.getElementById('pf-chart-tooltip');
    const ttDate = document.getElementById('pf-tooltip-date');
    const ttEquity = document.getElementById('pf-tooltip-equity');
    const ttBtc = document.getElementById('pf-tooltip-btc');
    const ttUsdt = document.getElementById('pf-tooltip-usdt');
    const ttPrice = document.getElementById('pf-tooltip-price');

    pfEquityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                label: 'Portföy Değeri',
                data: equityValues,
                borderColor: '#818cf8',
                backgroundColor: grad,
                borderWidth: 2,
                pointRadius: snapshots.length > 60 ? 0 : 3,
                pointHoverRadius: 5,
                pointBackgroundColor: '#818cf8',
                pointHoverBackgroundColor: '#a78bfa',
                tension: 0.2,
                fill: true,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: false,
                    external: function(context) {
                        const { tooltip } = context;
                        if (tooltip.opacity === 0) {
                            tooltipEl.classList.remove('visible');
                            return;
                        }
                        const idx = tooltip.dataPoints[0].dataIndex;
                        ttDate.textContent = dates[idx];
                        ttEquity.textContent = '$' + formatNum(equityValues[idx], 2);
                        ttBtc.textContent = btcAmounts[idx].toFixed(6) + ' BTC';
                        ttUsdt.textContent = '$' + formatNum(usdtAmounts[idx], 2);
                        ttPrice.textContent = '$' + formatNum(btcPrices[idx], 0);

                        const chartArea = pfEquityChart.chartArea;
                        const caretX = tooltip.caretX;
                        if (caretX < chartArea.width / 2) {
                            tooltipEl.style.left = (caretX + 80) + 'px';
                        } else {
                            tooltipEl.style.left = (caretX - 220) + 'px';
                        }
                        tooltipEl.style.top = '70px';
                        tooltipEl.style.transform = 'none';
                        tooltipEl.classList.add('visible');
                    },
                },
            },
            scales: {
                x: {
                    grid: { color: 'rgba(30,42,66,0.3)', drawTicks: false },
                    ticks: {
                        color: '#4d5a75',
                        font: { size: 10, family: 'Inter' },
                        maxTicksLimit: 12,
                        maxRotation: 0,
                        callback: function(value) {
                            const l = this.getLabelForValue(value);
                            return l && l.length >= 7 ? l.substring(0, 7) : l;
                        },
                    },
                    border: { display: false },
                },
                y: {
                    grid: { color: 'rgba(30,42,66,0.25)', drawTicks: false },
                    ticks: {
                        color: '#8692ad',
                        font: { size: 10, family: 'Inter' },
                        callback: function(value) {
                            return '$' + (value >= 1000 ? (value / 1000).toFixed(1) + 'K' : value);
                        },
                    },
                    border: { display: false },
                },
            },
        },
    });

    // Hide tooltip on mouse leave
    canvas.addEventListener('mouseleave', () => {
        tooltipEl.classList.remove('visible');
    });
}

function renderPortfolioTrades(trades) {
    const tbody = document.getElementById('pf-trades-body');
    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-row">Henüz işlem yok</td></tr>';
        return;
    }

    tbody.innerHTML = trades.map(t => {
        const actionClass = {
            BUY: 'badge-buy', SELL: 'badge-sell',
            SHIELD_SELL: 'badge-shield',
        }[t.action] || '';
        return `<tr>
            <td>${formatDate(t.timestamp)}</td>
            <td><span class="badge ${actionClass}">${t.action}</span></td>
            <td>${t.side || '—'}</td>
            <td>${t.amount_btc ? t.amount_btc.toFixed(6) : '—'}</td>
            <td>${t.amount_usdt ? formatNum(t.amount_usdt) : '—'}</td>
            <td>${t.price ? '$' + formatNum(t.price, 0) : '—'}</td>
            <td title="${escapeHtml(t.note || '')}">${t.note ? escapeHtml(t.note.length > 30 ? t.note.substr(0, 30) + '...' : t.note) : '—'}</td>
        </tr>`;
    }).join('');
}


// ─── Init ───────────────────────────────────────────────────

(function init() {
    if (token) {
        showDashboard();
    } else {
        showAuth();
    }
})();
