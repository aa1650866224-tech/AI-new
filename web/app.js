/* =========================================================================
 *  AI Daily Digest · app.js
 *  ------------------------------------------------------------------------
 *  Wired-inspired editorial layout. Render layer rewritten;
 *  数据契约（与 src/main.py / processors 严格对齐）保持不变：
 *    item.{id, title, content, url, source, created_at,
 *          chinese_title, chinese_summary, chinese_content,
 *          category, importance, sentiment, heat_score, author, ...}
 *    item.{verdict_tag, verdict_label, verdict_explain, verdict_analogy,
 *          verdict.{category_tag, who_should_care, prerequisites, similar_projects},
 *          stars, forks, stars_today, github_meta}   // GitHub 专属
 *  ========================================================================= */

let currentData = null;
let currentSource = 'all';
let currentFilter = 'all';
let currentImp = 'all';
let currentVerdict = 'true_use';   // GitHub 雷达子 tab
let currentDetailItem = null;

/* 各 source 的 mono kicker（ALL CAPS）+ 中文小标题 + 描述 */
const SOURCE_META = {
    all:          { mono: 'TODAY · DIGEST',     cn: '每日精选', desc: '基于多源数据的热度评分与聚类去重，精选每日 Top 资讯' },
    GitHub:       { mono: 'GITHUB · RADAR',     cn: 'GitHub 雷达', desc: '按"开发者真在用 / 看的多用的少 / 营销味重 / 已停摆"四档分类的今日 GitHub 项目' },
    X:            { mono: 'X · TRENDING',       cn: 'X 热门', desc: '来自 X (Twitter) 的 AI 相关热门推文' },
    Reddit:       { mono: 'REDDIT · TRENDING',  cn: 'Reddit 热帖', desc: 'r/MachineLearning、r/LocalLLaMA 等社区的 AI 热门讨论' },
    ProductHunt:  { mono: 'PRODUCT HUNT · TODAY', cn: 'Product Hunt', desc: 'ProductHunt 上今日热门的 AI 产品与工具' },
    HackerNews:   { mono: 'HACKER NEWS · FRONT', cn: 'Hacker News 热榜', desc: 'HackerNews 上与 AI 相关的高分讨论帖' },
    '量子位':      { mono: 'QBITAI · CHINA',      cn: '量子位', desc: '国内头部 AI 科技媒体，覆盖产业动态与技术前沿' }
};

/* mono kicker 上显示的源缩写（ALL CAPS） */
const SOURCE_MONO = {
    X: 'X',
    HackerNews: 'HACKER NEWS',
    Reddit: 'REDDIT',
    ProductHunt: 'PRODUCT HUNT',
    GitHub: 'GITHUB',
    '量子位': 'QBITAI'
};

/* importance: 去 emoji，改 mono caps + 中文双语 */
const IMP_META = {
    '重磅':     { mono: 'TOP STORY',  cls: 'imp-high' },
    '值得关注': { mono: 'WATCH',      cls: 'imp-mid'  },
    '了解即可': { mono: 'FYI',        cls: 'imp-low'  }
};

/* GitHub verdict: 去 emoji，重写为 mono caps 编辑性标签 */
const VERDICT_META = {
    true_use:  { mono: 'TRUE USE',   cn: '真新方向 / 开发者真在用',     short: '真在用' },
    hype_only: { mono: 'HYPE ONLY',  cn: '看的多用的少 / Hype 大于实用', short: 'Hype' },
    marketing: { mono: 'MARKETING',  cn: '营销味重 / 数据可疑',         short: '营销' },
    abandoned: { mono: 'ABANDONED',  cn: '已停摆 / 90 天未维护',         short: '弃坑' }
};

const IMPORTANCE_ORDER = { '重磅': 0, '值得关注': 1, '了解即可': 2 };

