# 🤖 AI 新闻日报助手

每日自动从 X(Twitter)、Hacker News、GitHub 采集热门 AI 资讯，经 DeepSeek AI 深度处理后，生成一份中文日报网页。

## 功能特性

- **多源采集**：X（推文）、Hacker News（技术讨论）、GitHub（Trending 仓库 & Releases）
- **智能筛选**：热度评分算法 + 去重 + 多样性保护，每日精选 Top 15
- **AI 深度处理**：DeepSeek 生成中文标题、摘要、分类、重要性定级
- **Web 看板**：支持按日期切换、分类筛选、重要性筛选、历史回溯
- **零成本部署**：GitHub Actions + GitHub Pages，完全免费

## 项目结构

```
.
├── config/
│   ├── settings.yaml       # API 配置与权重参数
│   └── keywords.yaml       # 监控与屏蔽关键词
├── src/
│   ├── collectors/         # 数据采集器
│   ├── processors/         # 去重、评分、AI 摘要
│   ├── storage/            # JSON 数据存储
│   └── main.py             # 主入口
├── web/                    # 前端看板（GitHub Pages 部署）
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── data/               # 日报 JSON 数据
├── data/daily/             # 本地数据备份
└── .github/workflows/
    └── daily-digest.yml    # 自动定时任务
```

## 快速开始

### 1. 克隆与安装

```bash
cd D:\pythonstudy\project
pip install -r requirements.txt
```

### 2. 配置环境变量

在项目目录创建 `.env` 文件（或直接在系统环境变量中设置）：

```bash
DEEPSEEK_API_KEY=sk-your-deepseek-key
X_BEARER_TOKEN=your-x-bearer-token
GH_PAT=your-github-token  # 可选，提高 API 限流（不要用 GITHUB_TOKEN 前缀）
```

### 3. 本地运行一次

```bash
python src/main.py
```

运行后会在 `data/daily/` 和 `web/data/` 下生成 `YYYY-MM-DD.json` 文件。

### 4. 本地预览网页

用浏览器打开 `web/index.html` 即可查看日报。

> 注意：由于浏览器安全策略，本地直接打开 `file://` 协议可能无法加载 JSON。建议使用 VS Code 的 **Live Server** 插件，或 Python 临时服务：
> ```bash
> cd web && python -m http.server 8080
> # 然后访问 http://localhost:8080
> ```

## GitHub 部署（推荐）

### 步骤 1：创建 GitHub 仓库

将本项目 push 到你的 GitHub 仓库。

### 步骤 2：设置 Secrets

进入仓库 **Settings -> Secrets and variables -> Actions -> New repository secret**，添加：

| Secret 名称 | 说明 |
|------------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `X_BEARER_TOKEN` | X API Bearer Token（在 https://developer.x.com 申请 Free 权限） |
| `GH_PAT` | GitHub Personal Access Token（可选，不要用 `GITHUB_TOKEN` 前缀） |

### 步骤 3：启用 GitHub Pages

进入仓库 **Settings -> Pages**：
- **Source** 选择 "GitHub Actions"

### 步骤 4：运行工作流

进入 **Actions -> Daily AI Digest -> Run workflow**，手动触发一次。

成功后，每日 UTC 01:00（北京时间 09:00）会自动生成并部署最新日报。

### 步骤 5：访问

部署完成后，访问 `https://你的用户名.github.io/仓库名/` 即可查看。

## 数据来源与额度说明

| 来源 | 免费额度 | 说明 |
|------|---------|------|
| X API (v2) | 1500 读取/月 | 每日约 50 条搜索，够用 |
| Hacker News API | 无限制 | 公开 API |
| GitHub API | 60 次/小时（无 token）/ 5000 次/小时（有 token） | 建议配置 token |
| DeepSeek API | 按量计费 | 每日 15 条约 ¥0.05-0.2 |

## 自定义配置

编辑 `config/settings.yaml` 可调整：
- 抓取关键词与数量
- 热度评分权重
- 每日推送条数（默认 15）
- 监控的 GitHub 仓库列表

## 里程碑

- [x] MVP：多源采集 + 评分排序 + AI 摘要 + JSON 存储
- [x] 可用：GitHub Actions 自动部署 + Web 看板
- [ ] 好用：Prompt 持续调优、补充更多数据源、交互式专题抓取

## License

MIT
