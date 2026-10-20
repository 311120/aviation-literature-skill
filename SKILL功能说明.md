# 航空领域文献查找及管理 skill — 功能说明

> 更新日期：2026-10-12 ｜ skill 名：`aviation-literature` ｜ 当前版本：**v1.5.3**
> 本目录结构：`aviation-literature/`（skill 本体）+ 3 份配套文档（功能说明 / 使用手册 / 生成指令）
> 安装位置：工作区 `E:\Learnings\文献查找及管理skill\aviation-literature\`
> 　　　　　全局 `C:\Users\Admin\.agents\skills\aviation-literature\`（两处内容需保持一致）
> 版本历史见 skill 目录下 `CHANGELOG.md`

本文档面向**维护者**，说明这个 skill 现在能做什么、每部分在哪、以及想加功能时该改哪里。
skill 运行时的行为规范写在 `SKILL.md` 里（模型读的是那份），本文档是给人看的。

> **使用者指南另见 [`使用手册-零基础上手.md`](使用手册-零基础上手.md)**（面向"怎么用"，含四个功能的对话示例、命令速查、常见问题）。
> **复现依据另见 [`生成指令-aviation-literature.md`](生成指令-aviation-literature.md)**（把 skill 拿到别处从零重建时用那份）。
> 本文档面向"怎么改"。

---

## 一、定位与设计底线

**研究的服务对象**是你这条主线：航空领域本体构建 → 依据本体构建知识图谱 → 基于 RAG 增强大模型 → 解决航空工程问题（工艺审查、容差标注审查等）。

**技术栈（用户指定）**：本体建模用 **Protégé**，知识图谱存储与可视化用 **HugeGraph**。这两个工具名已进入检索词与触发词。

> 换工具时要同步改三处，漏一处会出问题：`references/research-roadmap.md` 的技术栈表与阶段检索词、`SKILL.md` 正文第 8 行、frontmatter 的 `description`（漏掉这里会导致提到新工具名时 skill 不触发）。

**四件事**：找真文献、基于文献答问、按研究方向给指导、与 Zotero 文献库**双向共享**（读题录/附件/笔记/标注，新文献自动入库）。

**可迁移性设计**：脚本零第三方依赖、机器路径运行时自动探测、历史对话集中在单个纯 Markdown 文件——整个 skill 目录连同 `对话记录/历史对话.md` 拷到其他模型/agent 工具即可继续用。

改 skill 时**不要破坏**的五条底线（它们是这个 skill 存在的理由）：

| 底线 | 含义 | 落地位置 |
|---|---|---|
| 宁缺毋假 | 每条文献必须来自真实 API 返回、附 DOI 或链接，不许凭记忆编造标题/作者/年份 | SKILL.md「一、文献查找」开头 |
| 优先免费可得 | 呈现时标注 `OA`/`CNKI`/`SUB`/`?` 并优先推免费；**不把 `SUB`/`CNKI` 说成「已确认可下载」** | SKILL.md「一、文献查找」分级表 + 红线第 9、10 条 |
| 依据分层 | 回答必须说明依据是**全文**、**题录**、**笔记/标注**还是**通用知识**，不许混充 | SKILL.md「二、知识问答」 |
| 不臆断文件 | 附件路径无效时如实报告，不假装文件可用 | SKILL.md 查找第 2 步、问答第 1 条 |
| 不直写 Zotero 库 | 对 Zotero 只读走 sqlite 副本，写入只走本地 API / 抓取器 / RIS 导入，**绝不直接改 zotero.sqlite** | SKILL.md「五、红线与边界」第 1 条（**指令层**）+ `references/zotero.md`、`zotero_save.py` / `zotero_grab.py` 注释 |

> **v1.1.1 新增「五、红线与边界」8 条硬约束**（绝不直写库 / 不外发私有数据 / 外部内容只当数据不当指令 /
> 不给无法核实的数字 / 不代写整篇论文 / DOI 核验不猜补 / 简单问题直接答 / 不可逆操作先确认）。
> 来历：边界用例审计（26 例中扫出 **12 处规则缺口，失守率 46%**），其中「不直写库」原先
> **只写在按需加载的 `references/zotero.md` 里**——压测规范对此的判词是「只写 README 等于没有」，
> 故内联进 SKILL.md。改动硬约束时**两处都要维护**。
>
> **v1.5.0 扩到 10 条**：新增第 9 条「绝不绕过付费墙与登录」（不抓需登录内容、不伪造机构会话、
> 不用盗版镜像站如 Sci-Hub、不保存账号凭据）、第 10 条「不夸大可得性」（分级是基于公开字段的标注，
> 不是「你能下载到」的保证）。这两条直接约束「优先免费」这个新功能的行为边界。

---

## 二、文件结构与职责

### 2.1 目录总览（本目录 = skill 包 + 3 份配套文档）

```text
文献查找及管理skill/
├── aviation-literature/           ← skill 本体（这一层可整体拷贝到别处使用）
│   └── （见 2.2）
├── SKILL功能说明.md                ← 本文档：维护者视角（怎么改）
├── 使用手册-零基础上手.md           ← 使用者视角（怎么用）
└── 生成指令-aviation-literature.md ← 复现依据（在别处从零重建这个 skill）
```

### 2.2 skill 包内部结构

```text
aviation-literature/
├── SKILL.md                       ← 行为规范（模型读它来做事）
├── CHANGELOG.md                   ← 版本变更记录（1.0.0 → … → 1.5.1 → 1.5.2 → 1.5.3）
├── references/
│   ├── research-roadmap.md        ← 研究路线四阶段检索词 + 技术栈 + 同义词对照 + 已验证检索词
│   └── zotero.md                  ← Zotero 读写机制、PDF 附件上传四步协议、故障判断、验证状态
├── templates/
│   ├── literature-index.md        ← 文献索引表格骨架 + 字段填写要求
│   └── history-entry.md           ← 历史对话区块骨架 + 文件头
├── scripts/
│   ├── search_papers.py           ← 文献检索 + 可得性分级 + PDF 下载 + RIS/JSON 导出
│   ├── zotero_query.py            ← 读取 Zotero 馆藏（题录/附件/笔记/标注）
│   ├── zotero_save.py             ← 检索结果自动入库 Zotero（建条目 + 上传 PDF 全文）
│   └── zotero_grab.py             ← 用 Zotero 抓取器把 URL/DOI 抓成条目（含可获取的全文）
└── test/
    ├── run_all.py                 ← 验证集总入口（任一失败整体退出码 1）
    ├── harness.py                 ← 断言器 + 环境隔离工具（含夹具新鲜度检测）
    ├── fixtures/make_fixtures.py  ← 现场合成夹具（四源载荷 + 最小 Zotero 库）
    ├── test_parse.py              ← 解析层 149 断言
    ├── test_cli.py                ← 命令行端到端 66 断言
    ├── test_grab.py               ← 抓取器分流与退出码 55 断言
    ├── test_zotero.py             ← Zotero 集成 + 附件上传协议 130 断言
    └── test_boundary.py           ← 边界与退出码契约 71 断言