/* ========== Glossary：去 emoji，纯文字标签 ========== */
const GITHUB_GLOSSARY = {
    star: {
        name: 'STAR',
        desc: '用户点一下表示「我注意到了这个项目」',
        analogy: '类比：朋友圈给一家店点赞，不代表真去吃过',
        meaning: '所以星多 ≠ 好用，只能说明被看见'
    },
    fork: {
        name: 'FORK',
        desc: '别人把项目复制一份到自己账号下，准备自己改它',
        analogy: '类比：把别人的菜谱抄回家改成自己的版本',
        meaning: 'fork 数高 = 真有人在用它做事，比 star 更硬的指标'
    },
    issue: {
        name: 'ISSUE',
        desc: '用户报 bug、提建议、问怎么用',
        analogy: '类比：餐厅的顾客留言本',
        meaning: '有人提问 + 作者积极回复 = 项目在认真维护；问题堆着没人回 = 警报'
    },
    commit: {
        name: 'COMMIT',
        desc: '作者每改一次代码就记录一次',
        analogy: '类比：厨师改菜单',
        meaning: '最近还在 commit = 项目还活着；几个月没动 = 可能弃坑'
    },
    release: {
        name: 'RELEASE',
        desc: '作者打包好的「可以用」的版本，比正在开发中的代码可靠',
        analogy: '类比：餐厅正式推出的新菜单 vs 后厨还在试做的实验菜',
        meaning: '没发布过 release 的项目 = 还在 demo 阶段，慎用'
    }
};

function glossaryIcon(term) {
    const g = GITHUB_GLOSSARY[term];
    if (!g) return '';
    const tip = `${g.name}：${g.desc}\n${g.meaning}`;
    return `<span class="glossary-icon" data-glossary="${term}" title="${escapeHtml(tip)}">i</span>`;
}

function renderGlossaryBody() {
    const html = Object.values(GITHUB_GLOSSARY).map(g => `
        <div class="glossary-item">
            <div class="glossary-head">
                <span class="glossary-name">${g.name}</span>
            </div>
            <div class="glossary-desc">${escapeHtml(g.desc)}</div>
            <div class="glossary-analogy">${escapeHtml(g.analogy)}</div>
            <div class="glossary-meaning">${escapeHtml(g.meaning)}</div>
        </div>
    `).join('');
    document.querySelectorAll('.glossary-body').forEach(el => {
        el.innerHTML = html;
    });
}

/* ========== 数据加载 ========== */
async function listAvailableDates() {
    try {
        const resp = await fetch('data/index.json');
        if (!resp.ok) throw new Error('no index');
        return await resp.json();
    } catch (e) {
        const today = new Date().toISOString().split('T')[0];
        const yest = new Date(Date.now() - 864e5).toISOString().split('T')[0];
        return [today, yest];
    }
}

async function loadDate(dateStr) {
    try {
        const resp = await fetch(`data/${dateStr}.json`);
        if (!resp.ok) throw new Error(resp.statusText);
        currentData = await resp.json();
        updateSourceCounts();
        render();
    } catch (e) {
        document.getElementById('overviewText').textContent = '该日期暂无数据。';
        document.getElementById('newsList').innerHTML = '<p class="empty-state">该日期暂无数据</p>';
        document.getElementById('statCount').textContent = '0 STORIES';
        document.getElementById('genTime').textContent = '-';
        updateSourceCounts();
    }
}

function updateSourceCounts() {
    if (!currentData) return;
    const bySource = currentData.by_source || {};
    document.getElementById('count-all').textContent = currentData.count || 0;
    ['X', 'Reddit', 'ProductHunt', 'GitHub', 'HackerNews', '量子位'].forEach(src => {
        const count = (bySource[src] || []).length;
        const el = document.getElementById(`count-${src}`);
        if (el) el.textContent = count;
    });
}

/* ========== 数据切片 ========== */
function getItemsToRender() {
    if (!currentData) return [];
    if (currentSource === 'all') {
        return (currentData.items || []).slice();
    }
    if (currentSource === 'GitHub') {
        const all = currentData.by_source?.GitHub || [];
        const items = all.filter(it =>
            !(it.id || '').startsWith('gh_rel_') && it.verdict_tag === currentVerdict
        );
        return items.slice().sort((a, b) => (b.heat_score || 0) - (a.heat_score || 0));
    }
    const bySource = currentData.by_source || {};
    const items = bySource[currentSource] || [];
    return items.slice().sort((a, b) => {
        const ai = IMPORTANCE_ORDER[a.importance] ?? 99;
        const bi = IMPORTANCE_ORDER[b.importance] ?? 99;
        if (ai !== bi) return ai - bi;
        return (b.heat_score || 0) - (a.heat_score || 0);
    });
}

