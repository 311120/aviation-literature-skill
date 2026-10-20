# 版本变更记录

## 1.5.3

**代码健壮性与测试有效性修复**——2026-10-12 对 skill 做**代码层**检查（上一次
`功能核查报告-2026-10-08.md` 覆盖的是功能层）。发现 2 个会写坏数据或违反自身契约的缺陷、
1 处"看着在测、实际没测到"的假覆盖，以及若干静默失败与错误文案问题。本版一并修复。

### 1. 真缺陷：`zotero_save.py` 作者姓名解析把姓名写反

`split_author()` 只按空格切分、把最后一节当姓氏：

| 输入 | 早先结果 | 问题 |
|---|---|---|
| `Smith, John` | firstName=`Smith,` / lastName=`John` | **姓名颠倒 + 姓氏带逗号** |
| `van der Berg, Anna` | firstName=`van der Berg,` / lastName=`Anna` | 同上 |

而 `Smith, John` 这种"姓, 名"形态**正是本 skill 自己 `search_papers.parse_crossref()` 的产出**
（`f"{family} {given}"`）——用 `--source crossref` 或 `--source all` 检索后入库，
写进 Zotero 的作者字段就是错的，且 `SKILL.md` 的交付前自查没有一条能拦住它。

**修复**：`split_author()` 同时识别两种形态——逗号形态取「姓, 名」，多逗号（如
`Smith, Jr., John`）保留后缀且仍以首节为姓氏；无逗号时沿用空格规则。

### 2. 真缺陷：RIS 兜底写入失败时裸露 traceback，降级路径整体失效

`main()` 对 `import_dir` 的创建做了 `try/except`，却把真正写 `batch.ris` 的
`open(..., "w")` 留在保护之外。目录不可写时实测表现为：

```
[运行失败] PermissionError：[Errno 13] Permission denied: '...\skill-import\batch.ris'
```

两个后果：违反 `SKILL.md` 的退出码契约（"只打印受控错误信息，不会裸露 traceback"）；
「文件→导入」的提示**根本不会打印**，用户在最需要指引的降级路径上反而拿不到任何指引。

**修复**：RIS 写入包 `try/except OSError`，受控报错 + 给出替代做法（改用工作区目录生成 RIS
或在 Zotero 手工拖入）+ 以非 0 退出。同类问题一并修：`search_papers._write_text()`
（`--ris`/`--json`/`--out` 写失败）也不再裸露 traceback，改为受控失败。

### 3. 假覆盖：测试夹具与**真实** OpenAlex 响应结构不一致

夹具在载荷**顶层**放了 `"is_oa"`，`test_parse.py` 据此断言"is_oa 为真判为 OA"。
但真实 OpenAlex `/works` 响应**没有顶层 `is_oa`**（实测核对 51 个顶层键，该键不存在），
开放获取信息只在 `open_access` 子对象里。于是 `search_papers.py` 的 `w.get("is_oa")`
在生产环境**恒为 None**（死代码），那条断言实际测到的是 `oa_status` 分支。

**修复**：夹具去掉顶层 `is_oa`（与真实响应对齐）、生产代码删掉死代码并加注释说明；
新增 `openalex_bronze.json` 夹具与 `bronze` 档回归用例——`bronze`（源站可免费读到、
但无开放许可）此前**无任何覆盖**，而它正处在"不得夸大可得性"的红线上。

### 4. 静默失败与错误文案（按真实原因分流）

- `zotero_save.list_collections()` 两个来源（本地 API / sqlite 副本）的异常都是
  `except Exception: pass`——库读不到时只报"未读到任何分类"，与"库里确实没有分类"
  无法区分。**这个反模式项目自己在 `CHANGELOG` 1.4.0 里记为"极难排查"的坑**，本处却在重犯。
  现改为收集失败原因、如实打印，两个来源都失败时以非 0 退出并给出排查方向。
- `zotero_query.py` 把所有读取失败都提示"若 Zotero 正在运行，稍等片刻重试；仍失败就先关闭 Zotero"。
  实测 PermissionError 的真实原因常常是**临时目录/数据目录不可写**，与 Zotero 是否运行无关——
  该文案把用户引向错误方向。现按异常类型分流：`PermissionError/OSError` 报路径与权限方向，
  `sqlite3.Error` 才提示关 Zotero。
- PDF 未获取到时的呈现：早先一律显示"未获取到开放获取 PDF（需手动获取）"，
  把「该文献没有开放获取链接」与「有链接但下载失败（403/网络/写盘）」混为一谈——
  等于把脚本/网络的故障说成"这篇没有全文"。现状态化为 `ok/no_url/not_pdf/error`，
  逐条给出真实原因；`--json` 新增 `local_pdf_status` 字段供下游使用。
