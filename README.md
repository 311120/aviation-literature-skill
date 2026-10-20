# 航空领域文献查找及管理 Skill

> 一个可迁移、零第三方依赖的 AI Agent Skill：面向航空领域研究者，完成**找文献 → 下载全文 → 入库 Zotero → 基于馆藏问答 → 评估缺口 → 规划下一步**的完整闭环。

## 这个 Skill 解决什么问题

做航空领域研究（尤其是本体构建 → 知识图谱 → RAG 增强大模型这条主线）时，文献工作有三个高频痛点：

1. **找到的文献下不下来** —— 大量工具只给标题和摘要，不给全文 PDF。
2. **下下来了但管不住** —— PDF 散在下载文件夹里，和 Zotero 库对不上。
3. **看了但记不住** —— 读过什么、结论是什么、下一步该看什么，全靠脑子记。

本 Skill 把这三件事串成一条自动化的链路，并且**全程只讲真实可核验的文献**，拿不到全文就明说"需机构订阅"，绝不谎称已下载。

## 核心能力

| 能力 | 说明 |
|---|---|
| 文献检索 | 多源检索（OpenAlex / Crossref / Semantic Scholar / arXiv），优先免费开放获取 |
| 全文归档 | 下载真实 PDF 并归档，文件头校验 + 路径穿越防护 |
| Zotero 双向共享 | 自动定位 Zotero 数据目录，通过本地 API 或 RIS 兜底入库 |
| 知识问答 | 基于已入库文献与个人笔记作答，有据可查 |
| 缺口评估 | 对照研究方向评估文献覆盖度，指出缺哪一块 |
| 研究规划 | 按研究主线给出下一步阅读与实验建议 |
| 对话留痕 | 全部检索与问答记录持久化，可跨工具迁移不丢失 |

## 目录结构

```text
aviation-literature/
├── SKILL.md                     # Skill 主定义（触发词、工作流、降级路径）
├── CHANGELOG.md                 # 版本变更记录
├── references/
│   ├── research-roadmap.md      # 研究主线各阶段关键词与技术栈映射
│   └── zotero.md                # 与 Zotero 协作的细节约定
├── scripts/                     # 三个脚本，仅用 Python 标准库
│   ├── search_papers.py         # 检索
│   ├── zotero_save.py           # 入库
│   └── zotero_query.py          # 查询馆藏
├── templates/                   # 文献索引、历史对话模板
└── test/                        # 验证集（含边界与 CLI 测试）
```

## 快速开始

**环境要求**：Python 3（无需 pip 安装任何包）；Zotero 6/7（可选，缺失时自动降级为"只出清单不入库"）。

```bash
# 1. 检索文献
python scripts/search_papers.py --query "knowledge graph aviation ontology" --limit 20

# 2. 批量入库 Zotero
python scripts/zotero_save.py --batch ../文献库/batch.json

# 3. 查询已有馆藏
python scripts/zotero_query.py --list-collections

# 4. 跑测试
python test/run_all.py
```

## 跨机器使用：文档里的路径占位符

本仓库的所有文档**不绑定任何一台具体机器**。看到下列占位符，按自己环境替换即可；脚本运行时是自动探测真实路径的，**不需要改代码**。

| 占位符 | 含义 |
|---|---|
| `%USERPROFILE%` | Windows 用户目录，通常即 `C:\Users\<你的用户名>` |
| `%APPDATA%` | Windows 应用数据目录 |
| `<工作区>` | 你放置本 Skill 的任意目录 |
| `<你的工作目录>` | 你自己存放文献库与对话记录的目录 |
| `<原工作区>` | 仅出现在构建脚本说明里，指作者打包时的目录，可忽略 |
| `<附件KEY>` / `<条目KEY>` | Zotero 内部生成的随机标识，每台机器不同，运行时自动产生 |

> 在 PowerShell / cmd 里可以直接用 `%USERPROFILE%`；在 Git Bash 里对应 `$USERPROFILE` 或 `~`。

## 设计原则

- **零依赖**：三个脚本只用标准库，任何 Python 3 解释器可直接运行，整个目录可拷贝到其他 Agent 工具使用。
- **不静默失败**：每个依赖缺失都有明确的降级路径，见 `SKILL.md` 的降级表。
- **路径不硬编码**：Zotero 数据目录、临时目录均运行时探测，文档中一律使用占位符。
- **诚实优先**：付费墙文献如实说明"需机构订阅"，绝不绕过付费墙，绝不把"读不到"说成"没有"。

## 文档

- [`使用手册-零基础上手.md`](./使用手册-零基础上手.md) —— 零基础安装与使用
- [`SKILL功能说明.md`](./SKILL功能说明.md) —— 完整功能说明
- [`生成指令-aviation-literature.md`](./生成指令-aviation-literature.md) —— 从零生成此 Skill 的指令
- [`skill检查报告-2026-10-12.md`](./skill检查报告-2026-10-12.md) —— 代码层检查报告
- [`功能核查报告-2026-10-08.md`](./功能核查报告-2026-10-08.md) —— 功能层核查报告

## 版本

当前版本 **v1.5.3**，详见 [`CHANGELOG.md`](./aviation-literature/CHANGELOG.md)。

## 作者

小黄的小绿