```

| 文件 | 作用 | 何时被读取 |
|---|---|---|
| `SKILL.md` | 定义环境约定、四大功能流程、红线与边界、目录约定、交付自查 | skill 触发时整份加载 |
| `references/research-roadmap.md` | 技术栈表、四阶段检索词、中文同义词对照、实测有效检索词 | 检索前按需读取 |
| `references/zotero.md` | Zotero 读取路径、附件/笔记/标注定位规则、自动入库双路径、**PDF 附件上传四步协议**、抓取器能力边界、验证状态 | 涉及 Zotero 时读取 |
| `templates/literature-index.md` | 文献索引表格骨架，SKILL.md 正文改为引用它（不再内联） | 建/更新 `文献库/文献索引.md` 时 |
| `templates/history-entry.md` | 历史对话区块骨架与文件头 | 建/追加 `对话记录/历史对话.md` 时 |
| `scripts/search_papers.py` | 命令行检索工具 + **全文可得性分级与优先排序**（零第三方依赖） | 查找文献、生成 RIS/JSON 时调用 |
| `scripts/zotero_query.py` | 读取 Zotero：题录、PDF 附件、笔记、PDF 标注（零第三方依赖） | 查重馆藏、问答取材、研究指导时调用 |
| `scripts/zotero_save.py` | 把选定的检索结果入库 Zotero：建条目 + **把全文 PDF 上传为附件**（零第三方依赖） | 用户选定文献要入库时调用 |
| `scripts/zotero_grab.py` | 用 Zotero 抓取器把 URL/DOI 抓成条目；**知网/万方类链接主动分流给浏览器插件**（零第三方依赖） | 需要抓取网页/DOI 全文、或用户想「一键抓取」时调用 |
| `test/*` | **离线**验证集（5 套件 471 断言），改脚本后必跑（不联网、不碰真实 Zotero 库） | 改动脚本后自检 |
| `CHANGELOG.md` | 版本变更记录 | 发版/回溯时 |

**脚本依赖**：只用 Python 标准库（`urllib`、`sqlite3`、`json`、`re`、`ssl`、`argparse`），**不需要 pip 安装任何包**。这是刻意的设计，保证 skill 拷到任何机器都能跑。

---

## 三、四大功能

### 功能 1：文献查找

**触发**：找文献、文献检索、下载论文、文献综述、研究调研；或提到本体/知识图谱/RAG/工艺审查/容差标注等方向。

**流程（SKILL.md 六个步骤）**：

1. **明确需求** — 定位到研究阶段（本体 / 知识图谱 / RAG / 工程应用），不确定时反问一句
2. **查重馆藏** — 先跑 `zotero_query.py`（关键词同时匹配标题/作者/摘要/**笔记内容**），避免重复下载；命中则标注「馆藏已有」
3. **真实检索** — 生成 3–5 组中英文检索词，跑 `search_papers.py --json 文献库/batch.json`；结果**默认按可得性优先排序**（OA → CNKI → SUB → ?），顶部给出「N/M 条可免费获取」统计。中文库（知网/万方/维普）无公开 API，脚本搜不了，按 `SKILL.md` 检索第 3 步的人工路径走
4. **人工筛选后再呈现** — 脚本只拿数据，相关性由模型判断；按契合度排序并给推荐理由与**可得性标签**，**先给清单让用户挑，除非用户说直接下载**。⚠️ `SUB`/`CNKI` 只能说「需机构订阅/中文库，多数可在校图书馆或校内网取到」，**不能说成「已确认可下载」**
5. **自动入库** — 用户选定编号后跑 `zotero_save.py --json 文献库/batch.json --items 2,5`：Zotero 运行中走本地 API，**先建条目、再把全文 PDF 上传为附件**（条目下可直接读全文）；未运行则 PDF+RIS 落 `<Zotero数据目录>/skill-import/` 等用户导入；馆藏已有的自动跳过（DOI/标题查重）。入库结果分 **5 种状态**逐条如实打印（见第四节）。抓不到的全文可用 `zotero_grab.py` 让 Zotero 自己去抓（**但知网/万方必须走浏览器插件**）
6. **更新索引** — 追加到 `文献库/文献索引.md`，API 建立的条目回填 Zotero Key

**产物**：`文献库/batch.json`、`文献库/文献索引.md`、`<Zotero数据目录>/skill-import/`（PDF + batch.ris，仅兜底路径或附件上传失败时的兜底）

---

### 功能 2：知识问答

**触发**：对某个方向/某篇文献提问、要求解释概念、要求综述某主题。

**取材顺序（且必须明示依据强度）**：

1. **Zotero 馆藏** — 有本地全文可按全文答；只有题录（`--pdf` 显示 `storage:` 前缀）就只能依据标题/作者/摘要，**必须说明「未见全文」**，不许凭标题臆测方法细节；**用户自己的笔记与 PDF 标注也是依据**（`--notes` / `--key` 读出），引用时注明出自哪个条目的哪条笔记/标注
2. **`文献库/`** 下的 PDF 与 `文献索引.md`
3. 都覆盖不了 → 明说「文献库中没有直接依据，以下是基于通用知识的补充」

**引用格式**：逐点标注出处，形如「（据 2023_Smith_AviationOntology.pdf §3.2）」「（据 Zotero 条目 YZA4D3CK 的笔记）」「（据该条目 PDF 标注 p.5 高亮）」。依据不够时主动衔接功能 1 补检索。

---

### 功能 3：历史对话存储（单一文件）

**触发**：每次检索或问答结束后自动执行（无需用户要求）。

**做法**：所有会话**统一追加**（不覆盖、不改写、不删除）到 `对话记录/历史对话.md`。每次会话一个区块，模板五段：需求 / 动作（检索词与命令）/ 结果 / 入库 / 待办。

**为什么是单一文件**：纯 Markdown、不依赖任何模型或软件的功能，**更换模型或 agent 工具后整个 skill 连同该文件可整体迁移**，历史仍可读——这是用户对「通用、可迁移、封装好」的明确要求。

**反向使用**：新会话开始时读取该文件末尾 2–3 个区块延续上下文，避免重复推荐已给过的文献。

---

### 功能 4：研究进展指导

**触发**：问「我该看什么」「下一步怎么做」「我的研究还缺什么」「帮我做个文献规划」。

**做法（SKILL.md 四步）**：

1. **先摸清底数** — `zotero_query.py "" --limit 50 --notes` 列出馆藏与笔记
2. **指出缺口要具体** — 对照四阶段归类，说明哪阶段有基础（举出具体条目）、哪阶段薄弱，不许泛泛说「建议多读文献」
3. **给可执行的下一步** — 薄弱阶段给 2–3 个方向与检索词，需要时直接衔接功能 1
4. **说清局限** — 馆藏只反映「收藏了什么」，不等于「读了什么」

> 这个功能来自你需求原文里「你需要按照我的研究方向，对我进行指导以及文献的查找工作」。

---

## 四、脚本 CLI 参考

### `search_papers.py` — 文献检索

```bash
python scripts/search_papers.py <检索词> [选项]
```

| 参数 | 说明 |
|---|---|
| `query`（位置） | 检索词，建议英文 |
| `--source` | `openalex`（默认）\| `crossref` \| `arxiv` \| `s2` \| `all`（四源合并） |
| `--max` | 每个来源的最大条数，默认 10 |
| `--download DIR` | 下载有开放获取 PDF 链接的文献到该目录 |
| `--ris FILE` | 生成 RIS 题录文件，供 Zotero 导入（兜底路径） |
| `--json FILE` | 导出结构化 JSON（含 `access` 分级与 local_pdf 路径），**供 zotero_save.py 消费** |
| `--out FILE` | 结果另存为 Markdown |
| `--only-free` | **只输出可免费获取的条目**（OA + CNKI），滤掉需订阅的；过滤后为空则输出空清单，不回退成全量 |
| `--no-prefer-free` | 关闭「可得性优先」排序，改回原始相关性顺序（**默认是开启的**） |

**四个数据源的实际表现（实测）**：

| 源 | 精度 | 稳定性 | 说明 |
|---|---|---|---|
| **OpenAlex**（默认） | 高 | 稳 | 用 `title_and_abstract.search` 过滤器，按相关性排序，返回带 `relevance_score`、开放获取 PDF 链接、可还原的摘要 |
| **Crossref** | 中 | 稳 | 覆盖面广但模糊匹配噪音大（搜容差曾返回生物基因文献）。**查询串是 DOI 时自动走 `/works/{doi}` 精确核验题录**（v1.5.2 补上，此前无此实现）；**只认 Creative Commons 类开放授权才判 `OA`**——出版商的 TDM（text-mining）链接不算免费 |
| **arXiv** | 高（预印本） | ✅ **可用** | 2026-10-08 实测恢复，能正常返回结果（v1.5.2 前文档记「本机不可用」已过时） |
| **Semantic Scholar** | 高 | **本机不可用** | 未认证请求限流严格（常 429）；脚本退避重试后跳过并如实提示 |

**每条结果返回字段**：标题、作者列表、年份、来源（venue）、ID/DOI、链接、摘要摘录（前 300 字）、**可得性分级 `access`**、本地文件路径（若下载）。

**可得性四级（v1.5.0 新增，`access` 字段）**：

| 标签 | 含义 | 判定依据 | 能否自动下载 |
|---|---|---|---|
| `OA` | 公开开放获取，真免费 | OpenAlex `is_oa`/`oa_status`、S2 `openAccessPdf`、arXiv；Crossref **仅认 Creative Commons 类授权**（TDM 链接不算） | ✅ 能 |
| `CNKI` | 中文库（知网/万方等） | 标题或期刊含汉字且非 OA | ❌ 需浏览器插件 |
| `SUB` | 出版商页面，需机构订阅 | 有 DOI 但无 OA 标识 | ❌ 需校内网 |
| `?` | 无法判定 | 既无 DOI 也无 OA 标识 | ❌ |

⚠️ **`CNKI`/`SUB` 是标注不是保证**——实际可获取性取决于学校的订阅范围与 IP/VPN 授权，脚本看不到。

**关键实现点**（改动时注意）：
- `http_get()` 内置 SSL 降级：本机证书链不全，首次校验失败后自动用 `_create_unverified_context()` 重试
- `search_openalex()` / `search_crossref()` / `search_arxiv()` / `search_s2()` 各自独立，任一失败不影响其他源
- 主流程用 `failed` 列表收集失败的源，最后统一提示，**不会因为某个源挂了就整体失败**
- `rebuild_abstract()` 把 OpenAlex 的倒排摘要索引还原成文本
- `resolve_access()` 判定可得性，顺序为「先免费后收费」：OA（含 arXiv）→ CNKI → SUB → `?`
- `normalize_paper()` 把非法的 `access` 值降级为 `?`，不让脏值流到下游
- `sort_by_access()` 稳定排序，**只重排不丢弃**；`--only-free` 过滤后为空不回退
- `access_hint()` 给出「怎么拿到全文」的具体下一步
- `to_ris_entry()` 生成 RIS（`TY/AU/PY/DO/UR/AB/ER` 字段）
- `download_pdf()` 校验文件头必须是 `%PDF` 才算下载成功
- 文件名格式：`年份_第一作者姓氏_标题前60字.pdf`（已过滤非法字符）

### `zotero_query.py` — 读取 Zotero 馆藏（题录/附件/笔记/标注）

```bash
python scripts/zotero_query.py [关键词] [选项]
```

| 参数 | 说明 |
|---|---|
| `query`（位置，可省略） | 关键词；留空则列出最近文献。同时匹配**标题、作者、摘要、笔记内容** |
| `--limit` | 返回条数上限，默认 15 |
| `--pdf` | 显示 PDF 附件的本地路径（走 sqlite 副本路径） |
| `--notes` | 显示笔记摘录（走 sqlite 副本路径） |
| `--key ZOTERO_KEY` | 导出单条目的全部字段、笔记、PDF 标注（高亮/批注+页码） |

**输出字段**：年份、标题、作者（超 4 位显示 et al.）、条目类型、Zotero Key、出处期刊、（可选）PDF 路径与笔记摘录。独立笔记条目（如 Better Notes 的欢迎笔记、ReadingTime 的 JSON 笔记）会如实出现——它们是库里真实存在的条目。

### `zotero_save.py` — 检索结果自动入库 Zotero

```bash
python scripts/zotero_save.py --json <search_papers导出的JSON> (--items 2,5 | --all)
python scripts/zotero_save.py --json <JSON> --all --collection "本科毕设参考文献"   # 归入分类
python scripts/zotero_save.py --list-collections                # 列出库中分类
python scripts/zotero_save.py --authorize                       # 只做写入授权
```

| 参数 | 说明 |
|---|---|
| `--json FILE` | 输入：`search_papers.py --json` 导出的结果文件（`--authorize` / `--list-collections` 时可省） |
| `--items 2,5` | 要入库的编号（对应 JSON 里的 index），与 `--all` 互斥 |
| `--all` | 入库全部 |
| `--authorize` | 单独完成本地 API 写入授权，不读 `--json` |
| `--collection` | 入库到指定分类，可多个（逗号分隔）。支持全名 / 唯一名称片段 / 8 位分类 Key |
| `--list-collections` | 列出 Zotero 全部分类（名称 + Key），不执行入库 |

**流程**：定位 Zotero 数据目录 → sqlite 副本查重（DOI + 规范化标题）→ 双路径写入。
API 路径下：`POST /api/users/0/items` 建 journalArticle 条目 → `api_attach_pdf()`
四步上传全文 → 逐条打印结果。

**5 种入库状态**（`main()` 里的 `STATUS` 字典，改文案同步改这里）：

| 状态码 | 打印文案 | 含义 |
|---|---|---|
| `skip` | 跳过 | 馆藏已有（DOI/标题查重命中） |
| `api` | 已建立条目并挂上 PDF 全文 | 最理想 |
| `api_nopdf` | 已建立条目（该文献无开放获取全文，未挂附件） | **分两种**：源站没有免费 PDF / 有链接但下载失败（403、网络、写盘）——脚本按真实原因分别说明，`--json` 里的 `local_pdf_status` 也带这个状态 |
| `api+pdf_fail` | 已建立条目，但 PDF 未能挂为附件 | 上传被拒/中断，文件仍在 `skill-import/` |
| `staged` | 已存入 skill-import，等待导入 | RIS 兜底路径 |

**授权类失败不重试**：`AuthRequired(RuntimeError)` 专门标识「需人工点『允许』/开关未开」这类
自愈无望的失败。批量入库时首次命中即把**本批余下条目整体转 RIS**，避免逐条尝试导致连弹授权窗。

**分类归属（v1.4.0）**：`--collection` 让条目建出来就落在指定分类下（走请求体的 `collections` 字段）。

| 环节 | 说明 |
|---|---|
| 列表 | `list_collections()` **取本地 API 与 sqlite 副本的并集** |
| 解析 | `resolve_collections()` 支持全名 / 唯一片段 / 8 位 Key；未命中或多义时抛错并列出候选 |
| RIS 路径 | **不带分类信息**，兜底导入后需用户手工拖入分类（脚本会明确提示） |

> ⚠️ **实测坑：本地 API 的分类列表可能少于库里实际分类**。本机 3 个分类，`GET /api/users/0/collections`
> 只返回 2 个（新建分类短期不进 API 索引）。若按「API 优先、失败才回退」写，会出现分类明明存在却报
> 「找不到」。**必须合并两个来源**。
>
> ⚠️ **代码坑：`open_ro_copy()` 是上下文管理器**（内部 `yield`），必须 `with ... as con:`。
> 写成 `con = open_ro_copy(...)` 拿到的是生成器，`con.cursor()` 抛的异常会被 `except Exception: pass`
> 静默吞掉，表现为「sqlite 来源永远为空」——很难查。

**入库补下载**：检索时没下 PDF 的条目，入库阶段若 JSON 里有 `pdf_url` 会**再试一次**下载；
补不下来就按「无开放获取全文」如实报告，不会静默跳过。

### `zotero_grab.py` — 用 Zotero 抓取器抓 URL/DOI（v1.5.0 新增）

```bash
python scripts/zotero_grab.py --check                              # 检测抓取器可用性
python scripts/zotero_grab.py "https://arxiv.org/abs/2401.00001"   # 抓单个页面
python scripts/zotero_grab.py --doi 10.1000/oa-001                 # 按 DOI 抓
python scripts/zotero_grab.py --urls 文献库/待抓.txt                # 批量
python scripts/zotero_grab.py "https://arxiv.org/abs/1" --dry-run # 只校验不提交
```

**与 `zotero_save.py` 的分工**——用**不同端口的不同服务**：

| | zotero_save.py | zotero_grab.py |
|---|---|---|
| 端点 | `23119/api/...`（本地 API） | `23119/connector/...`（抓取器） |
| 鉴权 | 需 Server-ID + API Key（弹窗授权） | **无需鉴权**，需声明 `X-Zotero-Connector-API-Version: 3` |
| 输入 | 结构化条目 JSON | 网页 URL / DOI |
| 谁解析元数据 | 我们给什么就是什么 | **Zotero 自己解析页面** |
| 全文 PDF | 脚本下载后三步上传 | **Zotero 自己从页面抓** |

**能力边界（最关键）**：

| 来源 | 命令行能否抓全文 |
|---|---|
| arXiv / OA 期刊 / 有公开 PDF 直链的页面 | ✅ 能 |
| **知网 / 万方 / 维普** | ❌ **不能**——需登录 + 机构授权 + 反爬。脚本识别后**不提交**，单独列出并给「用浏览器插件抓」的指引 |
| 学校订阅的出版商页面 | ❌ 不能——依赖校内 IP / VPN |

**红线**：绝不绕过登录、付费墙或反爬，不保存任何账号凭据。知网/万方类链接走浏览器插件
（插件带登录会话）是唯一合规的自动化入口。

**退出码语义**：知网类链接的分流**不算失败**（返回 0，附「这是正常分流」说明）；
只有「本可自动抓却提交失败」才返回 1。

---

## 五、Zotero 集成机制

### 读取（两条路径，自动择优）

1. **本地 HTTP API**（Zotero 运行中）：`http://localhost:23119/api/users/0/items`，只读无需 Key
   ✅ **本机已验证**（`api_up()` 返回 True；带 `--pdf/--notes` 时仍走 sqlite 副本取细节）
2. **sqlite 只读副本**（Zotero 未运行）：定位 `zotero.sqlite` → 复制到临时目录 → 标准库 sqlite3 查询
   ✅ **本路径已验证**，数据目录 `C:\Users\Admin\Zotero`
   - 数据目录定位顺序：`%APPDATA%\Zotero\Zotero\Profiles\*\prefs.js` 里的 `extensions.zotero.dataDir` → `%USERPROFILE%\Zotero`
   - **绝不直连原库**——Zotero 运行时原库被锁定
   - 会一并复制 `-wal` / `-shm` 日志，避免漏掉未合并数据

**PDF 附件定位规则**（踩过坑，别改错）：
`storage/<目录名>/文件名.pdf` 中的**目录名是附件自身的 item key，不是父条目的 key**。脚本用 `itemAttachments.parentItemID`（数字 itemID）匹配条目、再用附件自身 itemID 反查 key。父条目 key 和附件 key 是两套值，用错就找不到文件。

### 写入（双路径自动择优，绝不直写 zotero.sqlite）

**输入**：`search_papers.py --json` 导出的结果文件（含 local_pdf 路径，避免解析 RIS 配对 PDF）。

1. **本地 API 写入**（Zotero 7+ 运行中且开启「设置→高级→允许其他应用与此电脑上的 Zotero 通信」）：
   三步就绪（通信开关 / `Zotero-Server-ID` 头 / `POST /api/local/authorize` 换 API Key，
   最后一步**会在 Zotero 弹窗需用户点「允许」**，Key 缓存在
   `<数据目录>/skill-import/.zotero_api_key`，401 时自动刷新一次）。
   ✅ **已实测通过**（v1.2.0 打通）
2. **PDF 附件上传**（同一 API 路径，条目建成后立即执行）：
   建 attachment 条目 → 声明上传拿 `uploadKey`（**必须带 MD5**）→ POST 字节 → 登记 `uploadKey`。
   封装在 `api_attach_pdf()`；失败抛异常，入库存为 `api+pdf_fail` 状态并保留 `skill-import/` 兜底。
   ✅ **已实测通过**（v1.3.0 打通，字节级 MD5 校验一致，见 `references/zotero.md`）
3. **RIS 导入兜底**（Zotero 未运行）：PDF 与 `batch.ris` 写入 `<Zotero数据目录>/skill-import/`，用户在 Zotero「文件→导入」一次完成（勾选按 DOI/标题去重）。
   ✅ 落盘与 RIS 生成已实测；GUI 导入这一步需人工操作，未走通全流程。
   ⚠️ **RIS 格式不含分类信息**——走这条路径的条目导入后需手工拖入目标分类，脚本会提示。

`batch.ris` 采用**追加合并**：分多次入库时此前批次待导入的题录不会丢（重复条目按 DOI/链接/标题识别跳过），实测验证过。

### 抓取入库（抓取器路径，v1.5.0）

**第 4 条写入路径**：`23119/connector/saveItems`（Zotero 抓取器，无需 Key）。
把 URL/DOI 交给 Zotero，由它自己解析页面并抓取可获取的全文。
⚠️ **知网/万方/维普链接命令行走不通**（无登录会话），脚本会主动分流给浏览器插件。
详见上文「`zotero_grab.py`」小节与 `references/zotero.md` 的抓取器章节。

> **红线澄清**：新建条目与上传 PDF 附件走的是 **Zotero 自己的 HTTP 服务**（它对数据的处理是安全的），
> 不属于「直写 zotero.sqlite」。红线禁止的是绕过 Zotero 去改库文件。
> 抓取器同理——它也是 Zotero 自己的服务。

**升级路径**：装 Better BibTeX / 配 Zotero Web API Key 可进一步支持按条目重命名、自动同步等。

---

## 六、关键设计约定（改 skill 时需一并维护）

### 目录约定（SKILL.md「环境约定」）

```text
文献库/
  batch.json           ← 最近一次检索的结构化结果（zotero_save.py 的输入）
  文献索引.md           ← 文献总索引
对话记录/
  历史对话.md           ← 唯一的历史对话文件，只追加不覆盖
<Zotero数据目录>/skill-import/   ← 入库 PDF + batch.ris（脚本自动定位 Zotero 数据目录）
```

产物放在**工作区根目录**（用户启动会话的目录）。改这里要同步改 SKILL.md「环境约定」和「一、文献查找」第 5、6 步。

### 文献索引格式

表格骨架与逐字段填写要求已抽到 `templates/literature-index.md`（v1.1.0 起不再内联在 SKILL.md 正文里），
照它建 `文献库/文献索引.md` 并追加新条目。改列时改模板 + SKILL.md「一、文献查找」第 6 步。

### 历史对话格式

会话区块骨架与文件头在 `templates/history-entry.md`，SKILL.md「三、历史对话存储」引用它。

### 检索词经验（已固化进 research-roadmap.md）

- **叠加术语**比单字有效：对象 + 方法 + 任务（如 `tolerance specification knowledge graph`）优于泛词
- **避开泛词**：`review`、`analysis`、`method` 会把结果带到医学、生物领域
- **中文必须试同义词**：**单个词搜不到不代表没有文献**，按对照表多试几组。⚠️ 注意别把"当时的快照"写死成规律——
  2026-10-08 曾记「实测搜『容差』为空、搜『公差』命中」，而 **2026-10-12 复查时「容差」正常命中**
  （如「飞机装配容差分析技术研究」，但精度低、混入政策文本）。经验性事实要带观测日期，别固化进规范层。
  对照表见 `research-roadmap.md`（容差/公差、本体/知识模型、工艺审查/工艺评审等十组，含本体建模工具、图谱存储两行）
- **中文检索在 OpenAlex 上"能用但精度低"**（2026-10-12 实测）：`航空发动机 容差` 与 `航空发动机容差`
  命中集**完全相同**（空格编码不影响），但会返回公示文件、政策文本等非学术条目；
  词序不影响，故中文结果**必须逐条人工剔除**，学术检索仍建议英文，中文全文走知网/图书馆路径。
- **工具检索要两条腿**（实测）：`HugeGraph` 能搜到直接文献——如「Transforming RDF to Property Graph in Hugegraph」(2020) 正对应 Protégé→HugeGraph 的衔接点，但总量远少于 Neo4j；`Protege ontology` 返回工具方法学经典（Noy 等 2001 起），做具体课题要与领域词组合。所以工具名和主流替代工具名都要搜，呈现时区分「直接针对该工具」与「可迁移的方法」
- **已验证检索词**：`tolerance specification knowledge graph`、`aviation manufacturing knowledge graph ontology`、`HugeGraph`、`Protege ontology`（命中结果均记在 research-roadmap.md）

---

## 七、实测状态一览
| 能力 | 状态 | 说明 |
|---|---|---|
| OpenAlex 检索 | ✅ 已验证 | 主力源，精度与稳定性最好 |
| Crossref 检索 | ✅ 已验证 | 可用，噪音较多；**查询串是 DOI 时走 `/works/{doi}` 精确核验**（v1.5.2），只认 CC 类授权判 `OA` |
| arXiv / Semantic Scholar | ⚠️ 逐源判断 | arXiv **可用**（2026-10-08 实测恢复，偶有限流）；Semantic Scholar 常限流，脚本自动跳过并如实汇报 |
| PDF 下载 | ✅ 已验证 | 实测 4 个真实 PDF（最高 2.3 MB），文件头校验通过。⚠️ 真 OA 源（Frontiers/MDPI）可下；Elsevier/ACM/IEEE 的 `pdf_url` 常 403，脚本如实报「未获取到」 |
| RIS 生成 | ✅ 已验证 | 字段完整，格式标准 |
| --json 导出 | ✅ 已验证 | index/title/authors/doi/local_pdf 等字段完整，zotero_save 可直接消费 |
| Zotero 馆藏读取（sqlite） | ✅ 已验证 | 读到 20+ 条馆藏，题录、附件定位均正确 |
| Zotero 笔记/标注读取 | ✅ 已验证 | `--notes` 列出笔记（含独立笔记条目）；`--key` 导出字段/笔记/标注 |
| Zotero 馆藏读取（本地 API） | ✅ 已验证 | `api_up()` True，题录级读取正常 |
| 入库查重 + skill-import 落盘 | ✅ 已验证 | 馆藏已有的正确跳过；PDF+RIS 正确落 `<Zotero数据目录>/skill-import/` |
| 本地 API 自动建条目 | ✅ 已验证 | 返回真实条目 Key（v1.2.0 打通三重保护；`--authorize` 弹窗授权） |
| **本地 API 上传 PDF 全文附件** | ✅ **已验证** | v1.3.0 打通四步协议；实测 20,037 字节 PDF 落 `storage/<附件Key>/`，**MD5 与源文件逐字节一致**；回读确认 |
| RIS 导入 Zotero（GUI） | ⚠️ 未走通 | 需人工操作；首次导入留意格式报错 |
| Zotero 附件文件 | ⚠️ 逐条判断 | 2026-09-16 复查：多数条目附件**已就位**（如 `storage\GD2RULJC\...HybirdRAG.pdf`）；早前「全部缺失」是旧快照，勿沿用 |
| Python 环境 | ✅ 可用 | `python` 可正常调用、脚本零第三方依赖；**版本随 PATH 而定**——WorkBuddy 托管环境内实测 3.13.14，系统 `E:\software\python` 为 3.14.7（两者都能跑） |
| **离线验证集** | ✅ **471/471 通过** | 5 套件（149+66+55+130+71）· 耗时 ~47s · EXIT 0。改脚本后必跑 |
| **多词查重一致性（v1.5.2 修复）** | ✅ **已验证** | `zotero_query.py` 两条路径统一为分词 AND；实测 `tolerance ontology` 在 sqlite 路径 0 → 4 条 |
| **Crossref DOI 直查（v1.5.2 新增）** | ✅ **已验证** | 传 DOI 走 `/works/{doi}` 精确核验；不存在的 DOI 受控返回空、不崩 |
| **Crossref `OA` 判定收紧（v1.5.2 修复）** | ✅ **已验证** | 只认 CC 类授权；同一篇 Springer 文章由 `OA` 纠正为 `SUB`，与 OpenAlex 一致；真 OA 源仍判 `OA` |
| **上传闸门** | ✅ **等级 A / 100 分 / 0 问题** | 通过检查 31 项；目录、全局副本、分发包三处均 PASS（EXIT 0）；改造前为等级 F / 0 分 / 6 BLOCKER |
| **行为层红线** | ⚠️ **待跨模型复测** | 10 条红线尚未经换模型验证；12 处缺口的来历见「五、红线与边界」段与 §9.5 生成指令 |
| **入库到指定分类** | ✅ **已验证** | v1.4.0；实测五篇本体文献归入 `AircraftAssemblyToleranceOntology`，回读 sqlite 确认 `collectionItems` 关联正确（0 → 5 条） |
| **全文可得性分级（OA/CNKI/SUB/?）** | ✅ **已验证** | v1.5.0；四类判定与优先排序均实测（四源夹具覆盖四种分级）；`--only-free` 过滤与空态行为已测 |
| **Zotero 抓取器入库（zotero_grab.py）** | ✅ **连通性已验证** | v1.5.0；`--check` 实测「抓取器可用」；知网链接分流实测正确（不提交、给插件指引、返回 0）。**实际抓取效果取决于 Zotero 抓取器库与目标页面** |

> **v1.3.1 复验记录**（2026-09-16，目录封装后）：三处闸门均 **A / 100 / 0 / 31 项通过**，
> 验证集均 **285 通过 / 0 失败**，**EXIT 0**。
> **v1.4.0 复验记录**（2026-09-16，分类功能后）：**三处**闸门均 **A / 100 / 0 / 31 项通过**，
> 验证集均 **309 通过 / 0 失败**（41.0s），**EXIT 0**；分发包 16 文件 / 76,246 B / byte-identical YES。
> **v1.5.0 复验记录**（2026-09-16，免费可得性 + 抓取器后）：**三处**闸门均 **A / 100 / 0 / 31 项通过**，
> 验证集均 **429 通过 / 0 失败**（40.5–40.6s），**EXIT 0**；分发包 **18 文件 / 96,735 B / byte-identical YES**，
> **确定性打包已验证**（两次打包 SHA256 均为 `64a632f5…7fe2`，完全一致）。
> 两处副本同步 `identical: YES`（16 → 18 文件，新增 `zotero_grab.py` 与 `test_grab.py`）。
> **v1.5.1 发布记录**（2026-10-08）：`SKILL.md` 的环境约定把 Python 版本由写死的「本机实测 3.14.7」
> 改为**不锁版本**——本机 `python` 现已解析到 WorkBuddy 托管运行时 3.13.14，系统 `E:\software\python`
> 仍是 3.14.7，版本随 PATH 漂移，不该固化进行为规范。`scripts/`、`references/`、`templates/`、`test/`
> 与 frontmatter 触发词**一律未动**。
> 复验：**三处**闸门均 **A / 100 / 0（31 项通过）**、验证集均 **429 通过 / 0 失败**（47.1–47.6s），
> **EXIT 0**；分发包 **18 文件 / 97,370 B / byte-identical YES**，确定性打包两次 SHA256 均为
> `506b8d2f…27b286`，完全一致。两处副本 `identical: YES`。
> 同日**文档复检**：修正本文档中残留的 v1.5.0 之前过时事实——目录树与封装形态文件数（16 → **18**）、
> `test/` 断言数（86/46/83/70 → **134/62/55/107/71**，补入 `test_grab.py`）、
> `CHANGELOG` 版本链（补 `1.4.0 → 1.5.0 → 1.5.1`）、Python 版本表述。
>
> **v1.5.2 发布记录**（2026-10-08，功能核查后的缺陷修复）：对 skill 做端到端实跑核查（真实联网 +
> 真实 Zotero 库），修掉 1 个真缺陷 + 2 处「文档声称有、实现却没有」的落差。
> ① `zotero_query.py` 两条路径多词匹配不一致（sqlite 退化成短语匹配，`--pdf`/`--notes` 下查重**静默漏检**）
> → 统一为分词 AND；② Crossref 无 DOI 直查分支（红线第 6 条此前**无实现**）→ 补 `/works/{doi}`；
> ③ Crossref「拿到 pdf link 即判 `OA`」会**夸大可得性**（踩红线第 10 条，出版商 TDM 链接不是免费全文）
> → 改为只认 CC 类授权。核查报告见工作区根 `功能核查报告-2026-10-08.md`。
> 复验：**三处**闸门均 **A / 100 / 0（31 项通过）**、验证集均 **454 通过 / 0 失败**（~48s），
> **EXIT 0**；分发包 **18 文件 / 102,950 B / byte-identical YES**，确定性打包两次 SHA256 均为
> `22be2b2f…f4b3aa`，完全一致。两处副本 `identical: YES`。
>
> **v1.5.3 发布记录**（2026-10-12，代码健壮性 + 测试有效性修复）：对 skill 做**代码层**检查
> （前一次核查只覆盖功能层），修掉 2 个会写坏数据/违反自身契约的缺陷 + 1 处**假覆盖**测试。
> ① `zotero_save.py` 的 `split_author()` 只按空格切分，把本 skill 自己 Crossref 路径产出的
> "Smith, John" 解析成 firstName="Smith," / lastName="John"（**姓名颠倒，直接写坏 Zotero 作者字段**）
> → 同时识别"名 姓"与"姓, 名"两种形态，含复姓与后缀；② RIS 兜底写 `batch.ris` 没有异常保护，
> 目录不可写时以裸 traceback 结束（**违反退出码契约，且降级路径整体失效**）→ 受控报错 + 给替代做法 + 非 0 退出；
> ③ 夹具在 OpenAlex 载荷顶层放了 `is_oa`，而**真实响应没有这个顶层键**（51 个顶层键实测核对），
> 于是那条断言"看着在测、实际测的是 `oa_status` 分支" → 夹具对齐真实结构，并补 `bronze` 档回归用例。
> 顺带：错误文案按异常类型分流（权限问题不再引导用户去关 Zotero）、`list_collections()` 两处
> `except Exception: pass` 改为如实汇报、PDF 下载失败与"本来没有链接"分开呈现、`_write_text` 写失败受控退出、
> 临时目录在受限环境下自动降级为固定名目录。检查报告见工作区根 `skill检查报告-2026-10-12.md`。
> 验证集 **454 → 471 断言**（test_parse 146→149、test_cli 63→66、test_zotero 120→130）。
> 复验：**三处**闸门均 **A / 100 / 0（31 项通过）**、验证集均 **471 通过 / 0 失败**（47.9–49.6s），
> **EXIT 0**；分发包 **18 文件 / 117,898 B / byte-identical YES**，确定性打包两次 SHA256 均为
> `8f32c0f9…b7d42b`，完全一致。两处副本 `identical: YES`。

---

## 八、想加功能 / 改东西时改哪里

| 你的需求 | 改哪里 | 注意 |
|---|---|---|
| **加新的文献数据源**（如 PubMed、DOAJ） | `search_papers.py` 新增 `search_xxx(query, max_results)` 函数，返回与其他源同结构的 dict 列表；在 `main()` 的 `--source` choices 里注册并加入调用链 | 返回字段必须含 `title/authors/year/venue/id/doi/link/pdf/abstract/access`，否则输出与 RIS 会缺项；**新源别忘了给 `access` 判定**（见 `resolve_access`） |
| **调整可得性判定规则**（如加「预印本平台白名单」、改中文识别范围） | `search_papers.py` 的 `resolve_access()` 与 `ACCESS_*` 三组常量 | 判定顺序是「先免费后收费」；改了分级取值必须同步 `ACCESS_LEVELS`/`ACCESS_RANK`/`ACCESS_LABEL` 三处，否则 `normalize_paper` 会把新值降级成 `?` |
| **改抓取器的来源白名单**（哪些链接判为「需浏览器插件」） | `zotero_grab.py` 的 `BROWSER_ONLY_HINTS` | 只是**分流提示**，不是安全边界；别试图在这里「放开」需登录的来源——那是红线（不绕登录/付费墙） |
| **支持中文文献库（知网/万方）** | ⚠️ 无公开 API，**脚本搜不了**。当前的实现是：`resolve_access()` 把中文文献标为 `CNKI`，`SKILL.md` 检索第 3 步给出人工检索路径，`zotero_grab.py` 把知网链接分流给浏览器插件 | 别引入需要登录的抓取；**命令行拿不到知网全文是事实，不要试图绕过** |
| **改产物目录**（如想直接存到 Zotero 的链接附件目录） | `SKILL.md`「环境约定」+「一、文献查找」第 5、6 步 | 若改成写入 Zotero 附件目录，需同时改判断「文件是否存在」的逻辑 |
| **改 PDF 附件上传行为**（如改文件名、传多个附件、跳过大于 N MB 的） | `zotero_save.py` 的 `api_attach_pdf()` 与 `_upload_*` 三兄弟 | 附件条目 `title` 现在就是文件名；大文件已分块算 MD5，无需改内存策略。**上传失败必须保持抛异常**，不能让调用方以为成功 |
| **调整入库状态文案** | `zotero_save.py` `main()` 里的 `STATUS` 字典 | 改了要同步 `SKILL.md`「一、文献查找」第 5 步的状态表与 `使用手册` 的第 3 步表 |
| **改分类行为**（如改成入库后再加分类、按关键词自动选分类） | `list_collections()` / `resolve_collections()` / `api_create(..., collections=)` | ⚠️ 分类列表**必须合并本地 API 与 sqlite 副本**两个来源——API 索引会滞后，只信 API 会漏掉新分类 |
| **加新功能章节**（如「文献综述自动生成」） | `SKILL.md` 新增「六、xxx」章节；**同时更新 frontmatter 的 `description`**，把触发词写进去，否则 skill 不会被触发 | `description` 是唯一的触发信号，写足关键词；现有触发词**只增不改** |
| **加 PDF 全文解析**（让问答能读全文） | 在 `SKILL.md`「二、知识问答」写明解析方式 | 注意**零依赖约束**：标准库无法解 PDF 文本，需取舍——要么允许用 pip 装 `pypdf`，要么改走外部工具 |
| **调整依据强度规则** | `SKILL.md`「二、知识问答」第 1 条 + `references/zotero.md` 的 `storage:` 段 | 这两处必须保持一致 |
| **加同义检索词** | `references/research-roadmap.md` 的「中文同义词对照」表 | 顺手把验证有效的检索词记到「已验证的有效检索词」段 |
| **换技术栈**（如本体工具改 WebProtégé、图谱改 Neo4j） | 三处同时改：`research-roadmap.md` 技术栈表 + 阶段 1/2 的检索词、`SKILL.md` 正文第 8 行、frontmatter `description` 触发词 | 漏掉 `description` 会导致提到新工具名时 skill 不触发；阶段 2 的历史版本曾误写 Neo4j，替换时注意别遗漏 |
| **更新筛选/排序策略** | `SKILL.md`「一、文献查找」第 4 步 | 脚本不做相关性判断，这层归模型 |

### 改完务必做的事

1. **跑验证集**：`cd aviation-literature && python test/run_all.py`——必须 `RESULT: PASS` 且退出码 0。
   这是改脚本后唯一能证明「没破坏既有行为」的手段。
2. **跑上传闸门**：`python <skill-quality-audit目录>/scripts/audit.py <skill目录> --profile upload`
   ——必须 EXIT 0，命中任一必修项不得交付。
3. **两处副本同步**：工作区 `E:\Learnings\文献查找及管理skill\aviation-literature\` 与全局 `C:\Users\Admin\.agents\skills\aviation-literature\`。
   ⚠️ **本机不要用 `xcopy`**——路径含中文时它会以 exit 1 失败（实测多次，甚至留下空目录）。
   用 `sync_skill.py`（见下）或 `Copy-Item -Recurse -Force`，同步后核对文件数与内容一致。
4. **清掉 `__pycache__\`**：`python -m py_compile` 与跑验证集都会产生缓存目录，拷进 skill 会显得脏。
   打包器 `pack_skill.py` 已自动忽略 `__pycache__` 与 `.pyc`。
5. **同步更新 `description`**：新增能力若没写进 `description`，skill 就等于不会被触发。
6. **递增 `version` 并写 `CHANGELOG.md`**：patch=补规则 / minor=新能力 / major=破坏性；
   **不要改动已有触发词**，否则用户原有的说法会失效。
7. **保持零第三方依赖**：新增功能若必须引入第三方包，要在 `SKILL.md`「环境约定」里写清安装方式，
   并说明 pip 指向哪个环境（本机 Anaconda 与独立 Python 3.14 的 site-packages 是分开的）。

### 配套工具脚本（本机实测可用）

| 脚本 | 用途 | 位置 |
|---|---|---|
| `sync_skill.py` | 两处副本同步 + 逐文件一致性校验（替代失效的 xcopy） | `C:\Users\Admin\WorkBuddy\2026-09-16-14-09-19\sync_skill.py` |
| `pack_skill.py` | 确定性打包（固定时间戳，两次打包 SHA256 一致）+ 包内与源码字节自证 | `C:\Users\Admin\WorkBuddy\2026-09-16-14-09-19\pack_skill.py` |
| `gate_check.py` | 三处闸门复验：目录副本 / 全局副本 / 分发包解包目录，各跑上传闸门 + 验证集 | `C:\Users\Admin\WorkBuddy\2026-09-16-14-09-19\gate_check.py` |

---

## 九、本目录封装形态

```text
E:\Learnings\文献查找及管理skill\
├── aviation-literature\             ← skill 包，18 文件；可整体拷贝到别的机器/工具
│   ├── SKILL.md
│   ├── CHANGELOG.md
│   ├── references\   (2)
│   ├── templates\    (2)
│   ├── scripts\      (4)
│   └── test\         (7 + fixtures\1)
├── SKILL功能说明.md                  ← 维护者文档（本文）
├── 使用手册-零基础上手.md             ← 使用者手册
└── 生成指令-aviation-literature.md    ← 生成指令（复现依据，自包含）
```

| 层 | 内容 | 是否随 skill 分发 |
|---|---|---|
| skill 包内 | `SKILL.md`、`CHANGELOG.md`、`references/`、`templates/`、`scripts/`、`test/` | 是 |
| 配套文档 | 功能说明、使用手册、生成指令（三份并列在包外） | 建议同交付 |
| 一次性产物 | 质检报告、边界用例审计、打包 zip、构建计划 | 否（已清理，见 `CHANGELOG.md` v1.3.0 / v1.3.1） |

**为什么三份文档放在包外而不是包内**：`SKILL.md` 与 `references/` 的每一条内容都会被模型在会话中读到，
往里塞面向人的长篇文档会稀释触发与执行精度；而 `audit.py` 的体检对象是 skill 包本身，
配套文档放包外能做到"包干净、文档齐全"两头兼顾。**拷 skill 到别处时只带 `aviation-literature/` 就够了**，
三份文档是给人看的，不是给模型看的。