- `download_pdf()` 在 `authors=[""]` 时 `[0].split()[-1]` 抛 `IndexError` 并被静默吞掉
  （表现为"没有全文"，实为下载代码崩了）→ 改为不会抛的取值方式。
- `open_ro_copy()` 改用 `copyfile`（副本只需内容一致），并新增 `_temp_dir()`：
  受限环境（沙箱只允许写工作区）下随机名临时目录"建得出来却写不进去"时，
  自动降级为固定名临时目录；验证集侧同样处理（`harness.make_temp_dir()`）。
- `zotero_query.find_data_dir()` 用 `path.startswith("C:")` 判断绝对路径，
  会把 `D:\...` 或 UNC 路径误当相对路径拼接 → 改用 `os.path.isabs()`。
- `search_papers.parse_arxiv()` 的 pdf 链接：arXiv id 带 `.pdf` 结尾时会产出
  `....pdf.pdf` → 已修正。

### 改动文件

- `scripts/zotero_save.py`：`split_author()` 双形态解析；RIS 写入 `try/except OSError`；
  `list_collections(reporter=)`、`resolve_collections(reporter=)` 如实汇报来源失败；
  `stage_pdf()` 返回 `(路径, 状态)`；`api_nopdf` 结果按真实原因说明。
- `scripts/search_papers.py`：`download_pdf_ex()` / `_first_author_surname()`；
  `LOCAL_PDF_LABEL` 与 `local_pdf_status`；`_write_text()` 受控失败；
  `parse_openalex()` 删死代码并注明 OpenAlex 结构；`parse_arxiv()` 后缀修正；
  失败源文案不再把"无结果"说成"限流/超时"。
- `scripts/zotero_query.py`：`_temp_dir()` 降级；`copyfile`；`_read_failure_hint()` 文案分流；
  `os.path.isabs()` 修正。
- `SKILL.md`：`version: 1.5.3`；降级路径表新增 4 行（临时目录不可写 / RIS 目标不可写 /
  分类来源读不到 / PDF 有链接但下载失败）；交付前自查 11 → **12** 条；自检段补受限环境运行说明。
- `test/`：`harness.make_temp_dir()`（受限环境降级）；四套件改用之；
  `test_parse` +3（bronze + 夹具结构）；`test_cli` +3（下载失败文案区分 + `--ris` 写失败受控）；
  `test_zotero` +10（作者姓名解析 + RIS 写入失败受控 + 只读保证改为快照差集）。
- `references/research-roadmap.md`、`references/zotero.md`：过期的中文检索快照改为带观测日期的表述；
  验证集数更新为 471。

**验证**（2026-10-12，本机）

```
离线验证集 454 → 471 断言（test_parse 146→149、test_cli 63→66、test_zotero 120→130）· 471/471 PASS · EXIT 0
真缺陷复现 修复前：--ris 指向目录 → 裸 PermissionError；split_author("Smith, John") → 姓名颠倒
           修复后：受控报错 + 非 0 退出；两形态均正确
```

## 1.5.2

**功能核查后的缺陷修复（三处）**——2026-10-08 对 skill 做端到端实跑核查（真实联网 + 真实
Zotero 库），发现 1 个真缺陷与 2 处「文档声称有、实现却没有」的落差。本版一并修复。

### 1. 真缺陷：`zotero_query.py` 两条读取路径的多词匹配语义不一致（漏检）

**现象**：同一查询在两条路径下结果不同，且 sqlite 路径会**静默漏检**。

| 查询 | 本地 API 路径 | sqlite 路径（`--pdf` / `--notes`） |
|---|---|---|
| `HybirdRAG` | ✅ 1 条 | ✅ 1 条 |
| `HybirdRAG aircraft` | ✅ 1 条 | ❌ **0 条** |
| `tolerance ontology` | ✅ 2 条 | ❌ **0 条** |

**成因**：API 路径把整串交给 Zotero 的 `q=`（Zotero 自己分词做 AND）；sqlite 路径早先用
`LIKE '%整串%'`，多词查询退化成**短语匹配**。而 `main()` 里 `--pdf` / `--notes` 会**强制走
sqlite**——`SKILL.md` 第 2 步推荐的查重命令正是 `zotero_query.py "knowledge graph" --pdf --notes`，
于是查重会漏检，后果是**重复下载**。

