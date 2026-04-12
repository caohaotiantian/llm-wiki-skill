# LLM Wiki Skill

[English](README.md) | [中文](README-cn.md)

一个 AI 智能体技能（Agent Skill），用于在 [Obsidian](https://obsidian.md) 仓库中构建和维护自主运行、持续积累的知识库。

灵感来自 [Andrej Karpathy 的 LLM Wiki 模式](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)——让 LLM 维护一个持久化的 wiki，知识被预先综合和交叉引用，而非每次都从原始文档中重新检索。

## 功能概述

你提供源文档——Markdown、PDF、Word、PowerPoint、电子表格、HTML、图片等等。智能体将它们综合为使用 `[[wikilinks]]` 互相链接的 wiki 页面，追踪信息来源，并通过定期检查维护一致性。

**三个核心操作：**

| 操作 | 说明 |
|------|------|
| **摄入（Ingest）** | 将源文档处理为综合性的、交叉引用的 wiki 页面 |
| **查询（Query）** | 搜索 wiki 并生成带引用的综合回答 |
| **检查（Lint）** | 健康检查——发现死链、别名不匹配、孤立页面、过时内容、矛盾信息 |

**知识如何持续积累：**

- 每个源文档可以生成多个互相链接的页面，而不仅仅是一个摘要
- 查询结果可以归档为 wiki 页面，成为正式的知识条目
- 新源文档自动与现有页面建立交叉引用
- 清单（manifest）追踪已处理的内容，避免重复处理

## 仓库结构

```
my-wiki/
├── .obsidian/           # Obsidian 将此识别为仓库
├── raw/                 # 不可变的源文档（真实数据来源）
│   ├── extracted/       # Docling 提取的 Markdown 版本（针对二进制格式）
│   └── .manifest.json   # 使用 SHA-256 哈希追踪已摄入的源文档
├── wiki/                # 综合生成的知识页面（分类从内容中自然产生）
├── index.md             # 自动维护的页面目录
├── log.md               # 仅追加的操作历史
└── schema.md            # Wiki 规范和模板
```

## 使用场景

- **企业设计文档** — 摄入架构文档，跨服务追踪决策，源文档变更时自动更新关联引用
- **研究知识库** — 将论文、笔记和会议记录编译为带来源追踪的互链 wiki
- **项目入职** — 从现有文档构建 wiki，让新成员查询综合知识，而不必阅读所有文档
- **个人学习** — 将书籍、文章和课程摄入不断增长的知识图谱

## 特性

- **增量差异化重新摄入** — 源文档变更时，对比旧快照与新版本，精确识别变更内容，仅更新受影响的 wiki 页面。大规模使用时显著节省 token。
- **级联更新** — 变更沿链接图谱传播：更新的事实会波及引用它们的页面
- **变更检测** — 在对话开始时检测新增/修改的源文档，建议重新摄入
- **删除和归档** — 完整的工作流程，用于移除源文档和处理派生页面
- **来源标记** — 使用行内脚注将声明标记为已提取（extracted）、已推断（inferred）或存疑（ambiguous）
- **批量更新保护** — 当修改超过 10 个现有页面时暂停，等待用户确认
- **Obsidian 原生** — 使用 wikilinks、callouts、嵌入、frontmatter、标签和图谱视图
- **扩展指南** — 针对 100+ 源文档 / 500+ 页面的策略（索引拆分、定向检查、日志轮转）
- **会话作用域** — 防止跨对话的无限重复处理循环
- **可选 Docling 集成** — 从 PDF、DOCX、PPTX、XLSX、HTML、图片等格式提取文本
- **周期性扫描** — 检测新增、失败或低质量的提取，自动重试
- **链接验证** — 检测别名不匹配（`[[别名]]` 应为 `[[文件名|别名]]`）和缺失的链接目标。自动修复将别名重写为正确的管道语法，保留显示文本和标题锚点。在摄入后验证和检查时运行。
- **编译真相 + 时间线页面模型** — 每个页面将可重写的综合内容（编译真相）与仅追加的证据记录（时间线）分离，防止长期知识漂移
- **类型化链接** — Frontmatter 中的 `links:` 字段支持语义类型（`references`、`contradicts`、`depends_on`、`supersedes`、`authored_by`、`works_at`、`mentions`），用于图谱查询
- **混合检索** — 可选的 PGlite/Postgres 索引，结合向量搜索 + 关键词搜索，通过倒数排名融合（RRF）合并结果。支持可配置的嵌入提供者（本地、OpenAI 兼容或任何远程 API）
- **图谱分析** — 基于 NetworkX 的图谱操作：邻居查询、最短路径、PageRank 重要性排名、社区检测、孤立页面发现。支持 Cytoscape.js HTML 导出实现交互式可视化
- **属性过滤** — 按 frontmatter 属性查询页面：`--where "type=concept tag=strategy confidence>=0.7"`
- **多查询扩展** — 通过 Anthropic 或 OpenAI 兼容的聊天 API 生成查询的同义改写，提升检索召回率
- **可插拔存储后端** — `StorageBackend` 协议，支持文件优先（默认）和数据库优先两种实现
- **提供者无关的 API** — 嵌入和扩展功能支持任何 OpenAI 兼容或 Anthropic 兼容的端点，通过环境变量配置（`EMBEDDING_BASE_URL`、`EXPANSION_BASE_URL` 等）

## 安装

详细的各平台安装说明请参阅 [INSTALL.md](INSTALL.md)（Claude Code、Codex CLI、Gemini CLI、Cursor、Windsurf 等）。

**快速开始（Claude Code）：**

```bash
# 克隆到全局技能目录
git clone https://github.com/caohaotiantian/llm-wiki-skill.git
cp -r llm-wiki-skill/llm-wiki ~/.claude/skills/llm-wiki

# 或用于项目级别
cp -r llm-wiki-skill/llm-wiki .claude/skills/llm-wiki
```

然后告诉 Claude：*"在 ./my-wiki 中建立一个知识库 wiki，并摄入这些文档"*

## 依赖

**必需：**
- 支持技能的 AI 编程智能体（Claude Code、Codex、Gemini CLI 等）

**推荐：**
- Python 3.10+ — 运行文档提取和扫描脚本所需
- [`docling`](https://github.com/docling-project/docling) — 用于高质量文档提取（PDF、DOCX、PPTX、XLSX、HTML、图片等）。安装：`pip install docling pip-system-certs`。未安装时，智能体仍可使用内置能力直接读取文件。
- Obsidian — 用于图谱视图、搜索和 Dataview 查询。没有它也能正常工作（本质上只是 Markdown 文件），但 Obsidian 能让 wiki 更好用。

**可选（高级功能）：**
- Node.js 18+ — 用于 PGlite 嵌入式 Postgres 索引（混合检索）
- `sentence-transformers` — 用于本地 CPU 嵌入（无需 API 密钥）
- `networkx` — 用于图谱分析（重要性排名、社区检测、路径查找）
- 任何 OpenAI 兼容或 Anthropic 兼容的 API — 用于远程嵌入和多查询扩展。通过 `EMBEDDING_BASE_URL` / `EXPANSION_BASE_URL` 环境变量配置。

## 项目结构

```
llm-wiki-skill/
├── llm-wiki/                # 技能包（安装的就是这个目录）
│   ├── SKILL.md             # 主技能定义
│   ├── references/
│   │   ├── schema.md        # 页面模板和 frontmatter 规范
│   │   └── obsidian.md      # Obsidian 操作参考（URI、CLI、Markdown）
│   └── scripts/
│       ├── extract.py       # 文档提取（可选 Docling 集成）
│       ├── scan.py          # 扫描 raw/ 发现新增、失败或低质量的提取
│       ├── diff_sources.py  # 用于增量重新摄入的结构化差异
│       ├── lint_links.py    # Wikilink 验证器 + 过时/失衡检查 + 反向引用注入
│       ├── score_pages.py   # 页面综合评分
│       ├── chunking.py      # 文本递归分块
│       ├── embeddings.py    # 提供者无关的嵌入接口
│       ├── index.py         # 混合搜索索引（PGlite/Postgres）
│       ├── graph.py         # 图谱分析（NetworkX + Cytoscape 导出）
│       ├── query_filter.py  # 基于属性的页面过滤
│       ├── expansion.py     # 多查询扩展（Anthropic/OpenAI）
│       └── storage.py       # 可插拔存储后端协议
├── INSTALL.md               # 各平台安装说明
├── LICENSE                  # MIT
└── README.md                # 英文说明
```

## 与 Karpathy 原始构想的区别

Karpathy 的[原始 gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 在较高的抽象层面描述了这一模式——它有意保持抽象，将实现细节留给用户和 LLM。本项目是一个面向生产环境的具体实现，增加了原始 gist 和其他社区实现（如 [Astro-Han/karpathy-llm-wiki](https://github.com/Astro-Han/karpathy-llm-wiki)）中未涵盖的多项能力：

| 能力 | Karpathy 的 Gist | 本项目 |
|------|------------------|--------|
| 文档提取（PDF、DOCX、PPTX、图片等） | 用户手动处理（如 Obsidian Web Clipper） | 通过 [Docling](https://github.com/docling-project/docling) 内置支持 |
| 变更检测 | 未涉及 | 周期性扫描 + `.manifest.json` 中的 SHA-256 哈希追踪 |
| 增量重新摄入 | 未涉及 | 章节级结构化差异——仅重新处理变更部分 |
| 源文档到页面的依赖追踪 | 未涉及 | `.manifest.json` 记录每个源文档生成了哪些 wiki 页面 |
| 批量更新保护 | 未涉及 | 当超过 10 个现有页面将被修改时暂停确认 |
| 会话作用域 | 未涉及 | 防止跨对话的无限重复处理循环 |
| 页面类型分类 | 粗略提及 | 五种起始模板（concepts、entities、topics、sources、queries），分类从内容自然产生 |
| 来源标记 | 未涉及 | 行内脚注：`^[extracted]`、`^[inferred]`、`^[ambiguous]` |
| Obsidian 集成 | 仅提供建议 | 完整参考：URI 方案、CLI 命令、仓库配置、插件 |
| 链接验证 | 未涉及 | 检测别名不匹配和缺失页面；使用 `--fix` 自动修复 |
| 混合检索 | 未涉及 | 向量 + 关键词搜索，通过 RRF 融合，基于 PGlite/Postgres |
| 图谱分析 | 未涉及 | PageRank、社区检测、最短路径、交互式可视化 |
| 知识模型 | 扁平页面 | 编译真相 + 时间线分离，支持过时检测 |
| 类型化链接 | 未涉及 | Frontmatter 中的语义链接类型，用于图谱查询 |

原始 gist 还提到了本项目尚未涵盖的功能：多样化的输出格式（Marp 幻灯片、matplotlib 图表）。

## 致谢

- [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — LLM Wiki 概念

## 许可证

MIT