/* ========== 主渲染 ========== */
function render() {
    if (!currentData) return;

    const items = getItemsToRender();
    const meta = SOURCE_META[currentSource] || SOURCE_META.all;

    document.getElementById('sectionLabel').textContent = meta.mono;
    document.getElementById('sectionLabelCn').textContent = meta.cn;
    document.getElementById('pageDesc').textContent = meta.desc;

    /* TODAY'S BRIEF 仅在 DIGEST 视图显示 */
    const overviewSection = document.getElementById('overviewSection');
    if (currentSource === 'all') {
        overviewSection.style.display = 'block';
        document.getElementById('overviewText').textContent = currentData.overview || '今日尚无速览';
    } else {
        overviewSection.style.display = 'none';
    }

    /* GitHub 雷达：4 档 verdict 判据 + 隐藏分类/重要性筛选 */
    renderPitfallCriteria();
    const filtersRow = document.getElementById('filtersRow');
    if (filtersRow) {
        filtersRow.style.display = (currentSource === 'GitHub') ? 'none' : '';
    }

    document.getElementById('genTime').textContent =
        currentData.generated_at ? currentData.generated_at.slice(0, 16).replace('T', ' ') : '-';

    /* 筛选 */
    let filtered = items;
    if (currentFilter !== 'all') filtered = filtered.filter(i => i.category === currentFilter);
    if (currentImp !== 'all')    filtered = filtered.filter(i => i.importance === currentImp);

    document.getElementById('statCount').textContent =
        `${String(filtered.length).padStart(2, '0')} STORIES`;

    const listEl = document.getElementById('newsList');
    listEl.innerHTML = '';

    if (filtered.length === 0) {
        let emptyMsg;
        if (currentSource === 'GitHub') {
            emptyMsg = '今日没有此类项目';
        } else if (items.length === 0) {
            emptyMsg = '该来源暂无数据。可能是 API 限额用完或当日无匹配内容。';
        } else {
            emptyMsg = '当前筛选条件下无匹配内容。';
        }
        listEl.innerHTML = `<p class="empty-state">${emptyMsg}</p>`;
        return;
    }

    filtered.forEach((item, idx) => {
        listEl.appendChild(renderStoryItem(item, idx));
    });
}