**修复**：新增 `build_sqlite_query(kw)`，按空白分词生成「每个词都必须命中」的 AND 条件
（每词在 标题/作者/摘要/笔记 四类字段任一命中即算命中），与 API 路径语义对齐。
单词语义不变；多词只会比原来的短语匹配命中更多（原文匹配短语的必然匹配全部词），
**只修漏检、不引入新漏检**。

### 2. `search_papers.py`：Crossref 支持 DOI 直查（红线第 6 条此前无实现）

`SKILL.md` 红线第 6 条要求「只给 DOI 时用 Crossref 核验原字段」，但 `search_crossref()`
固定请求 `works?query=`，**没有 DOI 直查分支**——把 DOI 当检索词丢进去只会返回无关文献
（实测搜 `10.1007/s00170-023-12644-y` 返回超导、胰腺炎等条目）。该红线此前**没有可执行的脚本路径**。

**修复**：新增 `DOI_RE` / `doi_of()`；查询串是 DOI（或 doi.org 链接）时改走
`/works/{doi}` 精确核验，核不到（404）时打印「Crossref 核不到该 DOI」并受控返回空。

### 3. `search_papers.py`：Crossref 的 `OA` 判定夸大可得性（违反红线第 10 条）

Crossref 的 `link` 里常带出版商的 **TDM（text-mining）端点**（`intended-application` 为
`text-mining` / `similarity-checking`），那是给机器批量抓取的授权通道，**不是**免费全文。
早先「拿到 pdf link 即视为 OA」会把付费期刊误标成免费。实测同一篇
`10.1007/s00170-023-12644-y`：OpenAlex 判 `SUB`、Crossref 判 `OA`，后者是错的
（该文 license 为 springernature 的 TDM 条款，无 CC）。

**修复**：新增 `_crossref_is_oa(item)`——**只认 Creative Commons 类开放授权**；
非开放获取时不再填 `pdf`（避免下游误触发下载与挂附件）。真 OA 源（Frontiers/MDPI 等）不受影响。

**改动文件**

- `scripts/zotero_query.py`：`SQLITE_SQL` 常量 → `_SQLITE_SQL_TMPL` + `_MATCH_ONE_TERM` +
  `build_sqlite_query()`；`_query_sqlite()` 改用生成器返回的 (sql, params)。
- `scripts/search_papers.py`：新增 `DOI_RE` / `doi_of()`；`search_crossref()` 增加 DOI 分支；
  新增 `_OA_LICENSE_RE` / `_crossref_is_oa()`；`parse_crossref()` 改用 `is_oa` 判定并据此决定是否填 `pdf`。
- `SKILL.md`：`version: 1.5.2`；「一、文献查找」来源说明更新（Crossref DOI 直查 + 只认 CC 授权；
  arXiv 改为**可用**）；红线第 6 条补注脚本已支持 DOI 直查。
- `test/fixtures/make_fixtures.py`：`CROSSREF` 夹具 1 → **2 条**，新增「只有 TDM 端点、无 CC 授权」
  的付费条目作为回归用例；原条目补 CC-BY 授权。
- `test/test_parse.py`：Crossref 断言更新并新增 CC 识别与 `doi_of` 用例（134 → **146**）。
- `test/test_zotero.py`：新增多词 AND 匹配与 `build_sqlite_query` 契约用例（107 → **120**）。
- `test/test_cli.py`：四源条数 7 → **8**、去重 6 → **7**（Crossref 夹具增 1 条）。

**验证**（2026-10-08，本机）

```
离线验证集 429 → 454 断言（test_parse 134→146、test_zotero 107→120）· 454/454 PASS · EXIT 0
上传闸门   三处（工作区副本 / 全局副本 / 分发包解包）均 A / 100 / 0（31 项）· EXIT 0
真实回归   多词查询 sqlite 路径 0 → 4 条；Springer DOI 由 OA 纠正为 SUB；Frontiers/MDPI 仍判 OA
分发包     dist/v1.5.2/aviation-literature.zip · 确定性打包（两次 SHA256 一致）
```

## 1.5.1

**环境约定措辞修正（无行为变更）**——`SKILL.md`「环境约定」把 Python 版本从写死的
「本机实测 3.14.7」改为不锁版本。

**背景**：该句原意只是「直接用 `python`，不需要 pip」，但把具体版本号写进指令层会随环境漂移。
本机 `python` 现已解析到 WorkBuddy 托管运行时 **3.13.14**，而系统 `E:\software\python` 仍是
**3.14.7**——同一台机器上不同 shell 的 PATH 顺序不同，`python -V` 的结果就不同，
写死版本号属于把易变的环境快照固化进行为规范。脚本纯标准库、未用任何版本相关语法
（无 walrus `:=`、无 `match`），任意 Python 3 解释器均可运行。

