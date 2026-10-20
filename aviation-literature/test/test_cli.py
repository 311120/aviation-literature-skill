#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 层用例：参数校验、退出码、文件产出的端到端行为。

不联网：通过替换模块内的 http_get 注入手写夹具载荷，因此走的是真实代码路径
（main → search_* → parse_* → 渲染 → 落盘），但全程零网络、结果确定。
"""
import contextlib
import io
import json
import os
import tempfile

from harness import Checker, capture, load_json, load_text, make_temp_dir, quiet, run_main


class _FakeHTTP:
    """按 URL 特征分派夹具载荷的 http_get 替身。"""

    def __init__(self, mapping, fail_on=()):
        self.mapping = mapping
        self.fail_on = fail_on
        self.calls = []

    def __call__(self, url, timeout=30):
        self.calls.append(url)
        for key in self.fail_on:
            if key in url:
                raise OSError("simulated network failure")
        for key, payload in self.mapping.items():
            if key in url:
                return payload if isinstance(payload, bytes) else payload.encode("utf-8")
        raise OSError("unmapped url in fixture")


def run():
    import search_papers as sp

    ck = Checker("test_cli")
    tmp = make_temp_dir(prefix="avlit_cli_")

    def call(argv, quiet_io=True):
        if quiet_io:
            with quiet():
                return sp.main(argv)
        return sp.main(argv)

    mapping = {
        "api.openalex.org": json.dumps(load_json("openalex.json")),
        "api.crossref.org": json.dumps(load_json("crossref.json")),
        "export.arxiv.org": load_text("arxiv.xml"),
        "api.semanticscholar.org": json.dumps(load_json("s2.json")),
    }

    def use(mapping_override=None, fail_on=()):
        fake = _FakeHTTP(mapping_override or mapping, fail_on)
        sp.http_get = fake
        return fake

    # ---------- 参数校验：坏输入必须非零退出，且不触网 ----------
    fake = use()
    ck.eq(call(["   "]), 1, "空检索词（纯空白）返回 1")
    ck.eq(call(["x", "--max", "0"]), 1, "--max 为 0 返回 1")
    ck.eq(call(["x", "--max", "-5"]), 1, "--max 为负数返回 1")
    ck.eq(len(fake.calls), 0, "参数非法时不发起任何网络请求")

    # ---------- 各单一来源端到端 ----------
    for src, expect_n in (("openalex", 4), ("crossref", 2), ("arxiv", 1), ("s2", 1)):
        use()
        out_md = os.path.join(tmp, f"{src}.md")
        ck.eq(call(["tolerance specification", "--source", src, "--out", out_md]), 0,
              f"单源 {src} 正常完成返回 0")
        ck.check(os.path.isfile(out_md), f"单源 {src} 生成 Markdown 文件")
        if os.path.isfile(out_md):
            with open(out_md, encoding="utf-8") as f:
                ck.eq(f.read().count("\n## "), expect_n, f"单源 {src} 产出 {expect_n} 条文献")

    # ---------- 四源合并 ----------
    use()
    out_all = os.path.join(tmp, "all.md")
    ck.eq(call(["x", "--source", "all", "--out", out_all]), 0, "--source all 返回 0")
    with open(out_all, encoding="utf-8") as f:
        ck.eq(f.read().count("\n## "), 8, "四源合计 8 条（各源夹具 4+2+1+1）")

    # ---------- 跨源去重：让 arXiv 返回与 OpenAlex 同标题的条目 ----------
    dup_arxiv = load_text("arxiv.xml").replace(
        "Graph RAG for Manufacturing Knowledge",
        "Knowledge Graph Enabled Tolerance Specification")
    use({**mapping, "export.arxiv.org": dup_arxiv})
    out_dedup = os.path.join(tmp, "dedup.md")
    call(["x", "--source", "all", "--out", out_dedup])
    with open(out_dedup, encoding="utf-8") as f:
        ck.eq(f.read().count("\n## "), 7, "跨源同标题条目被去重（8 -> 7）")

    # ---------- JSON 导出 ----------
    use()
    out_json = os.path.join(tmp, "batch.json")
    ck.eq(call(["x", "--source", "openalex", "--json", out_json]), 0, "--json 导出返回 0")
    with open(out_json, encoding="utf-8") as f:
        payload = json.load(f)
    ck.eq(len(payload), 4, "JSON 导出条目数正确")
    for k in ("index", "title", "authors", "year", "venue", "id", "doi",
              "link", "pdf", "abstract", "access", "pdf_url", "local_pdf"):
        ck.check(k in payload[0], f"JSON 条目含字段 {k}")
    ck.eq([p["index"] for p in payload], [1, 2, 3, 4], "JSON index 从 1 连续编号")
    ck.check(all(p["access"] in ("OA", "SUB", "CNKI", "?") for p in payload),
             "JSON 每条都带合法的可得性分级")

    # ---------- RIS 导出 ----------
    out_ris = os.path.join(tmp, "batch.ris")
    call(["x", "--source", "openalex", "--ris", out_ris])
    with open(out_ris, encoding="utf-8") as f:
        ris = f.read()
    ck.eq(ris.count("TY  - JOUR"), 4, "RIS 题录条数与结果一致")
    ck.eq(ris.count("ER  - "), 4, "RIS 每条有结束标记 ER")
    ck.check(ris.endswith("\n"), "RIS 文件以换行结尾")

    # ---------- 可得性优先排序（默认开启） ----------
    use()
    out_sorted = os.path.join(tmp, "sorted.md")
    ck.eq(call(["tolerance", "--source", "openalex", "--out", out_sorted]), 0,
          "默认排序模式返回 0")
    with open(out_sorted, encoding="utf-8") as f:
        md_sorted = f.read()
    pos_oa = md_sorted.find("[OA]")
    pos_sub = md_sorted.find("[SUB]")
    ck.check(pos_oa != -1 and pos_sub != -1, "默认排序：清单里同时出现 OA 与 SUB 标签")
    ck.check(pos_oa < pos_sub, "默认排序：免费条目 [OA] 排在需订阅 [SUB] 之前")
    ck.contains(md_sorted, "条可免费获取", "清单顶部给出可免费获取的条数统计")

    # --no-prefer-free 关闭排序后恢复原始顺序（夹具第 1、3、4 条为 OA/SUB/CNKI，
    # 原始顺序与可得性优先顺序不同，故两份清单的条目顺序应有差异）
    out_raw = os.path.join(tmp, "raw.md")
    call(["tolerance", "--source", "openalex", "--no-prefer-free", "--out", out_raw])
    with open(out_raw, encoding="utf-8") as f:
        md_raw = f.read()
    order_sorted = [l for l in md_sorted.splitlines() if l.startswith("## ")]
    order_raw = [l for l in md_raw.splitlines() if l.startswith("## ")]
    ck.check(len(order_sorted) == len(order_raw) == 4,
             "关闭优先排序后条目数不变（只换序不过滤）")
    ck.check(order_sorted != order_raw,
             "关闭优先排序后条目顺序与可得性优先顺序不同")
    ck.not_contains(md_raw, "本地文件", "关闭优先排序不影响清单其余内容")

    # ---------- --only-free 只保留可免费获取的条目 ----------
    use()
    out_only = os.path.join(tmp, "onlyfree.md")
    ck.eq(call(["tolerance", "--source", "openalex", "--only-free", "--out", out_only]), 0,
          "--only-free 返回 0")
    with open(out_only, encoding="utf-8") as f:
        md_only = f.read()
    ck.eq(md_only.count("\n## "), 2, "--only-free 只剩 OA + CNKI 共 2 条")
    ck.not_contains(md_only, "[SUB]", "--only-free 滤掉了需订阅的条目")
    ck.contains(md_only, "[OA]", "--only-free 保留公开开放获取条目")
    ck.contains(md_only, "[CNKI]", "--only-free 保留中文库条目")

    # 全部需订阅时 only-free 结果为空，但不得悄悄回退成全部
    use({**mapping, "api.openalex.org": json.dumps({
        "results": [{"id": "https://openalex.org/W9", "doi": "https://doi.org/10.1/only-sub",
                     "display_name": "A Paywalled Paper", "publication_year": 2020,
                     "authorships": [], "primary_location": {"source": {"display_name": "J"}},
                     "best_oa_location": None, "is_oa": False}]})})
    out_empty = os.path.join(tmp, "onlyfree_empty.md")
    ck.eq(call(["x", "--source", "openalex", "--only-free", "--out", out_empty]), 0,
          "--only-free 无免费条目时仍返回 0")
    with open(out_empty, encoding="utf-8") as f:
        md_empty = f.read()
    ck.not_contains(md_empty, "\n## ", "--only-free 无免费条目时清单为空（不回退成全量）")

    # ---------- 输出路径父目录不存在时自动创建 ----------
    deep = os.path.join(tmp, "a", "b", "c", "out.json")
    call(["x", "--source", "openalex", "--json", deep])
    ck.check(os.path.isfile(deep), "输出路径的父目录不存在时自动创建")

    # ---------- 容错：全部来源失败 / 部分失败 ----------
    use(fail_on=("openalex", "crossref", "arxiv", "semanticscholar"))
    ck.eq(call(["x", "--source", "all"]), 0, "全部来源失败时不崩，返回 0（结果为空属正常）")

    use(fail_on=("crossref",))
    ck.eq(call(["x", "--source", "all"]), 0, "部分来源失败时整体仍返回 0")

    # ---------- 下载：非 PDF 响应一律不落盘 ----------
    use({**mapping, "example.org": "this is not a pdf"})
    dl = os.path.join(tmp, "pdf")
    out_md2 = os.path.join(tmp, "dl_fail.md")
    call(["x", "--source", "openalex", "--download", dl, "--out", out_md2])
    ck.eq(len(os.listdir(dl)) if os.path.isdir(dl) else 0, 0,
          "响应不是 PDF 时不落任何文件")
    with open(out_md2, encoding="utf-8") as f:
        md_fail = f.read()
    ck.check("下载被拒" in md_fail,
             "下载失败时如实写明原因（不是笼统的「未获取到开放获取 PDF」）")
    ck.not_contains(md_fail, "未获取到开放获取 PDF",
                    "有 pdf_url 但下载失败时，不得说成「本来就没有 PDF」")

    # ---------- 下载：合法 PDF 落盘且文件名合规 ----------
    use({**mapping, "example.org": b"%PDF-1.4\nfixture\n"})
    out_md3 = os.path.join(tmp, "dl_ok.md")
    call(["x", "--source", "openalex", "--download", dl, "--out", out_md3])
    files = os.listdir(dl) if os.path.isdir(dl) else []
    ck.eq(len(files), 1, "合法 PDF 响应落盘 1 个文件")
    if files:
        ck.check(files[0].endswith(".pdf"), "落盘文件扩展名为 .pdf")
        ck.check(files[0].startswith("2023_"), "落盘文件名以年份开头")

    # ---------- 无结果 ----------
    use({**mapping, "api.openalex.org": json.dumps({"results": []})})
    ck.eq(call(["x", "--source", "openalex"]), 0, "无结果时返回 0")

    # ---------- 导出写不进去时受控失败（不裸露 traceback）----------
    # 把 --ris 指向一个**目录**：open(...,"w") 抛 IsADirectoryError，
    # 早先这会以裸 traceback 结束，违反 SKILL.md 的退出码契约。
    use(mapping)
    ris_dir = os.path.join(tmp, "ris_is_a_dir")
    os.makedirs(ris_dir, exist_ok=True)
    with capture() as cap:
        code = sp.main(["x", "--source", "openalex", "--ris", ris_dir])
    ck.eq(code, 1, "--ris 写不进去时以受控失败退出（非 0）")
    ck.contains(cap.err, "RIS写入失败", "--ris 写入失败时打印受控错误说明")
    ck.not_contains(cap.err, "Traceback", "--ris 写入失败时不裸露 traceback")

    return ck.report()


if __name__ == "__main__":
    run_main(run)
