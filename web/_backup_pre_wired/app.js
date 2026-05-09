let currentData = null;
let currentSource = 'all';
let currentFilter = 'all';
let currentImp = 'all';
let currentVerdict = 'true_use';   // F8：GitHub 雷达子 tab 选中状态
let currentDetailItem = null;

const SOURCE_META = {
    all: { title: '📋 每日精选', desc: '基于多源数据的热度评分与聚类去重，精选每日 Top 资讯' },
    X: { title: '🐦 X 热门', desc: '来自 X (Twitter) 的 AI 相关热门推文' },
    Reddit: { title: '🔴 Reddit 热帖', desc: 'r/MachineLearning、r/LocalLLaMA 等社区的 AI 热门讨论' },
    ProductHunt: { title: '🚀 ProductHunt', desc: 'ProductHunt 上今日热门的 AI 产品与工具' },
    GitHub: { title: '🐙 GitHub 雷达', desc: '按"开发者真在用 / 看的多用的少 / 营销味重 / 已停摆"四档分类的今日 GitHub 项目' },
    HackerNews: { title: '🔶 HackerNews 热榜', desc: 'HackerNews 上与 AI 相关的高分讨论帖' },
    '量子位': { title: '🇨🇳 量子位', desc: '国内头部 AI 科技媒体，覆盖产业动态与技术前沿' }
};

/* ===== GitHub 术语小词典（F3） =====
 * 行内 ⓘ 气泡 + 底部折叠区共用此常量。
 * 设计原则：保留英文术语 star / fork / issue / commit / release，
 * 不翻译——让懂的人不别扭，让不懂的人有上手坡道。
 */
const GITHUB_GLOSSARY = {
    star: {
        name: 'Star',
        icon: '⭐',
        desc: '用户点一下表示「我注意到了这个项目」',
        analogy: '类比：朋友圈给一家店点赞，不代表真去吃过',
        meaning: '所以星多 ≠ 好用，只能说明被看见'
    },
    fork: {
        name: 'Fork',
        icon: '🍴',
        desc: '别人把项目复制一份到自己账号下，准备自己改它',
        analogy: '类比：把别人的菜谱抄回家改成自己的版本',
        meaning: 'fork 数高 = 真有人在用它做事，比 star 更硬的指标'
    },
    issue: {
        name: 'Issue',
        icon: '💬',
        desc: '用户报 bug、提建议、问怎么用',
        analogy: '类比：餐厅的顾客留言本',
        meaning: '有人提问 + 作者积极回复 = 项目在认真维护；问题堆着没人回 = 警报'
    },
    commit: {
        name: 'Commit',
        icon: '🔨',
        desc: '作者每改一次代码就记录一次',
        analogy: '类比：厨师改菜单',
        meaning: '最近还在 commit = 项目还活着；几个月没动 = 可能弃坑'
    },
    release: {
        name: 'Release',
        icon: '📦',
        desc: '作者打包好的「可以用」的版本，比正在开发中的代码可靠',
        analogy: '类比：餐厅正式推出的新菜单 vs 后厨还在试做的实验菜',
        meaning: '没发布过 release 的项目 = 还在 demo 阶段，慎用'
    }
};

/* 给数字旁打个 ⓘ：term 必须是 GITHUB_GLOSSARY 的 key。
 * tooltip 用 title 属性（PC 悬停）+ data-glossary 让点击触发气泡（移动端）
 */
function glossaryIcon(term) {
    const g = GITHUB_GLOSSARY[term];
    if (!g) return '';
    const tip = `${g.icon} ${g.name}：${g.desc}\n${g.meaning}`;
    return `<span class="glossary-icon" data-glossary="${term}" title="${escapeHtml(tip)}">ⓘ</span>`;
}

