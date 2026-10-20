# 文献总索引 · 表格骨架

`文献库/文献索引.md` 使用下面这张表。新条目**追加到表尾**，不重排既有行。

```markdown
# 文献总索引

> 本文件由 aviation-literature skill 追加维护，每次入库后更新。

| 编号 | 标题 | 作者 | 年份 | 来源 | DOI/ID | Zotero Key | PDF 路径 | 研究阶段 | 推荐理由 |
|---|---|---|---|---|---|---|---|---|---|
| L001 | Automated Text-to-SWRL Rule Generation for Tolerance Specification Knowledge Graphs with LLM and RAG | Huang Z., Luo J. | 2026 | Procedia CIRP | 10.1016/j.procir.2026.03.135 | （API 建立后回填） | skill-import/2026_Huang_….pdf | 工程应用 | LLM+RAG 生成容差规则，直接对应容差标注审查场景 |
```

## 字段约定

| 字段 | 填写要求 |
|---|---|
| 编号 | `L001` 起顺序递增，与 `文献库/batch.json` 里的 `index` 不必一致，以本表为准 |
| 标题 | 原样保留，不翻译、不改写 |
| 作者 | 最多 3 位，超出写 `et al.` |
| 年份 | 四位数字；无法确认写「待核实」，**不许猜** |
| 来源 | 期刊或会议名；预印本写 `arXiv` |
| DOI/ID | 优先 DOI；无 DOI 时写 OpenAlex ID 或 arXiv ID |
| Zotero Key | 走本地 API 入库的填返回的 Key；走 RIS 导入的写「待导入」 |
| PDF 路径 | 相对工作区的路径；未获取到写「—」 |
| 研究阶段 | 四阶段之一：本体构建 / 知识图谱 / RAG 增强 / 工程应用 |
| 推荐理由 | 一句话，说清与研究方向的关系，不写「很相关」这类空话 |
