# AI Daily Brief

一份面向 AI builders 的中文每日技术简报，关注真正影响开发实践的新模型、Agent/Coding Agent、AI engineering、开源项目、评测与安全动态。

## 在线阅读

GitHub Pages 部署完成后可访问：

<https://mira190.github.io/ai-daily-brief/>

## 内容方法

简报采用以下流程：

1. 以 `Australia/Sydney` 时区的过去 24 小时为主窗口，并保留滚动 7 天热点追踪。
2. 宽扫实验室与作者博客、Hacker News、GitHub、Hugging Face、arXiv、Product Hunt、公开社交讨论和高质量技术博客。
3. 对陌生且快速升温的名词、论文、架构和项目进行二次检索。
4. 回到原始公告、论文、仓库或作者原文反向核查。
5. 按“事件增量”与最近 7 天归档去重，不用没有新进展的旧闻补数。
6. 对技术实质、传播速度、开发者影响和证据成熟度分别判断。

## 站点功能

- 按年份和月份折叠浏览历史简报
- 日期切换与当前简报搜索
- 暗色模式
- 移动端布局
- 打印友好样式
- 单文件静态站点，无后端、无追踪脚本

## 自动发布

每日简报生成并通过结构与隐私检查后，更新根目录的 `index.html`。推送到 `main` 会触发 GitHub Actions，将当前版本部署到 GitHub Pages。

发布遵循 fail-safe 原则：生成、归档或检查失败时不推送；部署失败时保留上一版可用站点。

## 仓库结构

```text
.
├── index.html                  # 完整简报归档与交互界面
├── README.md                   # 项目说明
├── SECURITY.md                 # 安全与隐私政策
├── .nojekyll                   # 禁用 Jekyll 转换
└── .github/workflows/pages.yml # GitHub Pages 部署
```

## 安全与隐私

本仓库只包含公开来源的简报正文和静态界面，不应提交 API key、访问令牌、Library 文件标识、用户账号信息、本地绝对路径、研究缓存或其他 PII。详情见 [SECURITY.md](SECURITY.md)。

## 信息边界

简报是技术信息筛选与分析，不构成投资、法律、医疗或安全授权建议。厂商 benchmark、作者声明、早期论文与独立复现会尽量明确区分。