/* 渲染底部折叠区内容 */
function renderGlossaryBody() {
    const html = Object.values(GITHUB_GLOSSARY).map(g => `
        <div class="glossary-item">
            <div class="glossary-head">
                <span class="glossary-emoji">${g.icon}</span>
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
        document.getElementById('newsList').innerHTML = '<p class="empty-state">暂无内容</p>';
        document.getElementById('statCount').textContent = '共 0 条';
        document.getElementById('genTime').textContent = '-';
        updateSourceCounts();
    }
}

function updateSourceCounts() {
    if (!currentData) return;
    const bySource = currentData.by_source || {};

    // 综合
    document.getElementById('count-all').textContent = currentData.count || 0;
    // 各来源
    ['X', 'Reddit', 'ProductHunt', 'GitHub', 'HackerNews', '量子位'].forEach(src => {
        const count = (bySource[src] || []).length;
        const el = document.getElementById(`count-${src}`);
        if (el) el.textContent = count;
    });
}

const IMPORTANCE_ORDER = { '重磅': 0, '值得关注': 1, '了解即可': 2 };

function getItemsToRender() {
    if (!currentData) return [];
    if (currentSource === 'all') {
        // 综合精选保持后端的重要性分层（重磅 → 值得关注 → 了解即可）
        return (currentData.items || []).slice();
    }
    // F8：GitHub 雷达——按 currentVerdict 子 tab 切片（trending 排除 release，按 verdict_tag 过滤）
    if (currentSource === 'GitHub') {
        const all = currentData.by_source?.GitHub || [];
        const items = all.filter(it =>
            !(it.id || '').startsWith('gh_rel_') && it.verdict_tag === currentVerdict
        );
        return items.slice().sort((a, b) => (b.heat_score || 0) - (a.heat_score || 0));
    }
    // 其他来源：按重要性分层（重磅→值得关注→了解即可），同层内按热度降序
    const bySource = currentData.by_source || {};
    const items = bySource[currentSource] || [];
    return items.slice().sort((a, b) => {
        const ai = IMPORTANCE_ORDER[a.importance] ?? 99;
        const bi = IMPORTANCE_ORDER[b.importance] ?? 99;
        if (ai !== bi) return ai - bi;
        return (b.heat_score || 0) - (a.heat_score || 0);
    });
}

function render() {
    if (!currentData) return;

    const items = getItemsToRender();

    // 页面标题
    const meta = SOURCE_META[currentSource] || SOURCE_META.all;
    document.getElementById('pageTitle').textContent = meta.title;
    document.getElementById('pageDesc').textContent = meta.desc;

    // Overview
    const overviewSection = document.getElementById('overviewSection');
    if (currentSource === 'all') {
        overviewSection.style.display = 'block';
        document.getElementById('overviewText').textContent = currentData.overview || '暂无概述';
    } else {
        overviewSection.style.display = 'none';
    }

    // F8：GitHub 雷达——子 tab + 4 档判据卡
    renderPitfallCriteria();

    // GitHub 雷达：隐藏分类/重要性筛选（用 verdict 子 tab 替代）
    const filtersRow = document.getElementById('filtersRow');
    if (filtersRow) {
        filtersRow.style.display = (currentSource === 'GitHub') ? 'none' : '';
    }

    document.getElementById('genTime').textContent = currentData.generated_at ? currentData.generated_at.slice(0, 16).replace('T', ' ') : '-';

    const listEl = document.getElementById('newsList');
    listEl.innerHTML = '';

    // 筛选
    let filtered = items;
    if (currentFilter !== 'all') {
        filtered = filtered.filter(i => i.category === currentFilter);
    }
    if (currentImp !== 'all') {
        filtered = filtered.filter(i => i.importance === currentImp);
    }

    document.getElementById('statCount').textContent = `共 ${filtered.length} 条`;

    if (filtered.length === 0) {
        let emptyMsg;
        if (currentSource === 'GitHub') {
            // F8：子 tab 空状态——保持 tab 可见，仅列表区文案
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
        const card = document.createElement('div');
        const isGitHub = item.source === 'GitHub';
        // 卡片左边框颜色：GitHub 看 verdict_tag，其他源看 importance
        const accentCls = isGitHub
            ? `verdict-${item.verdict_tag || 'true_use'}`
            : `importance-${item.importance || '了解即可'}`;
        card.className = `card ${accentCls}`;
        const itemId = item.id || idx;

        // F5：GitHub 不再显示 importance 标签，改用 verdict_label（4 选 1 大白话标签）
        const impBadge = isGitHub
            ? `<span class="badge verdict-${item.verdict_tag || 'true_use'}">${escapeHtml(item.verdict_label || '🟢 开发者真在用')}</span>`
            : `<span class="badge importance-${item.importance}">${item.importance || '了解即可'}</span>`;
        const catBadge = `<span class="badge">${item.category || '其他'}</span>`;
        const srcBadge = `<span class="badge source-${item.source}">${item.source}</span>`;
        let heat = item.heat_score ? `🔥 ${item.heat_score}` : '';
        // GitHub trending 展示今日新增 star，并在 star 旁挂 ⓘ 词典入口
        if (item.source === 'GitHub' && item.stars_today) {
            heat += (heat ? ' · ' : '') + `⭐ +${item.stars_today} today` + glossaryIcon('star');
        }

        // GitHub 卡片定制：标题用 repo 名，badges 区用 verdict + 热度气泡，底部不再重复热度
        const repoMatch = isGitHub ? (item.url || '').match(/github\.com\/[^\/]+\/([^\/?#]+)/) : null;
        const titleText = isGitHub && repoMatch ? repoMatch[1] : (item.chinese_title || item.title);
        const badgesHtml = isGitHub
            ? `${impBadge}${heat ? ` <span class="badge">${heat}</span>` : ''}`
            : `${srcBadge} ${catBadge} ${impBadge}`;
        const metaLeft = isGitHub
            ? `${escapeHtml(item.author || 'unknown')} &nbsp;|&nbsp; ${item.sentiment || 'neutral'}`
            : `${heat} &nbsp;|&nbsp; ${escapeHtml(item.author || 'unknown')} &nbsp;|&nbsp; ${item.sentiment || 'neutral'}`;

        // 域名小标签（HN 风格）：仅当 url 域名与"自然来源域名"不同 时显示，避免冗余
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
            ? `<span class="card-domain" title="原文链接将跳转到 ${urlDomain}">(${escapeHtml(urlDomain)})</span>`
            : '';

        // HN 讨论页入口：优先用 discussion_url，老数据兜底用 id 拼
        const hnDiscussion = item.discussion_url
            || (item.source === 'HackerNews' && /^\d+$/.test(item.id || '')
                ? `https://news.ycombinator.com/item?id=${item.id}`
                : '');
        const discussionLink = (hnDiscussion && hnDiscussion !== item.url)
            ? `<a class="card-discussion" href="${hnDiscussion}" target="_blank" rel="noopener" title="HN 评论讨论页">💬 HN 讨论 →</a>`
            : '';

        card.innerHTML = `
            <div class="card-header">
                <div class="card-title" data-id="${itemId}">${idx + 1}. ${escapeHtml(titleText)} ${domainTag}</div>
                <div class="card-badges">${badgesHtml}</div>
            </div>
            <div class="card-summary" data-id="${itemId}">${escapeHtml(item.chinese_summary || item.summary || item.content || '')}</div>
            <div class="card-meta">
                <span>${metaLeft}</span>
                <span class="card-links">
                    ${discussionLink}
                    <a href="${item.url}" target="_blank" rel="noopener">查看原文 →</a>
                </span>
            </div>
        `;
        
        // 点击标题或摘要进入详情页
        card.querySelector('.card-title').addEventListener('click', (e) => {
            e.stopPropagation();
            showDetailPage(item);
        });
        card.querySelector('.card-summary').addEventListener('click', (e) => {
            e.stopPropagation();
            showDetailPage(item);
        });

        listEl.appendChild(card);
    });
}

