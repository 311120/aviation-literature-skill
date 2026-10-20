# 研究路线与检索关键词

用户研究方向分四个阶段，检索时先定位阶段，再从下表选取/组合关键词。

## 技术栈（用户已指定，检索与问答都要考虑）

| 环节 | 工具 | 说明 |
|---|---|---|
| 本体建模 | **Protégé** | 斯坦福本体编辑器，产出 OWL 本体文件。相关检索词：Protégé、OWL、RDF、SPARQL |
| 知识图谱存储与可视化 | **HugeGraph** | Apache 图数据库，配 HugeGraph-Studio 做可视化。相关检索词：HugeGraph、Apache HugeGraph、graph database、Gremlin |

涉及这两个工具的建模方法、工程实践、工具对比类文献同样在用户的研究范围内。

## 阶段 1：航空领域本体构建

构建航空制造领域的本体（ontology），作为后续知识图谱的 schema 基础。**用户使用 Protégé 建模。**

- 中文：航空领域本体、航空制造本体、工艺知识本体、本体构建方法、领域本体建模、Protégé 本体建模
- 英文：aerospace manufacturing ontology, aviation domain ontology, ontology engineering, Ontology Web Language (OWL), domain-specific ontology construction, knowledge modeling for manufacturing, Protégé ontology modeling, OWL/RDF/SPARQL
- 关注期刊/会议：Journal of Manufacturing Systems, Advanced Engineering Informatics, Computers in Industry, OWL/PROTEGE 相关文献

## 阶段 2：知识图谱构建

依据本体抽取实体关系，构建航空工艺/制造知识图谱。**用户用 HugeGraph 做图谱存储与可视化。**

- 中文：工艺知识图谱、航空知识图谱、实体抽取、关系抽取、知识图谱构建、HugeGraph、图数据库
- 英文：knowledge graph construction, manufacturing knowledge graph, process knowledge graph, named entity recognition industrial, relation extraction domain-specific, Apache HugeGraph, graph database, Gremlin

## 阶段 3：RAG 增强大模型

基于知识图谱与文献库构建检索增强生成（RAG）系统。

- 中文：检索增强生成、大模型知识问答、知识图谱增强大模型
- 英文：retrieval-augmented generation, GraphRAG, knowledge graph RAG, domain-adaptive LLM, RAG for industrial/manufacturing, LLM question answering domain knowledge

## 阶段 4：航空工程问题求解

用上述系统解决具体工程问题。

- 中文：工艺审查、工艺文件审查、容差标注、尺寸公差审查、GD&T、智能工艺设计
- 英文：process plan review, process specification review, tolerance annotation, tolerance checking, GD&T (geometric dimensioning and tolerancing), computer-aided tolerancing, intelligent process planning, LLM process planning aerospace

## 中文同义词对照（检索时逐个试）

同一概念在中文文献里常有多种叫法，**一个词搜不到不代表没有文献**，同一个词在不同时期的命中情况也会变，所以按此表**多试几组**，不要凭一次结果断定「没有文献」：

| 概念 | 常见同义写法 |
|---|---|
| 容差 | 公差、尺寸公差、几何公差、偏差 |
| 本体 | 领域本体、知识模型、知识本体 |
| 工艺审查 | 工艺评审、工艺文件审核、工艺合规检查 |
| 知识图谱 | KG、知识网络、知识库 |
| 大语言模型 | 大模型、LLM、预训练语言模型 |
| 检索增强生成 | RAG、检索增强、知识增强 |
| 实体抽取 | 命名实体识别、NER、信息抽取 |
| 工艺 | 制造工艺、加工工艺、工艺规程 |
| 本体建模工具 | Protégé、OWL 编辑器、本体编辑器 |
| 图谱存储/可视化 | HugeGraph、Neo4j、图数据库、GraphDB |

**关于工具的检索策略（经实测修订）**：HugeGraph 的学术文献数量明显少于 Neo4j，但并非没有——实测搜 `HugeGraph` 能找到直接相关的文献（见下节）。`Protege ontology` 这类词会返回工具方法学经典（Noy 等，2001 年起），做具体课题时需与领域词组合。所以查「工具怎么用 / 怎么落地」时两条腿走路：**用工具名搜直接文献**，同时**用主流工具名（Neo4j、OWL）搜可迁移的方法类文献**。向用户呈现时说明这层区别——哪篇是直接针对该工具的、哪些结论需要迁移。

## 已验证的有效检索词（实测命中）

以下英文检索词经 OpenAlex 实测能命中研究方向内的真实文献，可直接复用或组合：

