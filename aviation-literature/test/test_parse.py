#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析层用例：四个数据源的纯函数解析 + 去重 + 规范化 + RIS 渲染。

全部离线，用手写夹具复刻真实 API 载荷结构，不发任何网络请求。
"""
from harness import Checker, load_json, load_text, run_main


def run():
    import search_papers as sp

    ck = Checker("test_parse")

    # ---------- OpenAlex：正常 ----------
    got = sp.parse_openalex(load_json("openalex.json"))
    ck.eq(len(got), 4, "OpenAlex 正常载荷返回 4 条")
    p = got[0]
    ck.eq(p["title"], "Knowledge Graph Enabled Tolerance Specification", "OpenAlex 标题")
    ck.eq(p["doi"], "10.1000/oa-001", "OpenAlex DOI 去掉 https://doi.org/ 前缀")
    ck.eq(p["id"], "10.1000/oa-001", "OpenAlex id 回退用 DOI")
    ck.eq(p["year"], "2023", "OpenAlex 年份转字符串")
    ck.eq(p["venue"], "IJAMT", "OpenAlex 来源期刊")
    ck.eq(p["pdf"], "https://example.org/oa-001.pdf", "OpenAlex 取 best_oa_location 的 pdf_url")
    ck.eq(p["authors"], ["Jia Jia", "Yingzhong Zhang"], "OpenAlex 作者列表")
    ck.eq(p["abstract"], "Tolerance specification via knowledge graphs", "OpenAlex 倒排摘要还原且有序")
    ck.check("relevance" in p, "OpenAlex 保留 relevance 字段")
    ck.eq(p["access"], "OA", "OpenAlex：open_access.oa_status=gold 判为 OA（公开免费）")

    # 第二条：doi/year/作者全缺，必须降级为安全默认值而不是崩
    q = got[1]
    ck.eq(q["doi"], "", "OpenAlex 缺 DOI 时为空串")
    ck.eq(q["year"], "?", "OpenAlex 缺年份时为 ?")
    ck.eq(q["authors"], [], "OpenAlex 缺作者时为空列表")
    ck.eq(q["venue"], "OpenAlex", "OpenAlex 缺来源时回退为源名")
    ck.eq(q["abstract"], "", "OpenAlex 缺摘要索引时为空串")
    ck.eq(q["access"], "?", "OpenAlex：无 DOI 无 OA 标识时可得性降级为 ?")

    # 第三条：有 DOI 但 oa_status=closed -> 需机构订阅
    ck.eq(got[2]["access"], "SUB", "OpenAlex：有 DOI 且非 OA 判为 SUB（需机构订阅）")
    ck.eq(got[2]["pdf"], "", "OpenAlex：closed 条目无 PDF 链接")
    # 第四条：中文标题 -> 中文库
    ck.eq(got[3]["access"], "CNKI", "OpenAlex：中文标题判为 CNKI（中文库）")

    # ---------- OpenAlex：oa_status 各档位（对照真实响应结构） ----------
    # 真实 OpenAlex /works 响应**没有顶层 is_oa**，开放获取信息只在 open_access 子对象里；
    # 生产代码据此判断，夹具也按同一结构构造，避免"看着在测、实际测的是别的分支"。
    ck.check("is_oa" not in got[0], "夹具与真实响应一致：OpenAlex 载荷无顶层 is_oa")
    bronze = sp.parse_openalex(load_json("openalex_bronze.json"))[0]
    ck.eq(bronze["access"], "OA",
          "OpenAlex：oa_status=bronze 判为 OA（源站可免费读到，虽无开放许可）")
    ck.eq(bronze["pdf"], "https://example.org/bronze-001.pdf",
          "OpenAlex：bronze 档也保留 pdf 链接供下载")

    ck.eq(sp.parse_openalex(load_json("openalex_empty.json")), [], "OpenAlex 空结果返回空列表")
    ck.eq(sp.parse_openalex(None), [], "OpenAlex 载荷为 None 不崩且返回空")
    ck.eq(sp.parse_openalex("not-a-dict"), [], "OpenAlex 载荷为字符串不崩且返回空")
    ck.eq(len(sp.parse_openalex(load_json("openalex.json"), 1)), 1, "OpenAlex max_results 生效")

    # ---------- OpenAlex：畸形 ----------
    mal = sp.parse_openalex(load_json("openalex_malformed.json"))
    ck.eq(len(mal), 1, "OpenAlex 畸形载荷：非字典元素与无标题元素被丢弃")
    ck.eq(mal[0]["title"], "Valid After Garbage", "OpenAlex 畸形载荷：坏元素之后的正常元素仍被解析")
    ck.eq(mal[0]["abstract"], "a b b c", "OpenAlex 畸形载荷：摘要索引按位置排序")
    ck.eq(mal[0]["abstract"], sp.rebuild_abstract({"b": [1, 0], "a": [0], "c": [2]}),
          "OpenAlex rebuild_abstract 可复现")

    # ---------- Crossref ----------
    cr = sp.parse_crossref(load_json("crossref.json"))
    ck.eq(len(cr), 2, "Crossref 空标题条目被丢弃（保留 2 条有效）")
    ck.eq(cr[0]["title"], "Ontology Based Process Review for Aerospace", "Crossref 标题取数组首项")
    ck.eq(cr[0]["authors"], ["Noy Natalya"], "Crossref 作者拼 姓+名")
    ck.eq(cr[0]["year"], "2001", "Crossref 年份取 date-parts")
    ck.eq(cr[0]["link"], "https://doi.org/10.1000/cr-001", "Crossref 链接由 DOI 合成")
    ck.eq(cr[0]["pdf"], "https://example.org/cr-001.pdf", "Crossref：CC 授权条目取其 pdf 链接")
    ck.eq(cr[0]["access"], "OA", "Crossref：license 为 CC-BY 时判 OA")
    # 回归：出版商 TDM 端点不是免费全文，不得据此判 OA（红线：不夸大可得性）
    ck.eq(cr[1]["access"], "SUB", "Crossref：只有 TDM 端点、无 CC 授权时判 SUB 而非 OA")
    ck.eq(cr[1]["pdf"], "", "Crossref：非开放获取时不填 pdf（避免误触发下载与挂附件）")
    ck.check(sp._crossref_is_oa(
        {"license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}]}),
        "Crossref：CC-BY 授权识别为开放获取")
    ck.check(not sp._crossref_is_oa(
        {"license": [{"URL": "https://www.springernature.com/gp/researchers/text-and-data-mining"}]}),
        "Crossref：出版商 TDM 条款不识别为开放获取")
    ck.check(not sp._crossref_is_oa({}), "Crossref：无 license 字段不识别为开放获取")
    ck.eq(sp.parse_crossref(load_json("crossref_empty.json")), [], "Crossref 空结果返回空列表")
    ck.eq(sp.parse_crossref(load_json("crossref_malformed.json")), [],
          "Crossref message 非字典时返回空列表")
    ck.eq(sp.parse_crossref(None), [], "Crossref 载荷为 None 不崩")

    # ---------- Crossref DOI 直查识别（红线：只给 DOI 时用它核验原字段）----------
    ck.eq(sp.doi_of("10.1007/s00170-023-12644-y"), "10.1007/s00170-023-12644-y",
          "doi_of：裸 DOI 被识别")
    ck.eq(sp.doi_of("https://doi.org/10.1000/xyz.1"), "10.1000/xyz.1",
          "doi_of：doi.org 链接被识别并规范化为裸 DOI")
    ck.eq(sp.doi_of("  http://dx.doi.org/10.1000/abc  "), "10.1000/abc",
          "doi_of：dx.doi.org 链接与首尾空白被处理")
    ck.eq(sp.doi_of("tolerance specification"), "", "doi_of：普通检索词不误判为 DOI")
    ck.eq(sp.doi_of("10.1000"), "", "doi_of：缺后缀的串不误判为 DOI")
    ck.eq(sp.doi_of(""), "", "doi_of：空串返回空")
    ck.eq(sp.doi_of(None), "", "doi_of：None 不崩")

    # ---------- arXiv ----------
    ax = sp.parse_arxiv(load_text("arxiv.xml"))
    ck.eq(len(ax), 1, "arXiv 缺 id 的 entry 被丢弃")
    ck.eq(ax[0]["title"], "Graph RAG for Manufacturing Knowledge", "arXiv 标题")
    ck.eq(ax[0]["id"], "2401.00001v1", "arXiv id 取链接末段")
    ck.eq(ax[0]["pdf"], "http://arxiv.org/pdf/2401.00001v1.pdf", "arXiv abs 链接改写为 pdf 链接")
    ck.eq(ax[0]["year"], "2024", "arXiv 取 published 年份")
    ck.eq(ax[0]["authors"], ["Alice Wu", "Bob Li"], "arXiv 作者列表")
    ck.eq(ax[0]["venue"], "arXiv", "arXiv 来源固定为源名")
    ck.eq(ax[0]["access"], "OA", "arXiv：预印本一律判为 OA（免费）")
    ck.eq(sp.parse_arxiv(load_text("arxiv_empty.xml")), [], "arXiv 空 feed 返回空列表")
    ck.eq(sp.parse_arxiv(""), [], "arXiv 空串不崩")
    ck.eq(sp.parse_arxiv(None), [], "arXiv 载荷为 None 不崩")

    # ---------- Semantic Scholar ----------
    s2 = sp.parse_s2(load_json("s2.json"))
    ck.eq(len(s2), 1, "S2 全空元素被丢弃")
    ck.eq(s2[0]["doi"], "10.1000/s2-001", "S2 DOI 取 externalIds")
    ck.eq(s2[0]["link"], "https://doi.org/10.1000/s2-001", "S2 有 DOI 时链接走 doi.org")
    ck.eq(s2[0]["pdf"], "https://example.org/s2-001.pdf", "S2 取 openAccessPdf")
    ck.eq(s2[0]["authors"], ["Cara Chen"], "S2 作者列表")
    ck.eq(s2[0]["access"], "OA", "S2：有 openAccessPdf 时判为 OA")
    ck.eq(sp.parse_s2(load_json("s2_empty.json")), [], "S2 空结果返回空列表")
    ck.eq(sp.parse_s2(load_json("s2_malformed.json")), [], "S2 data 非列表时返回空列表")
    ck.eq(sp.parse_s2(None), [], "S2 载荷为 None 不崩")

    # ---------- 去重 ----------
    a = {"title": "Same Paper", "doi": "10.1/x", "year": "2020"}
    b = {"title": "Same Paper", "doi": "10.1/X", "year": "2020"}     # DOI 大小写不同
    cc = {"title": "Same   Paper!!", "doi": "", "year": "2020"}      # 无 DOI，标题规范化后同名
    d = {"title": "Other Paper", "doi": "", "year": "2021"}
    out = sp.dedup([sp.normalize_paper(x) for x in (a, b, cc, d)])
    ck.eq(len(out), 2, "去重：DOI 大小写不敏感 + 无 DOI 时按规范化标题")
    ck.eq(out[0]["title"], "Same Paper", "去重后保留首次出现的条目")
    ck.eq(out[1]["title"], "Other Paper", "去重后顺序稳定")
    ck.eq(len(sp.dedup([])), 0, "去重：空列表返回空")

    # ---------- 全文可得性分级 ----------
    ra = sp.resolve_access
    ck.eq(ra(is_oa=True), "OA", "分级：is_oa 为真 -> OA")
    ck.eq(ra(has_pdf=True), "OA", "分级：拿到免费 PDF -> OA")
    ck.eq(ra(source="arxiv"), "OA", "分级：arXiv 来源 -> OA（预印本免费）")
    ck.eq(ra(doi="10.1/x"), "SUB", "分级：有 DOI 且非 OA -> SUB")
    ck.eq(ra(doi="10.1/x", title="飞机装配容差建模方法研究"), "CNKI",
          "分级：中文标题 -> CNKI（中文库）")
    ck.eq(ra(doi="10.1/x", venue="航空学报"), "CNKI", "分级：中文期刊名 -> CNKI")
    ck.eq(ra(), "?", "分级：无 DOI 无 OA -> ?（无法判定）")
    ck.eq(ra(is_oa=True, doi="10.1/x", title="中文标题"), "OA",
          "分级：OA 优先级高于中文库判定（先免费后收费）")
    ck.check(set(sp.ACCESS_LEVELS) == {"OA", "SUB", "CNKI", "?"},
             "ACCESS_LEVELS 恰为四个约定取值")
    for lv in sp.ACCESS_LEVELS:
        ck.check(lv in sp.ACCESS_RANK, f"ACCESS_RANK 含分级 {lv}")
        ck.check(lv in sp.ACCESS_LABEL, f"ACCESS_LABEL 含分级 {lv}")

    # 优先级：OA < CNKI < SUB < ?（数值越小越靠前）
    ck.check(sp.ACCESS_RANK["OA"] < sp.ACCESS_RANK["CNKI"] < sp.ACCESS_RANK["SUB"]
             < sp.ACCESS_RANK["?"], "分级优先顺序为 OA < CNKI < SUB < ?")

    # ---------- 可得性优先排序 ----------
    def mk(access, title):
        return sp.normalize_paper({"title": title, "access": access})

    ordered = sp.sort_by_access([mk("SUB", "s"), mk("OA", "o"),
                                 mk("?", "u"), mk("CNKI", "c")])
    ck.eq([x["access"] for x in ordered], ["OA", "CNKI", "SUB", "?"],
          "排序：免费可得的排前面（OA -> CNKI -> SUB -> ?）")
    ck.eq(len(sp.sort_by_access([mk("SUB", "a"), mk("OA", "b")])), 2,
          "排序：不丢弃任何条目（付费的仍保留）")
    same = [mk("OA", "x1"), mk("OA", "x2"), mk("OA", "x3")]
    ck.eq([x["title"] for x in sp.sort_by_access(same)], ["x1", "x2", "x3"],
          "排序：同级保持原有顺序（稳定排序）")
    ck.eq(sp.sort_by_access([]), [], "排序：空列表返回空")
    ck.eq(sp.sort_by_access([mk("??", "脏值")])[0]["access"], "?",
          "排序：非法分级值被规范化降级为 ?")

    # ---------- 获取方式提示 ----------
    oa_with_pdf = mk("OA", "t")
    oa_with_pdf["pdf"] = "https://x/y.pdf"
    ck.contains(sp.access_hint(oa_with_pdf), "可直接下载",
                "获取提示：OA 且有 PDF 时说明可直接下载")
    ck.contains(sp.access_hint(mk("SUB", "t")), "学校图书馆", "获取提示：SUB 指向学校图书馆")
    ck.contains(sp.access_hint(mk("CNKI", "t")), "知网", "获取提示：CNKI 指向知网/万方")
    ck.contains(sp.access_hint(mk("?", "t")), "图书馆统一检索",
                "获取提示：无法判定时建议用图书馆统一检索")

    # ---------- 规范化 ----------
    np_ = sp.normalize_paper({})
    for k in sp.PAPER_FIELDS:
        ck.check(k in np_, f"normalize_paper 补齐字段 {k}")
    ck.eq(np_["year"], "?", "normalize_paper 缺年份时为 ?")
    ck.eq(np_["authors"], [], "normalize_paper 缺作者时为空列表")
    ck.eq(sp.normalize_paper({"authors": "Solo"})["authors"], ["Solo"],
          "normalize_paper 把单个作者字符串包成列表")
    ck.eq(sp.normalize_paper({"year": 2024})["year"], "2024", "normalize_paper 年份数字转字符串")
    ck.eq(sp.normalize_paper({})["access"], "?", "normalize_paper 缺 access 时降级为 ?")
    ck.eq(sp.normalize_paper({"access": "OA"})["access"], "OA", "normalize_paper 保留合法 access")
    ck.eq(sp.normalize_paper({"access": "BOGUS"})["access"], "?",
          "normalize_paper 把非法的 access 值降级为 ?（不泄漏脏值）")

    # ---------- 摘要还原的边界 ----------
    ck.eq(sp.rebuild_abstract(None), "", "rebuild_abstract：None 返回空串")
    ck.eq(sp.rebuild_abstract({"w": "not-a-list"}), "", "rebuild_abstract：索引非列表时跳过")
    ck.eq(sp.rebuild_abstract({"w": ["x"]}), "", "rebuild_abstract：索引元素非整数时跳过")
    ck.eq(len(sp.rebuild_abstract({"w": list(range(500))})), 300, "rebuild_abstract：截断到 300 字符")

    # ---------- safe_name 与 RIS ----------
    ck.eq(sp.safe_name('a/b\\c:d*e?f"g<h>i|j'), "abcdefghij", "safe_name 过滤全部非法字符")
    ck.eq(sp.safe_name(None), "", "safe_name：None 返回空串")
    ck.eq(len(sp.safe_name("标题" * 200)), 400, "safe_name 不改变长度（截断交由调用方）")

    fixt = sp.normalize_paper({"title": "T", "authors": ["A B"], "year": "2020",
                               "doi": "10.1/z", "link": "https://x", "abstract": "AB"})
    ris = sp.to_ris_entry(fixt)
    for tag in ("TY  - JOUR", "TI  - T", "AU  - A B", "PY  - 2020",
                "DO  - 10.1/z", "UR  - https://x", "AB  - AB", "ER  - "):
        ck.contains(ris, tag, f"RIS 含字段 {tag}")
    ris_no_year = sp.to_ris_entry(sp.normalize_paper({"title": "T", "year": "?"}))
    ck.not_contains(ris_no_year, "PY  - ", "RIS 年份未知时不输出 PY 行")

    # ---------- Markdown 渲染 ----------
    md = sp.render_markdown("q", [fixt], {1: "/tmp/a.pdf"})
    ck.contains(md, "# 检索结果：q", "Markdown 含标题行")
    ck.contains(md, "本地文件：/tmp/a.pdf", "Markdown 含本地下载路径")
    ck.not_contains(sp.render_markdown("q", [fixt], {}), "本地文件",
                    "未下载时不输出本地文件行")

    # 可得性标签与获取指引必须出现在清单里
    md_oa = sp.render_markdown("q", [mk("OA", "Free Paper")], {})
    ck.contains(md_oa, "[OA]", "Markdown 输出可得性标签 [OA]")
    ck.contains(md_oa, "公开开放获取", "Markdown 说明 OA 的含义")
    ck.contains(md_oa, "获取方式：", "Markdown 输出获取方式行")
    md_sub = sp.render_markdown("q", [mk("SUB", "Paid Paper")], {})
    ck.contains(md_sub, "[SUB]", "Markdown 输出可得性标签 [SUB]")
    ck.contains(md_sub, "学校图书馆", "Markdown 对 SUB 给出校图书馆指引")
    md_cn = sp.render_markdown("q", [mk("CNKI", "中文论文")], {})
    ck.contains(md_cn, "[CNKI]", "Markdown 输出可得性标签 [CNKI]")
    ck.contains(md_cn, "知网", "Markdown 对 CNKI 给出知网指引")

    # 免费占比小标题：只在有免费条目时出现
    md_mix = sp.render_markdown("q", [mk("OA", "A"), mk("SUB", "B")], {})
    ck.contains(md_mix, "1/2 条可免费获取", "Markdown 统计可免费获取的条数")
    ck.not_contains(sp.render_markdown("q", [mk("SUB", "B")], {}), "可免费获取",
                    "全部需订阅时不输出免费占比小标题")

    return ck.report()


if __name__ == "__main__":
    run_main(run)
