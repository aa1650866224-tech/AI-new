// =========================================================================
//  AI-NEWS V3 · 卡片流前端
//  数据源：web/data/<YYYY-MM-DD>.json（最新日期）
//  渲染：4 个 section tab（morning/discussion/github/weekend），点击卡片跳原文
// =========================================================================

const DATA_INDEX = 'data/index.json';
const SECTION_LABELS = {
    morning:    { mono: 'MORNING',    cn: '今早必读 · 厂商一手发布', desc: '厂商 blog + 政策原文 + 中文媒体 · 按热度降序' },
    discussion: { mono: 'DISCUSSION', cn: '圈子在吵 · 社区讨论',     desc: 'HN + Reddit + 个人 blog · 按热度降序' },
    github:     { mono: 'GH RADAR',   cn: 'GitHub 雷达',           desc: '本轮调整中' },
    weekend:    { mono: 'WEEKEND',    cn: '周末再看 · 沉淀型内容',   desc: 'HuggingFace 模型趋势 · 按热度降序' },
};

let state = {
    currentSection: 'morning',
    currentCategory: 'all',
    data: null,   // 当前日期的完整 JSON
};

// ---------- 工具函数 ----------
function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
function escapeAttr(s) { return escapeHtml(s); }

// ---------- 数据加载 ----------
async function loadLatest() {
    const indexResp = await fetch(DATA_INDEX, { cache: 'no-store' });
    if (!indexResp.ok) throw new Error('index.json 加载失败');
    const dates = await indexResp.json();
    if (!Array.isArray(dates) || dates.length === 0) throw new Error('index.json 为空');
    // index.json 已按日期 reverse=True 排序，第一项就是最新
    const latestDate = dates[0];
    const dailyResp = await fetch(`data/${latestDate}.json`, { cache: 'no-store' });
    if (!dailyResp.ok) throw new Error(`${latestDate}.json 加载失败`);
    state.data = await dailyResp.json();
    return state.data;
}

// ---------- 卡片渲染 ----------
function renderCard(item) {
    // X 推文头部：头像 + handle
    const fallbackInitial = ((item.handle || '').replace(/^@/, '') || item.source || '?')[0].toUpperCase();
    const xHead = item.handle ? `
        <div class="v3-head-x">
            <div class="v3-avatar">
                ${item.avatar ? `<img src="${escapeAttr(item.avatar)}" alt="">` : escapeHtml(fallbackInitial)}
            </div>
            <div>
                <span class="v3-source-x">${escapeHtml(item.source)}</span>
                <span class="v3-handle">${escapeHtml(item.handle)}</span>
            </div>
        </div>
    ` : `<span class="v3-source">${escapeHtml(item.source)}</span>`;

    // 媒体网格（数据驱动：任何 item 有 media 字段就渲染）
    let mediaHtml = '';
    if (item.media && item.media.length > 0) {
        const list = item.media.slice(0, 4);
        const cells = list.map(m => {
            const src = m.thumbnail || m.url;
            const cls = m.type === 'video' ? 'v3-media-cell is-video' : 'v3-media-cell';
            return `<div class="${cls}"><img src="${escapeAttr(src)}" alt=""></div>`;
        }).join('');
        mediaHtml = `<div class="v3-media media-${list.length}">${cells}</div>`;
    }

    const tags = (item.tags || [])
        .slice(0, 4)
        .map(t => `<span class="v3-tag">${escapeHtml(t)}</span>`)
        .join('');

    return `
    <article class="v3-card" data-url="${escapeAttr(item.url)}">
        <div class="v3-head">
            ${xHead}
            <span class="v3-score-badge">
                + 精选 <span class="v3-score-num">${item['精选N'] ?? 0}</span>
            </span>
        </div>
        ${item.chinese_title && !item.handle ? `<h2 class="v3-title">${escapeHtml(item.chinese_title)}</h2>` : ''}
        <p class="v3-summary">${escapeHtml(item.chinese_summary || '')}</p>
        ${mediaHtml}
        <div class="v3-tags">${tags}</div>
        <hr class="v3-divider">
        <div class="v3-reason">
            <span class="v3-reason-label">推荐理由：</span>
            <span class="v3-reason-text">${escapeHtml(item.editor_note || '')}</span>
        </div>
    </article>`;
}

