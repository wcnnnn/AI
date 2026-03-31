# AI Paper Assistant (AI 论文助手)

一个自动化的论文推荐工作流，从 arXiv 和 ModelScope 获取最新论文，基于您的研究兴趣进行智能筛选，生成带有中文摘要和图表的 Obsidian 笔记。

[English](./README_en.md) | 中文

## 功能特性

- 📚 **多源获取**: 自动从 arXiv 和 ModelScope 获取最新论文
- 🔍 **智能筛选**: 基于关键词和相关性评分筛选论文
- 📥 **自动下载**: 下载论文 PDF 并提取图表
- 📝 **中文摘要**: 使用 LLM 生成专业的中文论文精读
- 📓 **Obsidian 集成**: 生成可直接导入 Obsidian 的 Markdown 笔记
- ⏰ **定时任务**: 支持每日自动运行

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/your-repo/ai-paper-assistant.git
cd ai-paper-assistant
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

1. 复制配置模板文件：
```bash
cp config.example.yaml config.yaml
```

2. 编辑 `config.yaml` 文件，填入你的配置：

```yaml
# 研究兴趣关键词
keywords:
  - AI for Science
  - scientific machine learning
  - molecular dynamics
  - protein folding
  - vision-language

# 每天获取的论文数量
arxiv_limit: 5
modelscope_limit: 3

# Obsidian 配置（替换为你的Obsidian仓库路径）
obsidian:
  vault_path: "D:/YourPath/obsidian-vault"

# LLM API (用于生成中文摘要)
llm_api:
  api_key: "YOUR_MINIMAX_API_KEY"
  model: "MiniMax-M2.5"

# Mineru API (用于 PDF 转 Markdown)
mineru:
  enabled: true
  api_key: "YOUR_MINERU_API_KEY"
```

> ⚠️ **注意**: `config.yaml` 包含敏感API密钥，已被 `.gitignore` 排除，请勿提交到公开仓库

### 4. 运行

```bash
# 运行完整工作流
python workflow.py --all

# 或分步骤运行
python workflow.py --fetch-arxiv      # 获取 arXiv 论文
python workflow.py --fetch-modelscope # 获取 ModelScope 论文
python workflow.py --filter           # 筛选论文
python workflow.py --download         # 下载 PDF 和图片
python workflow.py --parse           # 解析 PDF
python workflow.py --notes           # 生成笔记
```

## 配置说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `keywords` | 研究兴趣关键词列表 | - |
| `exclude_keywords` | 排除的关键词 | [] |
| `relevance_threshold` | 相关性阈值 (0-1) | 0.05 |
| `arxiv_limit` | 每天从 arXiv 获取的论文数 | 5 |
| `modelscope_limit` | 每天从 ModelScope 获取的论文数 | 3 |

### 支持的 arXiv 分类

- cs.AI, cs.LG, cs.CV, cs.CL, cs.NE
- q-bio.BM, q-bio.CB, q-bio.QM
- physics.chem-ph

## 输出结构

```
Obsidian Vault/
├── 论文库/
│   ├── 2601.12345.pdf
│   └── ...
├── 论文图片/
│   ├── 2601.12345/
│   │   ├── fig_1.png
│   │   └── ...
│   └── ...
└── Papers/
    ├── 2026/
    │   ├── 02/
    │   │   └── 20260227_paper_title.md
    │   └── ...
    └── ...
```

## 生成的笔记格式

```markdown
---
title: "Paper Title"
authors: "Author1, Author2"
date: 2026-02-27
source: arXiv
arxiv_id: "2601.12345"
---

# Paper Title
**中文标题**: 中文标题

## 基本信息
- **作者**: Author1, Author2
- **来源**: arXiv

## 摘要 (英文)
...

## 📖 论文精读 (中文)

### 🔍 核心问题
...

### 💡 核心创新点
...

### 🔧 方法介绍
...

### 📊 实验结果
...

### ✅ 结论
...

## 📋 阅读进度
- [ ] 待阅读
- [ ] 阅读中
- [ ] 已理解
- [ ] 已笔记
```

## 定时任务 (Windows)

```bash
# 创建每日早上8点运行的任务
schtasks /create /tn "AI Paper Assistant" /tr "python D:\path\to\workflow.py --all" /sc daily /st 08:00
```

## 技术栈

- **Python 3.11+**
- **PDF 处理**: pdfplumber, pypdf
- **API**: arXiv, ModelScope, MiniMax (LLM), Mineru (PDF转Markdown)
- **Obsidian**: Markdown 笔记生成

## 注意事项

1. 首次运行建议先运行 `--fetch-arxiv` 和 `--filter` 确认能正常获取论文
2. PDF 下载和图片提取需要网络连接
3. 解析大型 PDF 可能需要较长时间
4. 确保 Obsidian vault 路径配置正确
5. 请勿将包含 API Key 的 config.yaml 提交到公开仓库

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