**改动**

- `SKILL.md`：`version: 1.5.0` → **`1.5.1`**；「环境约定」Python 行改为
  「脚本零第三方依赖，任意 Python 3 解释器均可，无需 pip」，保留 9009 报错时改用
  `py` 或解释器完整路径的回退说明。
- **未改动**：`scripts/`、`references/`、`templates/`、`test/` 一律未动；
  frontmatter 的 `description` 触发词**只增不改**原则下本次未增删任何触发词。

**验证**（2026-10-08，本机）

```
上传闸门  工作区副本 A / 100 / 0（31 项）· 全局副本 A / 100 / 0（31 项）· EXIT 0
离线验证集 429 / 429 通过（47.6s / 47.1s）· EXIT 0 —— 与 v1.5.0 完全一致（未破坏既有行为）
分发包    dist/v1.5.1/aviation-literature.zip · 确定性打包（两次 SHA256 一致）
```

## 1.5.0

**优先免费可得：分级标注 + 优先排序 + 抓取入库**——用户提出「该 skill 优先寻找免费的、
可在知网、学校图书馆中可下载的文献」。原脚本只认「有没有开放获取 PDF」这一条线，
既无免费可得性的分级概念，也没把「知网/馆藏可获得」纳入排序与呈现。

**先说清楚边界（这次改动的核心判断）**

「知网 / 学校图书馆可下载」**无法由脚本自动核实**——知网无公开 API、
馆藏权限取决于学校的订阅范围与 IP/VPN 授权，脚本看不到这部分信息。
因此本次做的是**分级标注 + 排序偏好**，不是「保证可下载」：

| 标签 | 含义 | 判定依据 |
|---|---|---|
| `OA` | 公开开放获取，**真免费** | OpenAlex `is_oa`/`oa_status`、S2 `openAccessPdf`、arXiv 预印本、Crossref 的 pdf link |
| `CNKI` | 中文库（知网/万方等） | 标题或期刊名含汉字且非 OA |
| `SUB` | 出版商页面，需机构订阅 | 有 DOI 但无开放获取标识 |
| `?` | 无法判定 | 既无 DOI 也无 OA 标识 |

**改动**

- `search_papers.py`：
  - 新增 `access` 字段与三组常量 `ACCESS_LEVELS` / `ACCESS_RANK` / `ACCESS_LABEL`；
  - 新增 `resolve_access(...)`：按「先免费后收费」判定分级；`normalize_paper` 把非法值降级为 `?`；
  - `parse_openalex` 读 `is_oa` 与 `open_access.oa_status`（原代码只看 `pdf_url` 有无）；
  - 新增 `sort_by_access(papers)`：`OA → CNKI → SUB → ?` 稳定排序，**只重排不丢弃**；
  - 新增 `access_hint(p)`：给出「怎么拿到全文」的具体下一步，不是笼统「需手动获取」；
  - `render_markdown` 输出可得性标签、获取方式行，以及顶部「N/M 条可免费获取」统计；
  - CLI 新增 `--only-free`（只留 OA+CNKI）与 `--no-prefer-free`；**默认即按可得性优先排序**。
- **新增 `scripts/zotero_grab.py`**：用 Zotero 抓取器（`23119/connector/saveItems`）
  把 URL/DOI 交给 Zotero 自己解析抓取，含可获取的全文。与 `zotero_save.py` 分工互补：
  前者让 Zotero 去抓，后者写已经到手的条目。
- `SKILL.md`：`version: 1.5.0`；「一、文献查找」新增可得性分级表与**优先免费可得**原则、
  中文库（知网/万方/维普）操作路径、抓取器用法；降级路径表新增 3 行；
  交付前自查 9 → 11 条；「五、红线与边界」新增第 9、10 条（不绕付费墙、不夸大可得性）。
  `description` 新增触发词：免费文献、开放获取、知网、学校图书馆（只增不改）。
- `references/research-roadmap.md`：新增「全文获取路径」整节（分级表 + 中文库检索路径
  + 图书馆订阅路径 + 优先级建议）。
- `references/zotero.md`：新增抓取器章节（与 save 的分工对照、能力边界表、实测记录）；
  补记「本地 API 的 DELETE 是硬删除」；修正「本地 API 尚未验证」的过期表述。
- `test/`：新增 `test_grab.py` 套件（55 条断言）；`test_parse` +47、`test_cli` +16、
  `test_boundary` +1；夹具 `OPENALEX` 由 2 条扩为 4 条（覆盖 OA/SUB/CNKI/? 四种分级）。

**实现要点**