function renderEmptyState() {
    return `
    <section class="v3-empty-state">
        <div class="v3-empty-mono">GH RADAR · COMING SOON</div>
        <div class="v3-empty-title">本周榜单待录入</div>
        <p class="v3-empty-desc">GitHub 雷达板块改造中。<br>新版将基于人工精选周榜，下周回来。</p>
    </section>`;
}

// ---------- section 渲染 ----------
function renderSection() {
    const list = document.getElementById('newsList');
    const sectionLabel = document.getElementById('sectionLabel');
    const sectionLabelCn = document.getElementById('sectionLabelCn');
    const sectionCount = document.getElementById('statCount');
    const pageDesc = document.getElementById('pageDesc');

    const meta = SECTION_LABELS[state.currentSection] || SECTION_LABELS.morning;
    sectionLabel.textContent = meta.mono;
    sectionLabelCn.textContent = meta.cn;
    pageDesc.textContent = meta.desc;

    let items = (state.data?.by_section?.[state.currentSection]) || [];

    // category filter
    if (state.currentCategory !== 'all') {
        items = items.filter(it => it.category === state.currentCategory);
    }

    sectionCount.textContent = `${items.length} STORIES`;

    // github 板块本轮强制留空
    if (state.currentSection === 'github' || items.length === 0) {
        list.innerHTML = state.currentSection === 'github'
            ? renderEmptyState()
            : '<p class="page-desc">该板块今日暂无内容（或被 category filter 筛掉）。</p>';
        return;
    }

    list.innerHTML = items.map(renderCard).join('');
}

// ---------- 顶部 tab 计数 ----------
function updateRibbonCounts() {
    const counts = state.data?.by_section || {};
    document.getElementById('count-morning').textContent    = (counts.morning    || []).length;
    document.getElementById('count-discussion').textContent = (counts.discussion || []).length;
    document.getElementById('count-github').textContent     = '—';   // 留空
    document.getElementById('count-weekend').textContent    = (counts.weekend    || []).length;
}

// ---------- 顶部时间显示 ----------
function updateGeneratedTime() {
    const t = state.data?.generated_at;
    if (!t) return;
    const el = document.getElementById('genTime');
    if (el) el.textContent = t.slice(0, 16).replace('T', ' ');
}

// ---------- 事件绑定 ----------
function bindEvents() {
    // section tab 切换
    document.querySelectorAll('.ribbon-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.ribbon-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentSection = btn.dataset.section;
            state.currentCategory = 'all';
            // reset category filter UI
            document.querySelectorAll('.filter-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.filter === 'all');
            });
            renderSection();
        });
    });

    // category filter
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentCategory = btn.dataset.filter;
            renderSection();
        });
    });

    // REFRESH 按钮
    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            await loadLatest();
            updateRibbonCounts();
            updateGeneratedTime();
            renderSection();
        });
    }

    // 卡片点击跳原文（事件代理）
    document.addEventListener('click', e => {
        const card = e.target.closest('.v3-card');
        if (card && card.dataset.url) {
            window.open(card.dataset.url, '_blank', 'noopener');
        }
    });
}

// ---------- 启动 ----------
(async function init() {
    try {
        await loadLatest();
        updateRibbonCounts();
        updateGeneratedTime();
        bindEvents();
        renderSection();
    } catch (e) {
        console.error('启动失败:', e);
        document.getElementById('newsList').innerHTML =
            `<p class="page-desc">加载失败：${escapeHtml(e.message)}</p>`;
    }
})();