- `tolerance specification knowledge graph` — 命中「Automated Text-to-SWRL Rule Generation for Tolerance Specification Knowledge Graphs with LLM and RAG」(Procedia CIRP 2026)、「Knowledge graph–enabled tolerancing experience acquisition and reuse for tolerance specification」(IJAMT 2023)
- `aviation manufacturing knowledge graph ontology` — 命中「The Construction of Knowledge Graphs in the Aviation Assembly Domain Based on a Joint Knowledge Extraction Model」(IEEE Access 2023)、「Named Entity Recognition in Aviation Products Domain Based on BERT」(IEEE Access 2024)、「Construction and Application of Knowledge Graph for Aviation Equipment Manufacturing Process」(WCMEIM 2025)
- `HugeGraph` — 命中「Transforming RDF to Property Graph in Hugegraph」(2020)、「Differential Optimization Testing of Gremlin-Based Graph Database Systems」(ICST 2024)、「Method of Domain Knowledge Graph Construction Based on Property Graph Model」(2022)、「Flight test domain knowledge graph construction and application」(2023)。**其中「Transforming RDF to Property Graph in Hugegraph」正卡在你的技术栈衔接点上**（Protégé 产出 OWL/RDF → HugeGraph 用属性图），建议优先读
- `Protege ontology` — 命中 Protégé 工具方法学经典：Noy 等「Creating Semantic Web contents with Protege-2000」(IEEE Intelligent Systems 2001)、「Web-Protege: A Lightweight OWL Ontology Editor for the Web」(2008)。返回偏工具经典，做具体课题时把工具名与领域词组合（如 `Protege aviation ontology modeling`）

**检索词经验**：把 2–3 个领域术语叠起来（对象 + 方法 + 任务）效果最好；单个宽泛词（`review`、`analysis`、`method`）会把结果带到医学、生物等无关领域。

## 全文获取路径（按可得性分级，优先免费）

脚本给每条文献标一个可得性标签，含义与对应的获取动作见下表。**对学生而言「能不能真的拿到全文」比「相关性多高」更关键**，所以路径按免费程度排序：

| 标签 | 是什么 | 获取路径 | 能否自动 |
|---|---|---|---|
| `OA` | 公开开放获取 | 直接点 PDF 直链；入库时 `zotero_save.py` 自动下载挂附件 | ✅ 全自动 |
| `CNKI` | 知网/万方/维普等中文库 | 见下面「中文库检索路径」 | ❌ 需浏览器插件 |
| `SUB` | 出版商页面，需机构订阅 | 见下面「图书馆订阅路径」 | ❌ 需校内网络 |
| `?` | 无法判定 | 用标题到图书馆统一检索里搜一次 | ❌ |

### 中文库检索路径（知网 / 万方 / 维普）

**脚本无法自动检索中文库**——知网、万方、维普都没有公开 API，且有反爬与登录限制。按以下路径人工操作：

1. **检索式构造**：用「中文同义词对照」表里的一组词，按「对象 + 方法 + 任务」组合。例：
   - `飞机装配 AND 容差 AND 知识图谱`
   - `公差标注 AND 本体 AND 语义`
   - `工艺审查 AND 大模型`
   - 一组的检索词搜不到就换同义词，**别因为一个词为空就判定「没有中文文献」**。（2026-10-08 曾实测「容差」为空；2026-10-12 复查「容差」已能命中，但结果混入政策/公示类文本，需人工剔除——**经验性事实要带观测日期，别写死成规律**。）
2. **走图书馆统一检索更好**：西工大图书馆主页的「统一检索 / 资源发现」可以一次跨库搜知网、万方、Web of Science 等，且**直接带学校的订阅权限**，比单独进知网多覆盖一层订阅资源。检索后能直接下载的多数是本校已订阅的。
3. **拿到 PDF 后入库**：在浏览器里打开论文页面（确保已登录学校账号），点 **Zotero 浏览器插件图标** → 选择目标分类保存。插件带登录会话，这是知网全文唯一可靠的自动化入口；命令行做不到（`zotero_grab.py` 会识别知网链接并明确提示改用插件）。
4. **只拿到题录时如实标注**「仅题录，未见全文」，不要当作已获取全文。

### 图书馆订阅路径（`SUB` 类）

有 DOI 但无开放获取标识的文献，多数是出版商页面的付费内容。学校图书馆通常订阅了主流出版商（Elsevier、Springer、IEEE、Wiley 等），获取方式：

1. **校内网络**：在校园网 IP 范围内，直接点 DOI 链接（`https://doi.org/<DOI>`）通常能自动通过机构授权下载；
2. **校外**：走学校 VPN 或图书馆的 CARSI/代理访问（西工大图书馆主页有校外访问入口），登录后按 DOI 打开即可；
3. **图书馆没订阅时**：用图书馆的**文献传递 / 馆际互借**服务申请，或用标题到「统一检索」搜一次（有时同一篇有多个来源，其中一个是本校订阅的）；
4. **红线**：绝不用盗版镜像站（如 Sci-Hub）获取，也不伪造机构会话。拿不到就如实说「需自行获取全文」。

### 优先级建议

做毕设时建议按此顺序投入精力：**先拿 `OA` 的**（零成本、可全自动入库）→ 再看 `CNKI`（中文文献对国内课题的工程背景理解很有价值，且学校基本都订阅）→ 最后处理 `SUB`（成本最高，只在确实关键时走文献传递）。