| 点 | 做法 |
|---|---|
| 分级判定顺序 | 先 OA（含 arXiv）→ 再 CNKI（含汉字）→ 再 SUB（有 DOI）→ 否则 `?` |
| 脏值防御 | `normalize_paper` 把非 `ACCESS_LEVELS` 的 access 值降级为 `?`，不让脏值流到下游 |
| 排序稳定性 | 用 `sorted`（稳定）+ 单一 sort key，同级保持原相关性顺序 |
| 不丢条目 | `sort_by_access` 只重排；`--only-free` 过滤后为空就输出空清单，**不回退成全量** |
| 抓取器鉴权 | 无需 Key，但必须带 `X-Zotero-Connector-API-Version: 3` |
| 知网分流 | 命中 cnki/wanfang/cqvip 特征即**不提交**抓取器，单独列出并给浏览器插件指引 |

**实测发现的一个真坑（测试流程缺陷，顺手修了）**

改夹具后跑测试出现 **15 个假失败**，排查发现 `harness.fixture_data_dir()` 只在
`payloads/` 目录**不存在**时才生成夹具——旧缓存会静默生效，制造出一批与代码无关的失败。

修复过程中还踩了第二个坑：最初改用「目录 mtime」做新鲜度锚点，
但 `os.makedirs(exist_ok=True)` **不会更新已存在目录的时间戳**，重建后 mtime 不变，
整个检测形同虚设（验证时明确复现了「防护失效」）。最终改为由 `make_fixtures.py`
落一个 `.built` 标记文件，按**标记 mtime vs 源码 mtime** 判断是否需要重建。

**实测记录**（2026-09-16，本机真实 Zotero）

```
zotero_grab.py --check    → 「Zotero 抓取器可用（127.0.0.1:23119）」✅
知网链接分流              → 列出「[知网] https://kns.cnki.net/...」，未提交，返回 0 ✅
search_papers 分级        → OA/SUB/CNKI/? 四类判定与排序顺序均符合预期 ✅
```

**验证**：离线验证集 **310 → 429** 断言（`test_parse` 87 → **134**、`test_cli` 46 → **62**、
`test_grab` **55**（新）、`test_zotero` 107、`test_boundary` 70 → **71**）。
全程零第三方依赖。

## 1.4.0

**入库支持归入指定分类**——用户实测使用时提出「将这五篇入库，存储在 Zotero 相应的分类下」，
原脚本只会把条目建到「我的文库」根下，无分类能力。本次补上并实跑验证。

**改动**

- `zotero_save.py`：
  - `api_create(paper, data_dir, reporter=None, collections=None)` 新增 `collections` 参数，
    非空时在请求体写入 `"collections": ["<8 位分类 Key>"]`；
  - 新增 `list_collections(data_dir)`：列出全部分类（名称 + Key）；
  - 新增 `resolve_collections(spec, data_dir)`：把 `--collection` 的写法解析成分类 Key 列表；
  - CLI 新增两个子命令：`--list-collections`（列出分类）、`--collection NAME|KEY`（指定分类）；
  - 分类在**入库前一次性解析**——名字写错时在第一条条目建出来之前就报错退出，
    不必等建完才发现；
  - 结果输出新增分类归属提示；走 RIS 路径时明确提醒「RIS 不带分类」。
- `SKILL.md`：`version: 1.4.0`；「一、文献查找」第 5 步补分类用法与四条硬约束
  （先确认分类存在 / 不硬编名字 / RIS 不带分类要明说 / 声称已归入前必须回读 `collectionItems` 核验）；
  「交付前自查」新增第 5 条对应检查项（原 5–8 条顺延为 6–9）。
- `test/`：新增 `_test_collections` 22 条断言（含「只存在于 sqlite 的分类」这一核心回归）；
  夹具 `make_fixtures.py` 新增 `collections` / `collectionItems` 两表与 2 条分类数据。

**实现要点**

| 点 | 做法 |
|---|---|
| 分类标识 | 用 **8 位大写字母数字 Key**（如 `IN7CD4ST`），不是数字 `collectionID` |
| 写法兼容 | 全名（忽略大小写）/ 8 位 Key / **唯一名称片段**；多义或未命中抛 `ValueError` 并列出候选 |
| 多分类 | `--collection A,B` 逗号分隔，去重并保持输入顺序 |
| 归类时机 | 建条目时随请求体带上，不是建完再 PATCH |

**实测发现的两个真坑**