function isMostlyChinese(text) {
    if (!text) return false;
    const chineseChars = (text.match(/[\u4e00-\u9fff]/g) || []).length;
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
    } catch (e) {
        return '';
    }
}

function stripHtml(html) {
    if (!html) return '';
    // 先解码 HTML entities
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    let text = tmp.textContent || tmp.innerText || '';
    // 清理多余空白
    return text.replace(/\s+/g, ' ').trim();
}

function toggleSidebar(show) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (show) {
        sidebar.classList.add('open');
        overlay.classList.add('show');
    } else {
        sidebar.classList.remove('open');
        overlay.classList.remove('show');
    }
}

/* ===== Markdown 渲染（段落 + 标题 + 列表 + 链接 + 图片） ===== */
const IMG_RE = /!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g;
const SINGLE_IMG_RE = /^!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)\s*$/;
const HEADING_RE = /^(#{1,6})\s+(.+)$/;
const LIST_LINE_RE = /^\s*[-*]\s+(.+)$/;
const ORDERED_LIST_LINE_RE = /^\s*\d+\.\s+(.+)$/;
const IMG_PLACEHOLDER_TOKEN = '\u0001';

function renderImgTag(alt, src) {
    const safeSrc = escapeHtml(src);
    const safeAlt = escapeHtml(alt);
    return `<img class="article-img" src="${safeSrc}" alt="${safeAlt}" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add('img-broken')">`;
}

// 段落内"行内 markdown"处理：图片、链接、裸 URL（不处理块级元素）
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

// 通过汉字比例判断是否中文段落（决定首行缩进）
function isChineseParagraph(text) {
    const sample = text.slice(0, 200);
    const cn = (sample.match(/[一-鿿]/g) || []).length;
    return cn / Math.max(sample.length, 1) > 0.30;
}

function simpleMarkdownRender(text) {
    if (!text) return '';
    const paragraphs = text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);

    // 跳过 content 开头的 H1/H2（# 或 ## 主标题）——
    // 这通常就是文章主标题，UI 外层（卡片/详情页头部）已经展示过，避免重复
    if (paragraphs.length > 0 && !paragraphs[0].includes('\n')) {
        const m = paragraphs[0].match(HEADING_RE);
        if (m && m[1].length <= 2) {
            paragraphs.shift();
        }
    }

    const out = [];

    for (const para of paragraphs) {
        // 1. 整段单张图片
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

        // 2. 标题（独占一段的 # / ## / ### …）
        if (!para.includes('\n')) {
            const headingMatch = para.match(HEADING_RE);
            if (headingMatch) {
                const level = Math.min(headingMatch[1].length + 1, 6); // # → h2
                const titleHtml = renderInline(headingMatch[2].trim());
                out.push(`<h${level} class="article-h${level}">${titleHtml}</h${level}>`);
                continue;
            }
        }

        // 3. 列表（每行都是 - / * 或 1. 形式）
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

        // 4. 普通段落：换行转 <br>，整段 inline 渲染
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

/* ===== F4：GitHub 避坑卡片（详情页 + 首页避坑模块共用片段） ===== */

// 详情页：渲染完整的祛魅四段 verdict
function renderVerdictBlock(item) {
    const v = item.verdict;
    if (!v || typeof v !== 'object') return '';
    const tag = item.verdict_tag || 'true_use';
    const label = item.verdict_label || '🟢 开发者真在用';
    const explain = item.verdict_explain || '';
    const analogy = item.verdict_analogy || '';

    const sims = Array.isArray(v.similar_projects)
        ? v.similar_projects.map(s => String(s || '').trim()).filter(Boolean)
        : [];
    const simsHtml = sims.length
        ? sims.map(s => `<span class="verdict-sim-tag">${escapeHtml(s)}</span>`).join('')
        : '<span class="verdict-sim-empty">暂无明显成熟竞品</span>';

    const row = (icon, key, valHtml) => `
        <div class="verdict-row">
            <span class="verdict-row-icon">${icon}</span>
            <div class="verdict-row-body">
                <div class="verdict-row-key">${key}</div>
                <div class="verdict-row-val">${valHtml}</div>
            </div>
        </div>`;

    return `
    <div class="detail-verdict-block verdict-${tag}">
        <div class="verdict-head">
            <span class="verdict-head-label">${escapeHtml(label)}</span>
            <span class="verdict-head-analogy">${escapeHtml(analogy)}</span>
        </div>
        <div class="verdict-head-explain">${escapeHtml(explain)}</div>
        ${row('🏷️', '项目类型', `<span class="verdict-cat-tag">${escapeHtml(v.category_tag || '—')}</span>`)}
        ${row('🎯', '该不该 care', escapeHtml(v.who_should_care || '—'))}
        ${row('⚙️', '前置条件', escapeHtml(v.prerequisites || '无特殊要求'))}
        ${row('🔄', '相似项目', simsHtml)}
    </div>`;
}

// 4 档判定依据（与 src/processors/github_verdict.py 阈值同步，F7 已校准）
const PITFALL_CRITERIA = [
    {
        tag: 'true_use',
        label: '🟢 开发者真在用',
        explain: '有人提 bug、有人改代码、有人 fork 自己改',
        analogy: '像本地人天天去的小馆子',
        rule: '未触发下面任何一档时归入此类（兜底）'
    },
    {
        tag: 'hype_only',
        label: '🟡 看的人多用的人少',
        explain: '星很多，但提 issue / fork 的人少',
        analogy: '像网红店打卡照很多，回头客没几个',
        rule: 'stars > 1000 且 stars / forks > 20'
    },
    {
        tag: 'marketing',
        label: '🔴 营销味重',
        explain: '星数短期暴涨 + 提问题的人少',
        analogy: '像短视频里「3 天瘦 10 斤」那种话术',
        rule: '7 天新增 stars ≥ 3000 且 issues 不到新增 stars 的 5%（每涨 1000 颗 star 提问的人不到 50 个 → 大概率刷的）；或 README 命中 ≥ 4 个营销词。冷启动期用今日新增 stars ≥ 1500 近似。'
    },
    {
        tag: 'abandoned',
        label: '⚫ 已停摆',
        explain: '几个月没人维护了',
        analogy: '像招牌还挂着但已经关门的店',
        rule: '仓库最近一次 push 距今 > 90 天'
    }
];

// 4 卡并列展示判据，本身就是可点击的 verdict 选项卡；选中 verdict 加深色阴影高亮
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
        const activeCls = c.tag === currentVerdict ? ' is-current' : '';
        const count = trending.filter(it => it.verdict_tag === c.tag).length;
        return `
        <div class="pitfall-criteria-item verdict-${c.tag}${activeCls}" data-verdict="${c.tag}">
            <div class="pitfall-criteria-label">
                ${escapeHtml(c.label)}
                <span class="pitfall-criteria-count">${count}</span>
            </div>
            <div class="pitfall-criteria-explain">${escapeHtml(c.explain)}</div>
            <div class="pitfall-criteria-analogy">${escapeHtml(c.analogy)}</div>
            <div class="pitfall-criteria-rule-label">判据</div>
            <div class="pitfall-criteria-rule">${escapeHtml(c.rule)}</div>
        </div>`;
    }).join('');
}

