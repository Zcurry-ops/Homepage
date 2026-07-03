# Hanfei Zhu — Personal Homepage

个人学术主页，单页静态网站（纯 HTML/CSS/JS，无需构建），含双语切换、深浅色主题，以及自动更新的「前沿论文追踪」板块。

## 目录结构

```
个人网站_Test/
├── index.html                 # 全站页面（内联 CSS/JS）
├── assets/profile.jpg         # 头像
├── data/papers.json           # 「前沿论文追踪」的数据（由脚本自动生成）
├── scripts/update_radar.py    # 抓取 + 可选 AI 总结，生成 data/papers.json
└── .github/workflows/radar.yml# 每周定时自动更新（GitHub Actions）
```

## 本地查看

- 直接双击 `index.html` 即可（论文追踪板块会用页面内置的示例数据兜底）。
- 想看「实时读取 data/papers.json」的效果，用本地服务器打开：
  ```bash
  cd 个人网站_Test && python3 -m http.server 8000
  # 浏览器访问 http://localhost:8000
  ```

## 前沿论文追踪：工作原理

因为 arXiv 的 API 不支持浏览器跨域直接调用，采用「定时抓取 → 生成静态 JSON → 前端读取」的方式：

1. `scripts/update_radar.py` 按我的研究方向关键词从 **arXiv** 拉取最新论文；
2. 若配置了 LLM 密钥，则为每篇论文生成一句话中英文总结（否则用论文摘要截断）；
3. 结果写入 `data/papers.json`，前端加载时读取并渲染，支持按主题筛选。

### 手动更新一次

```bash
python3 scripts/update_radar.py                        # 仅摘要，无需任何密钥
ANTHROPIC_API_KEY=sk-xxx python3 scripts/update_radar.py   # 额外生成 Claude AI 总结
OPENAI_API_KEY=sk-xxx   python3 scripts/update_radar.py   # 或用 GPT 生成总结
```

### 让它每周自动更新（GitHub Pages 场景）

1. 把本目录推到 GitHub 仓库，开启 **Settings → Pages**（部署分支根目录）。
2. （可选，用于 AI 总结）**Settings → Secrets and variables → Actions** 新增
   `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`。
3. `.github/workflows/radar.yml` 已配置为每周一自动运行，也可在 **Actions** 页面手动
   点击 “Run workflow”。它会刷新 `data/papers.json` 并自动提交。

### 调整追踪的方向 / 关键词

编辑 `scripts/update_radar.py` 顶部的 `TOPICS` 列表即可（主题标签 + arXiv 检索表达式）。

## 待补充

- Google Scholar 链接目前为占位（`index.html` 中 hero 区），请替换为真实主页；可按需再加
  GitHub / ORCID / 简历下载。