1. **本地 API 的分类列表会滞后于库内实际状态**。本机库里有 3 个分类，而
   `GET /api/users/0/collections` 只回了 2 个（新建分类短期不进 API 索引）——
   最初按「API 优先、失败才回退 sqlite」写，表现为「分类明明存在却报找不到」。
   改为**两个来源取并集**（同 Key 以 API 名称为准）。
2. **`open_ro_copy()` 是上下文管理器**（内部用 `yield`）。写成 `con = open_ro_copy(...)`
   拿到的是生成器对象，`con.cursor()` 抛出的异常被外层 `except Exception: pass`
   静默吞掉，表现为「sqlite 来源永远为空」且**零报错**，极难排查。必须 `with`。

附带：`--list-collections` 首次实现时返回退出码 2，原因是它被加在 `required=True`
互斥组之外，argparse 会追问 `--items`；须与 `--items/--all/--authorize` 同组。

**入库实测**（2026-09-16）：五篇本体构建文献全部归入 `AircraftAssemblyToleranceOntology`，
回读 sqlite `collectionItems` 核验关联正确（0 → 5 条）。五篇均为付费墙期刊、无开放获取全文，
状态为 `api_nopdf`。

**验证**：离线验证集 **285 → 309** 断言（`test_zotero` 83 → **107**）；
三处位置（工作区副本 / 全局副本 / 分发包解包）上传闸门均 **A / 100 / 0（31 项）**，
验证集均 **309/309 PASS**。

## 1.3.1

**目录封装 + 配套文档补齐**——用户要求：把 skill 封装在 `<工作区>` 下、
清掉无用文件、并把三份文档一并交付。

**改动**

