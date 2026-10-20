# Zotero 集成说明

skill 与 Zotero 的关系是**共享文献库**：读题录/附件/笔记/标注（zotero_query.py），新文献自动入库（zotero_save.py），全程不需要 Zotero Web API Key。

## 读取馆藏（scripts/zotero_query.py）

按优先级自动选择：

1. **本地 HTTP API（Zotero 7+，需 Zotero 正在运行）**：`http://localhost:23119/api/users/0/items`，只读、无需 Key，返回题录级数据。✅ **已实测通过**（2026-09-16 复查：读取与写入均可用，写入细节见下节）。注意本地 API 的索引可能滞后于库内实际状态，**分类列表要取「API ∪ sqlite」两个来源**才完整。Zotero 未运行时自动回退到 sqlite。
2. **sqlite 只读副本（Zotero 未运行时，或需要 --pdf/--notes/--key 时）**：定位 `zotero.sqlite`（优先读 `%APPDATA%\Zotero\Zotero\Profiles\*\prefs.js` 里的 `extensions.zotero.dataDir`，其次 `%USERPROFILE%\Zotero`），把数据库复制到临时目录后用标准库 sqlite3 查询——**绝不直接连原库**，Zotero 运行时原库处于锁定状态。**此路径已实测通过**（默认数据目录 `%USERPROFILE%\Zotero`）。

   关键定位规则：
   - PDF 附件的存储目录名是**附件自身**的 item key（`storage/<附件Key>/文件名.pdf`），不是父条目的 key。脚本用 `itemAttachments.parentItemID`（数字 itemID）匹配条目、再用附件自身 itemID 反查 key。
   - **笔记**在 `itemNotes` 表：子笔记挂 `parentItemID`，独立笔记（`parentItemID` 为空）以自身 `itemID` 成为条目。关键词检索同时匹配标题/作者/摘要/**笔记内容**（匹配前去 HTML 标签）。
   - **PDF 标注**在 `itemAnnotations` 表（Zotero 6+）：type（highlight/note/text）、text、comment、pageLabel，通过标注所属的附件条目关联到文献条目。`--key` 可导出某条目的全部笔记与标注。

常用命令：

```bash
python zotero_query.py "knowledge graph" --pdf --notes   # 搜馆藏（含笔记匹配），列 PDF 与笔记摘录
python zotero_query.py "" --limit 20                     # 列出最近 20 条馆藏
python zotero_query.py "公差" --notes                    # 中文检索（注意同义词，见 research-roadmap.md）
python zotero_query.py --key YZA4D3CK                    # 导出条目字段、笔记、PDF 标注
```

**关于 `storage:` 前缀**：如果 `--pdf` 输出的是 `storage:xxx.pdf` 而不是完整本地路径，说明 Zotero 数据库里有该附件记录，但 `storage/<附件Key>/` 下找不到对应文件（常见原因：附件存放在 Zotero 网盘未同步到本地、或被清理过）。此时把状态如实告诉用户，不要假定文件可用；需要全文时让用户在 Zotero 中同步/下载附件，或用该条目的 DOI 从 OpenAlex / Crossref 取开放获取版本。

> 本机实测：2026-09-16 复查时**大量条目的附件本地文件已就位**（如 `storage\<附件KEY>\Xie 等 - 2025 - ...HybirdRAG.pdf`）。早前「20 条附件全部缺失」是当时的快照，不是长期状态——判断时要**逐条看**，不要沿用旧结论。

## 自动入库（scripts/zotero_save.py）

输入是 `search_papers.py --json` 导出的结果文件。双路径自动择优，**绝不直写 zotero.sqlite**：

1. **本地 API 写入（Zotero 7+ 运行中）**：需三步同时就绪，缺一即被服务端拒绝（脚本会自动探测并降级，不会假装成功）：

   | 步骤 | 要求 | 不满足时的报错 |
   |---|---|---|
   | 1 | Zotero 设置→高级 勾选「允许其他应用与此电脑上的 Zotero 通信」（`extensions.zotero.httpServer.enabled`） | 连接失败，退回 sqlite 只读 |
   | 2 | 写请求带 **`Zotero-Server-ID`** 头（从任意 GET 响应的同名响应头取） | `428 Precondition Required`，响应体 `Zotero-Server-ID not provided` |
   | 3 | 首次写入前先 `POST /api/local/authorize` 换取 **API Key** | `401 API key required -- POST /api/local/authorize to obtain one` |

   **第 3 步会阻塞并在 Zotero 界面弹出授权窗口，需要用户点「允许」**（这是 Zotero 有意设计的防滥用环节，无法绕过）。

   ```bash
   python zotero_save.py --authorize     # 单独完成授权，会在 Zotero 弹窗
   ```

   换到的 Key 缓存在 `<Zotero数据目录>/skill-import/.zotero_api_key`，后续批次直接复用；
   若 Zotero 关闭了「记住」选项或重启，Key 会失效，脚本收到 401 后**自动清缓存并重新申请一次**。

   流程：sqlite 副本按 DOI/规范化标题查重 → `POST /api/users/0/items` 创建 journalArticle 条目
   → **接着把 PDF 全文作为附件上传**（见下）→ 输出新条目的 Zotero Key。
   ✅ **已实测通过**（建条目 + 附件上传 + 回读验证，见下节实测记录）。

2. **RIS 导入兜底（Zotero 未运行，或上面任一步不满足）**：PDF 与 `batch.ris` 写入
   `<Zotero数据目录>/skill-import/`，用户在 Zotero「文件→导入」一次完成（勾选去重）。

## PDF 附件上传（本地 API，三步协议，✅ 已实测）

用户对入库的要求是「不能只建条目，要连全文 PDF 一起下下来挂上」。协议如下，**三步缺一不可**：

| 步 | 请求 | 关键点 |
|---|---|---|
| 0 | `POST /api/users/0/items`，body `{"itemType":"attachment","linkMode":"imported_url","parentItem":"<父Key>","title":"<文件名>","contentType":"application/pdf"}` | 先建**附件条目**，拿到附件自身的 Key |
| 1 | `POST /api/users/0/items/<附件Key>/file`，body 为 form-urlencoded 的 `md5=&filename=&filesize=&mtime=0`，带 `If-None-Match: *` | **必须带 MD5**，否则 `400 MD5 hash not provided`；返回 `{url, uploadKey}` |
| 2 | `POST <步1返回的 url>`，body 为 PDF **原始字节**，`Content-Type: application/pdf` | 返回 `201` |
| 3 | `POST /api/users/0/items/<附件Key>/file`，body 为 `upload=<uploadKey>` | 登记后才真正归档到 `storage/<附件Key>/`，返回 `204` |

实测记录（2026-09-16，本机真实 Zotero）：

```
建条目   → item Key  <条目KEY>
建附件   → attach Key <附件KEY>
三步上传 → 落盘 %USERPROFILE%\Zotero\storage\<附件KEY>\probe_attachment.pdf
           20,037 字节，MD5 ff918d7efe9191b30f81fa3438b7aa40
           与源文件 MD5 完全一致（字节级校验通过）
回读验证 → zotero_query.py --key <条目KEY> 显示该 PDF 路径 ✅
```

脚本把三步上传封装成 `api_attach_pdf(parent_key, pdf_path, data_dir)`，失败时**抛出而非静默**，
调用方在结果里用独立状态 `api+pdf_fail` 如实报告「条目建好了但 PDF 没挂上」，
并保留 `skill-import/` 里的文件供用户手工拖拽——**绝不谎称已附加**。

三种入库结果要能区分清楚（都在 stdout 里逐条打印）：

| 状态 | 含义 |
|---|---|
| `api` | 条目 + PDF 全文都成功了 |
| `api_nopdf` | 条目建好了，但该文献**没有开放获取全文**（OpenAlex/Crossref 上无 PDF 链接） |
| `api+pdf_fail` | 条目建好了，PDF 上传被拒/中断，文件仍在 `skill-import/` |
| `staged` | 走 RIS 兜底路径，等用户「文件→导入」 |

### 顺带发现：DELETE 还有一层保护

删除条目时另需 `If-Unmodified-Since-Version: <库版本号>`，否则 `428 If-Unmodified-Since-Version not provided`。
版本号从任意 GET 的响应头 `Last-Modified-Version` 取。脚本本身**不做删除**（红线：不可逆操作先确认），
此条仅供手工/临时代码参考。

> ⚠️ **本地 API 的 DELETE 是硬删除，不进回收站**（2026-09-16 实测）。用 DELETE 端点删掉的条目在
> `deletedItems` 表与 `includeTrashed=1` 的结果里都查不到，只能从备份重建。若确实要让用户能恢复，
> 正确的做法是在 Zotero 界面里按 Delete（那才会进回收站），或改走「加 `deleted` 标记」的方式——
> 但标记删除属于写库，需谨慎评估。

## 抓取入库（scripts/zotero_grab.py）—— 与 save 的分工

`zotero_save.py` 写「已经到手」的条目（输入是 `search_papers.py --json` 导出的结果）；
`zotero_grab.py` 把**一个 URL 或 DOI** 交给 Zotero 自己去解析抓取。两者用的是**不同端口的不同服务**：

| | zotero_save.py | zotero_grab.py |
|---|---|---|
| 端口/端点 | `23119/api/...`（本地 API） | `23119/connector/...`（抓取器 Connector） |
| 鉴权 | 需 `Zotero-Server-ID` 头 + API Key（会弹窗授权） | **无需鉴权**，但需声明 `X-Zotero-Connector-API-Version: 3` |
| 输入 | 结构化条目（JSON） | 网页 URL / DOI |
| 谁解析元数据 | 我们给什么就是什么 | **Zotero 自己解析页面** |
| 全文 PDF | 由脚本下载后三步上传 | **Zotero 自己从页面抓**（能抓就抓） |

```bash
python zotero_grab.py --check                              # 先确认抓取器可用
python zotero_grab.py "https://arxiv.org/abs/2401.00001"   # 单个页面
python zotero_grab.py --doi 10.1000/oa-001                 # 按 DOI 抓
python zotero_grab.py --urls 文献库/待抓.txt                # 批量（每行一个）
```

### 能力边界（这是最关键的一条）

抓取器**带着浏览器插件的登录会话**工作时才能抓需登录的页面；**命令行没有会话**，因此：

| 来源 | 命令行能否抓全文 | 说明 |
|---|---|---|
| arXiv / bioRxiv 预印本 | ✅ 能 | 公开直链 |
| 开放获取期刊（DOAJ/PLOS/MDPI/Frontiers） | ✅ 能 | 公开直链 |
| 有公开 PDF 直链的任意页面 | ✅ 能 | — |
| **知网 / 万方 / 维普** | ❌ **不能** | 需登录 + 机构授权 + 反爬。脚本会识别链接并提示改用浏览器插件 |
| 学校订阅的出版商页面 | ❌ **不能** | 依赖校内 IP / VPN 授权 |

脚本对知网/万方/维普链接会**主动分流**：不提交给抓取器，单独列出并给出「用浏览器插件抓」的指引，
且明确标注「这是正常分流，不是失败」。**它绝不尝试绕过登录、付费墙或反爬，也不保存任何账号凭据。**

需要登录的全文，唯一可靠的自动化入口是**浏览器里的 Zotero 插件**——你已登录的会话在手，
点一下图标就能抓。命令行先解决「免费且公开」的那部分，剩下的交给插件。

### 实测记录（2026-09-16，本机真实 Zotero）

```
--check          → 「Zotero 抓取器可用（127.0.0.1:23119）」✅
知网链接分流     → 列出「[知网] https://kns.cnki.net/...」，未提交，返回 0 ✅
```

**验证状态（诚实标注）**：查重逻辑、`skill-import` 落盘、RIS 生成、本地 API **建条目**、
本地 API **PDF 附件上传**（三步协议 + 字节级校验）均已实测通过；
抓取器**连通性与分流逻辑**已实测（`--check` + 知网链接不提交）；
抓取器**实际抓取效果**取决于 Zotero 的抓取器库与目标页面，脚本不保证每个 URL 都能抓到全文。
RIS 导入是 GUI 操作，需人工完成，脚本无法替代。
验证集 **471/471** 覆盖了协议全部分支（用假连接器离线跑）。