/* ========== 单个 story 渲染 ========== */
function renderStoryItem(item, idx) {
    const isGitHub = item.source === 'GitHub';
    const article = document.createElement('article');
    article.className = 'story-item';

    const numeral = String(idx + 1).padStart(2, '0');

    /* mono kickers：源 · 分类 · 重要性 / verdict */
    const sourceMono = SOURCE_MONO[item.source] || (item.source || '').toUpperCase();
    const kickers = [];
    kickers.push(`<span class="story-kicker">${sourceMono}</span>`);
    if (item.category && !isGitHub) {
        kickers.push(`<span class="story-kicker-sep">·</span>`);
        kickers.push(`<span class="story-kicker cat">${escapeHtml(item.category)}</span>`);
    }
    if (isGitHub) {
        const v = VERDICT_META[item.verdict_tag] || VERDICT_META.true_use;
        kickers.push(`<span class="story-kicker-sep">·</span>`);
        kickers.push(`<span class="story-kicker verdict-${item.verdict_tag || 'true_use'}">${v.mono}</span>`);
    } else if (item.importance && IMP_META[item.importance]) {
        const imp = IMP_META[item.importance];
        kickers.push(`<span class="story-kicker-sep">·</span>`);
        kickers.push(`<span class="story-kicker ${imp.cls}">${imp.mono}</span>`);
    }

    /* 标题：GitHub 用 repo 名（mono 显示） + 域名小注 */
    const repoMatch = isGitHub ? (item.url || '').match(/github\.com\/[^\/]+\/([^\/?#]+)/) : null;
    const titleText = isGitHub && repoMatch ? repoMatch[1] : (item.chinese_title || item.title);
    const headlineCls = isGitHub ? 'story-headline is-mono' : 'story-headline';

    /* 域名小标签 */
    const urlDomain = getDomain(item.url);
    const sourceNativeDomains = {
        HackerNews: 'news.ycombinator.com',
        X: 'x.com',
        Reddit: 'reddit.com',
        GitHub: 'github.com',
        ProductHunt: 'producthunt.com',
        '量子位': 'qbitai.com'
    };
    const nativeDomain = sourceNativeDomains[item.source] || '';
    const showDomain = urlDomain && urlDomain !== nativeDomain && !urlDomain.endsWith('.' + nativeDomain);
    const domainTag = showDomain
        ? `<span class="story-domain">${escapeHtml(urlDomain)}</span>`
        : '';

    /* deck（chinese_summary） */
    const deck = item.chinese_summary || item.summary || item.content || '';

    /* meta：作者 · 热度 · 链接 */
    const heatTxt = item.heat_score ? `HEAT ${Math.round(item.heat_score)}` : '';
    const starsTodayTxt = (isGitHub && item.stars_today)
        ? `+${item.stars_today} STARS TODAY${glossaryIcon('star')}`
        : '';
    const author = item.author ? `BY ${escapeHtml(String(item.author).toUpperCase())}` : '';

    /* HN 讨论页入口 */
    const hnDiscussion = item.discussion_url
        || (item.source === 'HackerNews' && /^\d+$/.test(item.id || '')
            ? `https://news.ycombinator.com/item?id=${item.id}`
            : '');
    const discussionLink = (hnDiscussion && hnDiscussion !== item.url)
        ? `<a class="story-meta-discussion" href="${hnDiscussion}" target="_blank" rel="noopener">HN DISCUSSION →</a>`
        : '';

    article.innerHTML = `
        <div class="story-numeral">${numeral}</div>
        <div class="story-body">
            <div class="story-kickers">${kickers.join('')}</div>
            <h2 class="${headlineCls}" data-clickable="1">${escapeHtml(titleText)}${domainTag}</h2>
            ${deck ? `<p class="story-deck" data-clickable="1">${escapeHtml(deck)}</p>` : ''}
            <div class="story-meta">
                ${author ? `<span>${author}</span>` : ''}
                ${heatTxt ? `<span>${heatTxt}</span>` : ''}
                ${starsTodayTxt ? `<span>${starsTodayTxt}</span>` : ''}
                ${discussionLink}
                <a href="${item.url}" target="_blank" rel="noopener">SOURCE →</a>
            </div>
        </div>
    `;

    /* 点击 headline / deck 进详情页 */
    article.querySelectorAll('[data-clickable="1"]').forEach(el => {
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            showDetailPage(item);
        });
    });

    return article;
}

/* ========== 4 档 verdict 判据卡（既是判据说明，又是 tab） ========== */
const PITFALL_CRITERIA = [
    {
        tag: 'true_use',
        explain: '有人提 bug、有人改代码、有人 fork 自己改',
        analogy: '像本地人天天去的小馆子',
        rule: '未触发其他三档的兜底归类'
    },
    {
        tag: 'hype_only',
        explain: '星很多，但提 issue / fork 的人少',
        analogy: '像网红店打卡照很多，回头客没几个',
        rule: 'stars > 1000 且 stars / forks > 20'
    },
    {
        tag: 'marketing',
        explain: '星数短期暴涨 + 提问题的人少',
        analogy: '像短视频里"3 天瘦 10 斤"那种话术',
        rule: '7 天新增 stars ≥ 3000 且 issues 不到新增 stars 5%；或 README 命中 ≥ 4 营销词'
    },
    {
        tag: 'abandoned',
        explain: '几个月没人维护了',
        analogy: '像招牌还挂着但已经关门的店',
        rule: '仓库最近一次 push 距今 > 90 天'
    }
];

function renderPitfallCriteria() {
    const section = document.getElementById('pitfallCriteria');
    const grid = document.getElementById('pitfallCriteriaGrid');
    if (!section || !grid) return;

    if (currentSource !== 'GitHub') {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';
    const trending = (currentData?.by_source?.GitHub || [])
        .filter(it => !(it.id || '').startsWith('gh_rel_'));

    grid.innerHTML = PITFALL_CRITERIA.map(c => {
        const v = VERDICT_META[c.tag];
        const activeCls = c.tag === currentVerdict ? ' is-current' : '';
        const count = trending.filter(it => it.verdict_tag === c.tag).length;
        return `
        <div class="verdict-criteria-item${activeCls}" data-verdict="${c.tag}">
            <div class="verdict-criteria-label">
                <span class="verdict-criteria-label-tag ${c.tag}">${v.mono}</span>
                <span class="verdict-criteria-count">${String(count).padStart(2, '0')}</span>
            </div>
            <div class="verdict-criteria-cn">${escapeHtml(v.cn)}</div>
            <div class="verdict-criteria-explain">${escapeHtml(c.explain)}</div>
            <div class="verdict-criteria-analogy">${escapeHtml(c.analogy)}</div>
            <div class="verdict-criteria-rule-label">RULE</div>
            <div class="verdict-criteria-rule">${escapeHtml(c.rule)}</div>
        </div>`;
    }).join('');
}

/* ========== 详情页 ========== */
function _doHideDetailPage() {
    document.getElementById('detailView').style.display = 'none';
    document.getElementById('listView').style.display = 'block';
    currentDetailItem = null;
}

function showDetailPage(item) {
    currentDetailItem = item;
    history.pushState({view: 'detail'}, '');

    const listView = document.getElementById('listView');
    const detailView = document.getElementById('detailView');
    const body = document.getElementById('detailBody');
    const isGitHub = item.source === 'GitHub';

    /* mono kickers */
    const sourceMono = SOURCE_MONO[item.source] || (item.source || '').toUpperCase();
    const kickers = [`<span class="detail-kicker">${sourceMono}</span>`];
    if (item.category && !isGitHub) {
        kickers.push(`<span class="detail-kicker cat">${escapeHtml(item.category)}</span>`);
    }
    if (isGitHub) {
        const v = VERDICT_META[item.verdict_tag] || VERDICT_META.true_use;
        kickers.push(`<span class="detail-kicker verdict-${item.verdict_tag || 'true_use'}">${v.mono}</span>`);
    } else if (item.importance && IMP_META[item.importance]) {
        const imp = IMP_META[item.importance];
        kickers.push(`<span class="detail-kicker ${imp.cls}">${imp.mono}</span>`);
    }

    /* 双语内容 */
    const contentIsChinese = isMostlyChinese(item.content || '');
    const rawEn = contentIsChinese ? '' : (item.content || '');
    const rawZh = (item.chinese_content || '') || (contentIsChinese ? (item.content || '') : '');
    const hasEn = rawEn.trim().length > 20;
    const hasZh = rawZh.trim().length > 20;
    const hasBilingual = hasEn && hasZh;
    const defaultLang = hasZh ? 'zh' : 'en';
    const isGitHubRepo = isGitHub && item.verdict;

    let contentSection = '';
    if (!isGitHubRepo && (hasEn || hasZh)) {
        const zhHtml = hasZh ? simpleMarkdownRender(rawZh) : '<p class="empty-text">暂无中文翻译</p>';
        const enHtml = hasEn ? simpleMarkdownRender(rawEn) : '<p class="empty-text">暂无英文原文</p>';
        contentSection = `
        <div class="detail-content-box">
            <div class="detail-content-header">
                <div class="detail-section-label">FULL TEXT · 原文内容</div>
                ${hasBilingual ? `
                <div class="lang-toggle">
                    <button class="lang-btn ${defaultLang === 'zh' ? 'active' : ''}" data-lang="zh">中文</button>
                    <button class="lang-btn ${defaultLang === 'en' ? 'active' : ''}" data-lang="en">EN</button>
                </div>` : ''}
            </div>
            <div class="detail-lang-content" data-lang="zh" style="display: ${defaultLang === 'zh' ? 'block' : 'none'}">${zhHtml}</div>
            <div class="detail-lang-content" data-lang="en" style="display: ${defaultLang === 'en' ? 'block' : 'none'}">${enHtml}</div>
        </div>`;
    }

    const created = item.created_at
        ? new Date(item.created_at).toLocaleString('zh-CN').toUpperCase()
        : '-';

    const heatTxt = item.heat_score ? `HEAT ${Math.round(item.heat_score)}` : '';
    const starsTodayTxt = (isGitHub && item.stars_today)
        ? `+${item.stars_today} STARS TODAY${glossaryIcon('star')}`
        : '';

    const hnDiscussion = item.discussion_url
        || (item.source === 'HackerNews' && /^\d+$/.test(item.id || '')
            ? `https://news.ycombinator.com/item?id=${item.id}`
            : '');
    const discussionLink = (hnDiscussion && hnDiscussion !== item.url)
        ? `<a class="detail-external-link detail-discussion-link" href="${hnDiscussion}" target="_blank" rel="noopener">HN DISCUSSION →</a>`
        : '';

    body.innerHTML = `
        <div class="detail-header">
            <div class="detail-kickers">${kickers.join('')}</div>
            <h1 class="detail-title">${escapeHtml(item.chinese_title || item.title)}</h1>
            ${item.chinese_title && item.chinese_title !== item.title
                ? `<div class="detail-original-title">${escapeHtml(item.title)}</div>` : ''}
        </div>

        <div class="detail-summary-box">
            <div class="detail-section-label">AI · 摘要</div>
            <div class="detail-summary">${escapeHtml(item.chinese_summary || item.summary || '暂无摘要')}</div>
        </div>

        ${isGitHubRepo ? renderVerdictBlock(item) : ''}

        ${contentSection}

        <div class="detail-footer-bar">
            <div class="detail-meta">
                ${item.author ? `<span>BY ${escapeHtml(String(item.author).toUpperCase())}</span>` : ''}
                <span>${created}</span>
                ${heatTxt ? `<span>${heatTxt}</span>` : ''}
                ${starsTodayTxt ? `<span>${starsTodayTxt}</span>` : ''}
                ${item.sentiment ? `<span>SENTIMENT · ${escapeHtml(String(item.sentiment).toUpperCase())}</span>` : ''}
            </div>
            <div class="detail-link-group">
                ${discussionLink}
                <a class="detail-external-link" href="${item.url}" target="_blank" rel="noopener">SOURCE →</a>
            </div>
        </div>

        ${isGitHub ? `
        <details class="glossary-block" open>
            <summary>
                <span class="glossary-summary-mono">GLOSSARY</span>
                <span class="glossary-summary-cn">看不懂这些数字？(GitHub 术语小词典)</span>
            </summary>
            <div class="glossary-body"></div>
        </details>` : ''}
    `;

    if (isGitHub) renderGlossaryBody();

    listView.style.display = 'none';
    detailView.style.display = 'block';
    detailView.scrollTop = 0;
    window.scrollTo(0, 0);
}

function hideDetailPage() {
    if (!currentDetailItem) return;
    if (history.state?.view === 'detail') {
        history.back();
    } else {
        _doHideDetailPage();
    }
}

/* GitHub verdict 详情块 */
function renderVerdictBlock(item) {
    const v = item.verdict;
    if (!v || typeof v !== 'object') return '';
    const tag = item.verdict_tag || 'true_use';
    const meta = VERDICT_META[tag] || VERDICT_META.true_use;
    const explain = item.verdict_explain || '';
    const analogy = item.verdict_analogy || '';

    const sims = Array.isArray(v.similar_projects)
        ? v.similar_projects.map(s => String(s || '').trim()).filter(Boolean)
        : [];
    const simsHtml = sims.length
        ? sims.map(s => `<span class="verdict-sim-tag">${escapeHtml(s)}</span>`).join('')
        : '<span class="verdict-sim-empty">暂无明显成熟竞品</span>';

    const row = (key, valHtml) => `
        <div class="verdict-row">
            <div class="verdict-row-key">${key}</div>
            <div class="verdict-row-val">${valHtml}</div>
        </div>`;

    return `
    <div class="detail-verdict-block verdict-${tag}">
        <div class="verdict-head">
            <span class="verdict-head-tag ${tag}">${meta.mono}</span>
            <span class="verdict-head-cn">${escapeHtml(meta.cn)}</span>
            ${analogy ? `<span class="verdict-head-analogy">${escapeHtml(analogy)}</span>` : ''}
        </div>
        ${explain ? `<div class="verdict-head-explain">${escapeHtml(explain)}</div>` : ''}
        ${row('CATEGORY · 项目类型',  `<span class="verdict-cat-tag">${escapeHtml(v.category_tag || '—')}</span>`)}
        ${row('WHO CARES · 谁该 care', escapeHtml(v.who_should_care || '—'))}
        ${row('PREREQ · 前置条件',     escapeHtml(v.prerequisites || '无特殊要求'))}
        ${row('SIMILAR · 相似项目',    simsHtml)}
    </div>`;
}

/* ========== Markdown 渲染（保持不变，仅样式由 CSS 接管） ========== */
const IMG_RE = /!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g;
const SINGLE_IMG_RE = /^!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)\s*$/;
const HEADING_RE = /^(#{1,6})\s+(.+)$/;
const LIST_LINE_RE = /^\s*[-*]\s+(.+)$/;
const ORDERED_LIST_LINE_RE = /^\s*\d+\.\s+(.+)$/;
const IMG_PLACEHOLDER_TOKEN = '';

function renderImgTag(alt, src) {
    const safeSrc = escapeHtml(src);
    const safeAlt = escapeHtml(alt);
    return `<img class="article-img" src="${safeSrc}" alt="${safeAlt}" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add('img-broken')">`;
}

function renderInline(text) {
    const imgs = [];
    let work = text.replace(IMG_RE, (_, alt, src) => {
        imgs.push(renderImgTag(alt, src));
        return `${IMG_PLACEHOLDER_TOKEN}${imgs.length - 1}${IMG_PLACEHOLDER_TOKEN}`;
    });
    let html = escapeHtml(work);
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    html = html.replace(/(^|[^"'>])((https?:\/\/[^\s<"']+))/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    const tokenRe = new RegExp(`${IMG_PLACEHOLDER_TOKEN}(\\d+)${IMG_PLACEHOLDER_TOKEN}`, 'g');
    html = html.replace(tokenRe, (_, i) => imgs[Number(i)]);
    return html;
}

function isChineseParagraph(text) {
    const sample = text.slice(0, 200);
    const cn = (sample.match(/[一-鿿]/g) || []).length;
    return cn / Math.max(sample.length, 1) > 0.30;
}

function simpleMarkdownRender(text) {
    if (!text) return '';
    const paragraphs = text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);

    if (paragraphs.length > 0 && !paragraphs[0].includes('\n')) {
        const m = paragraphs[0].match(HEADING_RE);
        if (m && m[1].length <= 2) paragraphs.shift();
    }

    const out = [];
    for (const para of paragraphs) {
        const singleImg = para.match(SINGLE_IMG_RE);
        if (singleImg) {
            const alt = singleImg[1];
            const src = singleImg[2];
            const caption = (alt && alt.length <= 120)
                ? `<figcaption>${escapeHtml(alt)}</figcaption>`
                : '';
            out.push(`<figure class="article-figure">${renderImgTag(alt, src)}${caption}</figure>`);
            continue;
        }
        if (!para.includes('\n')) {
            const headingMatch = para.match(HEADING_RE);
            if (headingMatch) {
                const level = Math.min(headingMatch[1].length + 1, 6);
                const titleHtml = renderInline(headingMatch[2].trim());
                out.push(`<h${level} class="article-h${level}">${titleHtml}</h${level}>`);
                continue;
            }
        }
        const lines = para.split('\n');
        const allUnordered = lines.length > 0 && lines.every(l => LIST_LINE_RE.test(l));
        const allOrdered = lines.length > 0 && lines.every(l => ORDERED_LIST_LINE_RE.test(l));
        if (allUnordered) {
            const items = lines.map(l => `<li>${renderInline(l.match(LIST_LINE_RE)[1])}</li>`).join('');
            out.push(`<ul class="article-list">${items}</ul>`);
            continue;
        }
        if (allOrdered) {
            const items = lines.map(l => `<li>${renderInline(l.match(ORDERED_LIST_LINE_RE)[1])}</li>`).join('');
            out.push(`<ol class="article-list">${items}</ol>`);
            continue;
        }
        const html = renderInline(para).replace(/\n/g, '<br>');
        const isChinese = isChineseParagraph(para);
        const startsWithImg = html.startsWith('<img');
        const className = (isChinese && !startsWithImg)
            ? 'article-p article-p-cn'
            : 'article-p article-p-en';
        out.push(`<p class="${className}">${html}</p>`);
    }
    return out.join('');
}

/* ========== 工具函数 ========== */
function isMostlyChinese(text) {
    if (!text) return false;
    const chineseChars = (text.match(/[一-鿿]/g) || []).length;
    return chineseChars / text.length > 0.30;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getDomain(url) {
    if (!url) return '';
    try {
        let host = new URL(url).hostname.toLowerCase();
        if (host.startsWith('www.')) host = host.slice(4);
        return host;
    } catch (e) { return ''; }
}

/* ========== init ========== */
async function init() {
    /* 日期下拉 */
    const dates = await listAvailableDates();
    const select = document.getElementById('dateSelect');
    select.innerHTML = '';
    dates.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d;
        opt.textContent = d;
        select.appendChild(opt);
    });
    select.addEventListener('change', () => loadDate(select.value));
    document.getElementById('refreshBtn').addEventListener('click', () => loadDate(select.value));

    /* 源切换 ribbon tab */
    document.querySelectorAll('.ribbon-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            if (currentDetailItem) {
                history.replaceState({}, '');
                _doHideDetailPage();
            }
            document.querySelectorAll('.ribbon-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSource = btn.dataset.source;
            currentFilter = 'all';
            currentImp = 'all';
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            document.querySelector('.filter-btn[data-filter="all"]').classList.add('active');
            document.querySelectorAll('.imp-btn').forEach(b => b.classList.remove('active'));
            document.querySelector('.imp-btn[data-imp="all"]').classList.add('active');
            window.scrollTo(0, 0);
            render();
        });
    });

    /* 分类筛选 */
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.filter;
            render();
        });
    });

    /* 重要性筛选 */
    document.querySelectorAll('.imp-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.imp-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentImp = btn.dataset.imp;
            render();
        });
    });

    if (dates.length > 0) {
        select.value = dates[0];
        await loadDate(dates[0]);
    }

    renderGlossaryBody();

    /* GitHub verdict 4 档判据卡：点击切换 verdict（事件委托） */
    const grid = document.getElementById('pitfallCriteriaGrid');
    if (grid) {
        grid.addEventListener('click', (e) => {
            const card = e.target.closest('.verdict-criteria-item[data-verdict]');
            if (!card) return;
            currentVerdict = card.dataset.verdict;
            render();
        });
    }

    /* 详情页返回 */
    document.getElementById('detailBack').addEventListener('click', hideDetailPage);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && currentDetailItem) hideDetailPage();
    });
    window.addEventListener('popstate', () => {
        if (currentDetailItem) _doHideDetailPage();
    });

    /* 详情页语言切换（事件委托） */
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.lang-btn');
        if (!btn) return;
        const box = btn.closest('.detail-content-box');
        if (!box) return;
        const lang = btn.dataset.lang;
        box.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        box.querySelectorAll('.detail-lang-content').forEach(c => {
            c.style.display = c.dataset.lang === lang ? 'block' : 'none';
        });
    });
}

init();