- **目录形态**：skill 从 `.agents\skills\aviation-literature\` 深嵌路径提到目录根
  （`文献查找及管理skill\aviation-literature\`），与三份配套文档并列。skill 包内 16 个文件
  **逐字节未变**，本次改动不影响任何脚本行为与验证集结果；
- **三份配套文档齐备**：
  - `SKILL功能说明.md`（维护者：怎么改）
  - `使用手册-零基础上手.md`（使用者：怎么用）
  - `生成指令-aviation-literature.md`（**新增**，复现依据：把 skill 拿到别处从零重建）
- **生成指令同步到 v1.3.0 实现基准**（原 `文献查找及管理skill.txt` 停留在 v1.1.1，已过时）：
  - 第 5 节目录树补 `CHANGELOG.md` / `templates/` / `test/`，并给出 285 断言基准分布；
  - 第 8 节实测状态表：**本地 API 读取 → 已验证**、**本地 API 建条目 → 已验证**、
    **附件文件「全部缺失」→ 逐条判断**（旧快照不准），**新增「本地 API 上传 PDF 全文附件 ✅ 已验证」**；
  - 新增 PDF 附件上传**四步协议**表、写入**三重保护**表（含 428/401 报错原文）、
    第四个保护层（DELETE 的 `If-Unmodified-Since-Version`）；
  - 入库状态 3 种 → **5 种**；补 `AuthRequired` 与"首次命中即整体转 RIS"策略；
  - 第 9.1 节：**明令禁止 `xcopy`**（中文路径下 exit 1 失败），改用 Python 同步脚本；
  - 第 9.3 节维护动作 4 条 → **6 条**，补"跑验证集""跑上传闸门"与"清运行期产物"；
  - 新增 8.3 节"实现坑表"（8 条）与 9.5 节"红线条款来历"（12 处缺口 → 8 条红线的推理链）。
- **行为规范原文本身未动**（`SKILL.md`、`references/`、`templates/`、`scripts/`、`test/` 全未修改），
  故 `description` 触发词不变、验证集与闸门结果应与 v1.3.0 完全一致。

**清理**（移入 `_backup_<时间戳>/`，非直接删除）

| 项 | 为什么不进交付 |
|---|---|
| `.zcode\plans\` | 构建过程计划，一次性产物 |
| `qa\`（TEST-KIT / rubric / 边界审计） | 关3 压测过程证据，结论已固化进 SKILL.md 红线 |
| `QC报告-aviation-literature-v1.1.1.md` | 针对 v1.1.1 的旧质检报告，版本已过期 |
| `对话记录\` | **运行期产物**，本不该进交付目录 |
| `dist\v1.2.0\`、`dist\` 旧包 | 旧版本分发包 |
| `文献查找及管理skill.txt` | 已被 `生成指令-aviation-literature.md` 取代（内容同步升级） |

**验证**：见本次交付的三处闸门 + 验证集结果，应与 v1.3.0 一致（16 文件 / 285 断言 / A·100·0）。

## 1.3.0

**入库从「只建条目」升级为「条目 + 全文 PDF 附件」**——用户明确要求：入库时不能只在 Zotero
里生成题录，还要把文献的具体内容（PDF）下载下来挂上。

打通 Zotero 7 本地 API 的**附件文件上传**（此前文档标注「未实现」，故 PDF 只落
`skill-import/` 等用户手拖）。实测协议四步：

| 步 | 请求 | 关键点 |
|---|---|---|
| 0 | `POST /api/users/0/items`（`itemType=attachment`, `linkMode=imported_url`, `parentItem=<父Key>`） | 先建附件条目，拿附件自身的 Key |
| 1 | `POST /api/users/0/items/<附件Key>/file`，form-urlencoded `md5&filename&filesize&mtime`，带 `If-None-Match: *` | **缺 MD5 会 `400 MD5 hash not provided`**；返回 `{url, uploadKey}` |
| 2 | `POST <步1的 url>`，body 为 PDF 原始字节，`Content-Type: application/pdf` | `201` |
| 3 | `POST /api/users/0/items/<附件Key>/file`，body `upload=<uploadKey>` | 登记后归档到 `storage/<附件Key>/`，`204` |

改动：

- 新增 `api_attach_pdf(parent_key, pdf_path, data_dir)`：完整封装四步，任一步失败**抛异常**而非静默；
- 新增 `_md5_file()`（分块算 MD5，大 PDF 不占内存）、`_upload_target()`、`_upload_bytes()`、
  `_upload_register()`；新增 `import hashlib, urllib.parse`；
- 新增异常类型 `AuthRequired(RuntimeError)`：把「需要人工授权/开关未开」这类**重试无用**的失败
  与网络抖动区分开。批量入库时首次命中即把**本批余下条目整体转 RIS**，不再对每条都尝试授权
  （否则会连弹多次窗）；
- 抽出 `api_key_refresh()` 与 `_write_headers()`；条目创建与附件上传两处遇 401/403 都只刷新一次 Key；
- **入库结果从 3 种扩到 5 种状态**，逐条如实打印：
  `api`（条目+PDF 都成功）/ `api_nopdf`（条目成功但该文献**无开放获取全文**）/
  `api+pdf_fail`（条目成功但 PDF 上传失败）/ `staged`（RIS 兜底）/ `skip`（馆藏已有）；
- 检索时没下 PDF 的条目，入库会**补下一次**（有 `pdf_url` 才试），补不下来按「无全文」报；
- `_upload_target()` 对 **412 Precondition Failed** 给出可读解释（同名文件已存在或 md5 不符），
  不再裸抛 `HTTPError`；
- 顺带查清：**DELETE 还需 `If-Unmodified-Since-Version`**（取任意 GET 响应头的
  `Last-Modified-Version`），否则 `428`。脚本本身不做删除（红线所在），仅记入文档备查。

行为层（`SKILL.md`）：

- 「一、文献查找」第 5 步重写：明确四种入库状态**不得混为一谈**，特别写明
  「不得把只建了条目说成已入库全文」「不得因 PDF 失败就把已建好的条目说成失败」；
- 降级路径表新增「条目建好了但 PDF 上传失败」一行；
- 「五、红线与边界」第 1 条补一句澄清：**新建条目与上传附件走的是 Zotero 自己的 HTTP 服务，
  不属于直写 sqlite**，从规则上消除「能不能写」的歧义；
- 「交付前自查」第 4 条扩写，把四种状态与「不得谎报全文」写进检查项；
- frontmatter `description` 新增触发词「下载全文」「下载 pdf」，并补上「含全文 PDF」的能力描述。

验证：

- 离线验证集 **262 → 285** 断言（`test_zotero.py` 60 → 83），新增 23 条覆盖附件上传全部分支：
  附件条目字段、三步请求序列与头、上传字节与源文件一致、MD5 分块计算一致性、
  412 可读报错、PDF 不存在提前拒绝、无 Server-ID / 授权被拒时抛 `AuthRequired` 且不重试。
  测试用**假 API 替身**离线跑，并连带替换 `urllib.request.urlopen`（否则 `_server_id()` 会真去连
  本机 23119，若 Zotero 恰在运行就会打到真实库——这是写测试时踩到的坑）；
- **真实 Zotero 端到端实测通过**：建条目 `<条目KEY>` → 附件条目 `<附件KEY>` → 三步上传 →
  文件落 `storage\<附件KEY>\probe_attachment.pdf`，**20,037 字节、MD5
  `ff918d7efe9191b30f81fa3438b7aa40` 与源文件逐字节一致** → `zotero_query.py --key <条目KEY>`
  回读确认附件路径正确。探针条目已全部删除（进回收站，可恢复）；
- 同时实测确认「无 pdf_url 条目」会走 `api_nopdf` 分支并给出正确提示文案。

文档：

- `references/zotero.md`：新增「PDF 附件上传（本地 API，三步协议）」整节（含实测记录）；
  删掉「PDF 附件自动上传暂未实现」的旧表述；补「DELETE 的版本号保护」；
  修正 `storage:` 前缀那段的旧结论（原写「20 条附件本地文件全部缺失」，
  复查发现**多数已就位**，改为提示逐条判断、不要沿用旧快照）；
- `SKILL功能说明.md`、`使用手册-零基础上手.md`：入库路径描述从「PDF 落 skill-import 需手拖」
  改为「PDF 自动挂为附件，可直接阅读」。

## 1.2.0

打通 Zotero 本地 API 的**写入**路径（此前只写文档说「待实测」，实际一直失败并静默降级为 RIS）。

根因（实测定位）：Zotero 7 的本地 API 对写请求有三重保护，缺一即拒：

1. 需在设置→高级开启「允许其他应用通信」——否则读都不通；
2. 写请求必须带 `Zotero-Server-ID` 头，否则 `428 Precondition Required`
   （`Zotero-Server-ID not provided`）；
3. 首次写入需先 `POST /api/local/authorize` 换 API Key，否则
   `401 API key required`。该请求**会在 Zotero 界面弹窗要求用户点「允许」**。

改动：

- `api_create()` 补 `Zotero-Server-ID` + `Authorization: Bearer <key>` 头；
- 新增 `_server_id()`（带缓存）、`_api_key()`、`request_key()`，Key 缓存在
  `<数据目录>/skill-import/.zotero_api_key`，失效（401）时自动清缓存重申请一次；
- 新增 `api_writable()`，把「能读」与「能写」分开探测，避免把只读当作可写；
- 新增 CLI 子命令 `--authorize`，供用户单独完成授权；
- 授权提示语先打印并 flush，修正 stdout/stderr 缓冲导致的提示后置问题；
- 改 `使用手册-零基础上手.md` 与 `QC报告-aviation-literature-v1.1.1.md`、`SKILL功能说明.md`、`references/zotero.md`
  中「本地 API 写入：⚠️ 待实测 / 未验证」的表述。

行为层：`SKILL.md` 降级路径表新增一行「本地 API 可读但写入被拒」，明确不得谎称已入库、
不得反复重试，并给出 `--authorize` 的处置方式。触发词未改动。

验证：验证集 262/262 通过（未破坏既有行为）；真实 Zotero 上建条目成功返回 Key（`8LDK5IVL`，
已手动删除）。

## 1.1.1

行为层补规则（来自边界用例审计）：新增「五、红线与边界」8 条硬约束，把原先只写在
`references/zotero.md` 里的「绝不直写 zotero.sqlite」内联进 SKILL.md 指令层；补「只给 DOI 时
用 Crossref 核验、不许猜测补全字段」；补「简单问题直接答、不必凑满四功能流程」。
「交付前自查」由 6 条扩到 8 条。触发词未改动，脚本接口未变动。

## 1.1.0

质量重构（大厂标准 Step 0–6）：

- frontmatter 补齐必填项 `description_zh` / `description_en` / `version` / `author`，
  建议项 `name` / `display_name` / `display_name_en` / `category` / `allowed-tools`。
- 修复幽灵引用（`scripts/xxx.py` 不存在）：改为「命令中出现的脚本都相对本 skill 的 `scripts/` 目录」。
- 新增「退出码约定」（0/1/2）与「依赖不可用时的降级路径」表，明确不得静默失败。
- 内联模板抽到 `templates/`（`literature-index.md`、`history-entry.md`），正文改为引用。
- `search_papers.py`：解析层抽为纯函数（可离线测试）；新增 `--source all` 跨源去重；
  丢弃无标题空壳条目；错误码收敛为 0/1/2，不再裸露 traceback。
- `zotero_query.py`：只读副本改用 `open_ro_copy()` 上下文管理器（独立临时目录 + 退出清理）；
  **修复作者名笛卡尔积重复拼接的 SQL bug**（原 `GROUP_CONCAT` JOIN 会让作者名重复多次）。
- `zotero_save.py`：适配新副本接口；批量 JSON 读取支持 UTF-8 BOM；坏输入受控非零退出。
- 新增 `test/` 离线验证集（4 套件 / 262 断言，夹具现场合成，不联网、不碰真实库）。

## 1.0.0

初版：四功能（文献查找 / 知识问答 / 历史对话存储 / 研究进展指导）+ 三脚本 + 两份 references。