/* ===== 详情页 ===== */
function _doHideDetailPage() {
    const listView = document.getElementById('listView');
    const detailView = document.getElementById('detailView');
    detailView.style.display = 'none';
    listView.style.display = 'block';
    currentDetailItem = null;
}

function showDetailPage(item) {
    currentDetailItem = item;
    // 推入历史记录，支持浏览器后退按钮返回列表
    history.pushState({view: 'detail'}, '');
    
    const listView = document.getElementById('listView');
    const detailView = document.getElementById('detailView');
    const body = document.getElementById('detailBody');

    const isGitHub = item.source === 'GitHub';
    // GitHub 详情页同样用 verdict_label 替代 importance 标签
    const impBadge = isGitHub
        ? `<span class="badge verdict-${item.verdict_tag || 'true_use'}">${escapeHtml(item.verdict_label || '🟢 开发者真在用')}</span>`
        : `<span class="badge importance-${item.importance}">${item.importance || '了解即可'}</span>`;
    const catBadge = `<span class="badge">${item.category || '其他'}</span>`;
    const srcBadge = `<span class="badge source-${item.source}">${item.source}</span>`;
    
    let heat = item.heat_score ? `🔥 ${item.heat_score}` : '';
    if (item.source === 'GitHub' && item.stars_today) {
        heat += (heat ? ' · ' : '') + `⭐ +${item.stars_today} today` + glossaryIcon('star');
    }

    const created = item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '-';
    
    // 内容区：中英双语切换
    const contentIsChinese = isMostlyChinese(item.content || '');
    const rawEn = contentIsChinese ? '' : (item.content || '');
    const rawZh = (item.chinese_content || '') || (contentIsChinese ? (item.content || '') : '');

    const hasEn = rawEn.trim().length > 20;
    const hasZh = rawZh.trim().length > 20;
    const hasBilingual = hasEn && hasZh;
    const defaultLang = hasZh ? 'zh' : 'en';

    // GitHub 仓库：用祛魅四段 verdict 替代"原文内容"——content 只是 description，重复
    const isGitHubRepo = item.source === 'GitHub' && item.verdict;

    let contentSection = '';
    if (!isGitHubRepo && (hasEn || hasZh)) {
        const zhHtml = hasZh ? simpleMarkdownRender(rawZh) : '<p class="empty-text">暂无中文翻译</p>';
        const enHtml = hasEn ? simpleMarkdownRender(rawEn) : '<p class="empty-text">暂无英文原文</p>';
        contentSection = `
        <div class="detail-content-box">
            <div class="detail-content-header">
                <div class="detail-section-label">📄 原文内容</div>
                ${hasBilingual ? `
                <div class="lang-toggle">
                    <button class="lang-btn ${defaultLang === 'zh' ? 'active' : ''}" data-lang="zh">🇨🇳 中文</button>
                    <button class="lang-btn ${defaultLang === 'en' ? 'active' : ''}" data-lang="en">🇺🇸 English</button>
                </div>` : ''}
            </div>
            <div class="detail-lang-content" data-lang="zh" style="display: ${defaultLang === 'zh' ? 'block' : 'none'}">${zhHtml}</div>
            <div class="detail-lang-content" data-lang="en" style="display: ${defaultLang === 'en' ? 'block' : 'none'}">${enHtml}</div>
        </div>
        `;
    }
    
    body.innerHTML = `
        <div class="detail-header">
            <div class="detail-badges">${srcBadge} ${catBadge} ${impBadge}</div>
            <h2 class="detail-title">${escapeHtml(item.chinese_title || item.title)}</h2>
            ${item.chinese_title && item.chinese_title !== item.title ? `<div class="detail-original-title">${escapeHtml(item.title)}</div>` : ''}
        </div>
        
        <div class="detail-summary-box">
            <div class="detail-section-label">💡 AI 摘要</div>
            <div class="detail-summary">${escapeHtml(item.chinese_summary || item.summary || '暂无摘要')}</div>
        </div>

        ${isGitHubRepo ? renderVerdictBlock(item) : ''}

        ${contentSection}
        
        <div class="detail-footer-bar">
            <div class="detail-meta">
                <span>👤 ${escapeHtml(item.author || 'unknown')}</span>
                <span>📅 ${created}</span>
                <span>${heat}</span>
                <span>😊 ${item.sentiment || 'neutral'}</span>
            </div>
            <div class="detail-link-group">
                ${(() => {
                    const d = item.discussion_url
                        || (item.source === 'HackerNews' && /^\d+$/.test(item.id || '')
                            ? `https://news.ycombinator.com/item?id=${item.id}`
                            : '');
                    return (d && d !== item.url)
                        ? `<a class="detail-external-link detail-discussion-link" href="${d}" target="_blank" rel="noopener">💬 HN 讨论 →</a>`
                        : '';
                })()}
                <a class="detail-external-link" href="${item.url}" target="_blank" rel="noopener">查看原始网页 →</a>
            </div>
        </div>

        ${isGitHub ? `
        <details class="glossary-block" open>
            <summary>📖 看不懂这些数字？(GitHub 术语小词典)</summary>
            <div class="glossary-body"></div>
        </details>` : ''}
    `;

    // 详情页里的术语词典折叠区也要填充内容
    if (isGitHub) renderGlossaryBody();

    listView.style.display = 'none';
    detailView.style.display = 'block';
    detailView.scrollTop = 0;
}

function hideDetailPage() {
    if (!currentDetailItem) return;
    // 如果 history state 是 detail，用 back() 同步浏览器历史栈
    if (history.state?.view === 'detail') {
        history.back();
        // popstate 事件会触发 _doHideDetailPage()
    } else {
        _doHideDetailPage();
    }
}

async function init() {
    // 日期选择
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

    // 移动端菜单
    document.getElementById('menuToggle').addEventListener('click', () => toggleSidebar(true));
    document.getElementById('sidebarOverlay').addEventListener('click', () => toggleSidebar(false));

    // 来源选项卡
    document.querySelectorAll('.source-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            // 如果当前在详情页，先退出详情页（清理 history 残留）
            if (currentDetailItem) {
                history.replaceState({}, '');
                _doHideDetailPage();
            }
            
            document.querySelectorAll('.source-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSource = btn.dataset.source;
            // 切换来源时重置筛选
            currentFilter = 'all';
            currentImp = 'all';
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            document.querySelector('.filter-btn[data-filter="all"]').classList.add('active');
            document.querySelectorAll('.imp-btn').forEach(b => b.classList.remove('active'));
            document.querySelector('.imp-btn[data-imp="all"]').classList.add('active');
            // 移动端自动关闭侧边栏
            toggleSidebar(false);
            render();
        });
    });

    // 分类筛选
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.filter;
            render();
        });
    });

    // 重要性筛选
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

    // F3：填充首页底部 GitHub 术语词典
    renderGlossaryBody();

    // F8：GitHub 雷达——4 张判据卡当作 verdict 选项卡（事件委托到 grid，避免重渲染后失效）
    const grid = document.getElementById('pitfallCriteriaGrid');
    if (grid) {
        grid.addEventListener('click', (e) => {
            const card = e.target.closest('.pitfall-criteria-item[data-verdict]');
            if (!card) return;
            currentVerdict = card.dataset.verdict;
            render();
        });
    }

    // 详情页返回按钮
    document.getElementById('detailBack').addEventListener('click', hideDetailPage);
    // ESC 返回
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && currentDetailItem) {
            hideDetailPage();
        }
    });
    
    // 浏览器后退/前进按钮：如果当前在详情页，退出到列表
    window.addEventListener('popstate', () => {
        if (currentDetailItem) {
            _doHideDetailPage();
        }
    });
    
    // 详情页语言切换（事件委托）
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
