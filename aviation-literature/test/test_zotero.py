#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zotero 集成用例：馆藏读取、附件定位、笔记/标注导出、查重与入库。

全程只操作夹具目录下合成的 zotero.sqlite，**绝不触碰真实 Zotero 库**：
  1) 把 APPDATA / USERPROFILE 指向夹具，屏蔽真实配置文件与用户目录；
  2) 断言解析出的数据目录确实位于夹具内，否则立即中止；
  3) 强制关闭本地 API 路径，只走离线 RIS 分支，避免写到真实 Zotero。
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import urllib.error

from harness import Checker, build_all, make_temp_dir, quiet, run_main


def run():
    import zotero_query as zq
    import zotero_save as zs

    ck = Checker("test_zotero")
    tmp = make_temp_dir(prefix="avlit_zotero_")
    build_all(tmp)

    # 隔离环境变量 + 关闭本地 API 路径（避免误写真实 Zotero 库）
    # 夹具库位于 <tmp>/zotero/Zotero/zotero.sqlite，故 USERPROFILE 指向 <tmp>/zotero
    os.environ["APPDATA"] = os.path.join(tmp, "nonexistent_appdata")
    os.environ["USERPROFILE"] = os.path.join(tmp, "zotero")
    zs.api_up = lambda *a, **k: False

    def zsmain(argv):
        with quiet():
            return zs.main(argv)

    data_dir = zq.find_data_dir()
    real_root = os.path.abspath(tmp)
    if not os.path.abspath(data_dir).startswith(real_root):
        print("  [中止] 数据目录指向夹具之外，为保护真实 Zotero 库停止执行")
        ck.check(False, "数据目录解析结果位于夹具内（安全闸门）")
        return ck.report()
    ck.check(True, "数据目录解析结果位于夹具内（安全闸门）")

    # ---------- 读取：条目筛选 ----------
    papers = zq.query_sqlite("", 50, data_dir)
    ck.eq(sorted(p["key"] for p in papers), ["AAAA1111", "BBBB2222", "DDDD4444"],
          "馆藏读取排除回收站条目与附件条目")
    by_key = {p["key"]: p for p in papers}
    a = by_key["AAAA1111"]
    ck.eq(a["title"], "Aviation Ontology Construction", "题录标题正确")
    ck.eq(a["year"], "2023", "题录年份取 date 前 4 位")
    ck.eq(a["authors"], ["Zhang San", "Li Si"], "题录作者按 orderIndex 保序且不重复")
    ck.eq(len(set(a["authors"])), len(a["authors"]),
          "回归：多字段条目的作者不被 JOIN 笛卡尔积重复拼接")
    ck.eq(a["publication"], "Journal of Manufacturing Systems", "题录出处正确")
    ck.eq(a["item_type"], "journalArticle", "题录类型正确")

    # ---------- 读取：笔记 ----------
    ck.eq(len(a["notes"]), 0, "未开 want_notes 时不读笔记")
    with_notes = {p["key"]: p for p in zq.query_sqlite("", 50, data_dir, want_notes=True)}
    ck.eq(len(with_notes["AAAA1111"]["notes"]), 1, "开 want_notes 后读到 1 条子笔记")
    ck.contains(with_notes["AAAA1111"]["notes"][0], "ontology reuse", "笔记内容可检索")
    ck.not_contains(with_notes["AAAA1111"]["notes"][0], "<p>", "笔记内容已去 HTML 标签")

    # ---------- 读取：独立笔记条目 ----------
    d = by_key["DDDD4444"]
    ck.eq(d["item_type"], "note", "独立笔记以自身条目出现")
    ck.contains(d["title"], "Standalone note", "独立笔记标题回退为笔记开头")

    # ---------- 读取：关键词命中四个维度 ----------
    ck.eq(len(zq.query_sqlite("Ontology", 50, data_dir)), 1, "关键词命中标题")
    ck.eq(len(zq.query_sqlite("Zhang", 50, data_dir)), 1, "关键词命中作者")
    ck.eq(len(zq.query_sqlite("reuse", 50, data_dir)), 1, "关键词命中摘要")
    ck.eq(len(zq.query_sqlite("Standalone", 50, data_dir)), 1, "关键词命中笔记内容")
    ck.eq(len(zq.query_sqlite("绝不存在的词", 50, data_dir)), 0, "无匹配时返回空列表")

    # 回归：多词必须按「分词 AND」匹配，不能退化成整串短语匹配。
    # 早先 sqlite 路径用 LIKE '%整串%'，导致 "Aviation assembly"（词分散在标题与摘要里）
    # 匹配不到；而 --pdf/--notes 会强制走 sqlite，查重环节就会静默漏检（后果是重复下载）。
    ck.eq(len(zq.query_sqlite("Aviation assembly", 50, data_dir)), 1,
          "多词查询：按分词 AND 命中（词可分散在不同字段）")
    ck.eq(len(zq.query_sqlite("Aviation aerospace", 50, data_dir)), 1,
          "多词查询：标题词 + 摘要词 组合命中")
    ck.eq(len(zq.query_sqlite("Aviation Ontology", 50, data_dir)), 1,
          "多词查询：同一条目内两词均命中")
    ck.eq(len(zq.query_sqlite("Aviation 绝不存在的词", 50, data_dir)), 0,
          "多词查询：任一词未命中即整条不命中（AND 语义）")
    ck.eq(len(zq.query_sqlite("aviation ASSEMBLY", 50, data_dir)), 1,
          "多词查询：大小写不敏感")
    # SQL 生成器契约
    sql3, prm3 = zq.build_sqlite_query("a b c")
    ck.eq(sorted(prm3), ["kw0", "kw1", "kw2"], "build_sqlite_query：3 个词生成 3 个绑定参数")
    ck.eq(sql3.count(":kw0"), 4,
          "build_sqlite_query：每个词覆盖 标题/作者/摘要/笔记 四类字段")
    sql1t, _ = zq.build_sqlite_query("a")
    ck.check(sql3.count(" AND ") > sql1t.count(" AND "),
             "build_sqlite_query：词数增加时 AND 条件随之增加")
    ck.eq(sql3.count(" OR EXISTS "), 9,
          "build_sqlite_query：3 个词各覆盖 作者/摘要/笔记 3 类子查询")
    sql0, prm0 = zq.build_sqlite_query("")
    ck.eq(prm0, {}, "build_sqlite_query：空关键词不生成绑定参数")
    ck.check("HAVING" not in sql0, "build_sqlite_query：空关键词不设 HAVING（列出全部）")
    sql1, prm1 = zq.build_sqlite_query("  graph   ")
    ck.eq(prm1, {"kw0": "%graph%"}, "build_sqlite_query：多余空白被折叠成单个词")
    ck.eq(zq.build_sqlite_query(None)[1], {}, "build_sqlite_query：None 不崩")

    # ---------- 读取：附件定位（核心坑位）----------
    ck.eq(a["pdf"], os.path.join(data_dir, "storage", "EEEE5555", "paper_ok.pdf"),
          "附件目录名用「附件自身 key」而非父条目 key")
    ck.check(os.path.isfile(a["pdf"]), "解析出的附件路径确实存在")
    ck.eq(by_key["BBBB2222"]["pdf"], "storage:missing.pdf",
          "附件文件缺失时保留 storage: 前缀（不谎报可用）")

    # ---------- 读取：单条目导出 ----------
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        found = zq.dump_key("AAAA1111", data_dir)
    exported = buf.getvalue()
    ck.eq(found, True, "dump_key 对存在的条目返回 True")
    ck.contains(exported, "Aviation Ontology Construction", "dump_key 导出标题")
    ck.contains(exported, "10.1000/aaa", "dump_key 导出 DOI")
    ck.contains(exported, "笔记（1 条）", "dump_key 统计笔记条数")
    ck.contains(exported, "tolerance is critical", "dump_key 导出 PDF 标注正文")
    ck.contains(exported, "高亮", "dump_key 标注类型译为中文")
    with contextlib.redirect_stdout(io.StringIO()):
        ck.eq(zq.dump_key("NOSUCHKEY", data_dir), False, "dump_key 对不存在的 Key 返回 False")
        ck.eq(zq.dump_key("CCCC3333", data_dir), False,
              "dump_key 对回收站中的条目返回 False")

    # ---------- 只读保证：不残留副本、不动原库 ----------
    before = _tree(data_dir)
    # 用**前后快照差集**判定"用后即清"，而不是绝对计数：
    # 受限沙箱可能让随机名目录删不掉，环境里本来就有残留时绝对计数会误报。
    tmp_before = _tmp_copy_names()
    for _ in range(3):
        zq.query_sqlite("", 5, data_dir)
    ck.eq(_tree(data_dir), before, "多次读取后数据目录内容完全未变（严格只读）")
    _report_tmp_leftovers(ck, tmp_before)

    with zq.open_ro_copy(data_dir) as c1:
        with zq.open_ro_copy(data_dir) as c2:
            n1 = c1.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            n2 = c2.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    ck.eq((n1, n2), (6, 6), "并发打开两个只读副本互不干扰")

    with zq.open_ro_copy(data_dir) as c:
        c.execute("DELETE FROM items")
        c.commit()
    ck.eq(len(zq.query_sqlite("", 50, data_dir)), 3, "对副本做写操作完全不影响原库")

    # ---------- 查重数据 ----------
    dois, titles = zs.load_existing(data_dir)
    ck.check("10.1000/aaa" in dois, "load_existing 收集 DOI（统一小写）")
    ck.check("10.1000/bbb" in dois, "load_existing 收集第二条 DOI")
    ck.check(zs.norm_title("Aviation Ontology Construction!") in titles,
             "load_existing 标题按规范化形式收集")
    ck.eq(zs.norm_title("A B-c!1"), "abc1", "norm_title 只保留字母数字与汉字")
    ck.eq(zs.norm_title(None), "", "norm_title：None 返回空串")
    ck.eq(zs.norm_title("容差 标注"), "容差标注", "norm_title 保留汉字并去空格")

    # ---------- 入库：编号筛选与查重 ----------
    batch = os.path.join(tmp, "payloads", "batch.json")
    ck.eq(zsmain(["--json", batch, "--items", "2,3"]), 0, "入库正常完成返回 0")

    import_dir = os.path.join(data_dir, "skill-import")
    ck.check(os.path.isdir(import_dir), "创建了 skill-import 暂存目录")
    ris_path = os.path.join(import_dir, "batch.ris")
    ck.check(os.path.isfile(ris_path), "生成了 batch.ris")
    with open(ris_path, encoding="utf-8") as f:
        ris1 = f.read()
    ck.not_contains(ris1, "Aviation Ontology Construction",
                    "馆藏已有的 DOI 条目被跳过，未写入 RIS")
    ck.contains(ris1, "Brand New Paper On HugeGraph", "馆藏没有的条目被写入 RIS")
    ck.eq(ris1.count("TY  - JOUR"), 1, "本次仅 1 条进入 RIS")

    # ---------- 入库：RIS 追加合并不丢历史 ----------
    ck.eq(zsmain(["--json", batch, "--items", "1"]), 0, "第二次入库返回 0")
    with open(ris_path, encoding="utf-8") as f:
        ris2 = f.read()
    ck.contains(ris2, "Brand New Paper On HugeGraph", "追加后上一批次题录仍在（不覆盖）")
    ck.contains(ris2, "Knowledge Graph Enabled Tolerance Specification", "新批次题录已加入")
    ck.eq(ris2.count("TY  - JOUR"), 2, "追加后共 2 条题录")

    zsmain(["--json", batch, "--items", "1"])
    with open(ris_path, encoding="utf-8") as f:
        ck.eq(f.read().count("TY  - JOUR"), 2, "重复入库同一条目不产生重复题录")

    # ---------- 入库：坏输入一律非零退出 ----------
    ck.eq(zsmain(["--json", os.path.join(tmp, "nope.json"), "--all"]), 1,
          "输入文件不存在返回 1")
    ck.eq(zsmain(["--json", os.path.join(tmp, "payloads", "batch_empty.json"), "--all"]), 1,
          "空批次返回 1")
    ck.eq(zsmain(["--json", os.path.join(tmp, "payloads", "batch_not_list.json"), "--all"]), 1,
          "JSON 顶层不是数组返回 1")
    ck.eq(zsmain(["--json", batch, "--items", "abc"]), 1, "--items 非数字返回 1")
    ck.eq(zsmain(["--json", batch, "--items", "99"]), 1, "编号不存在返回 1")

    ck.eq(zsmain(["--json", os.path.join(tmp, "payloads", "batch_bom.json"),
                  "--items", "3"]), 0, "带 UTF-8 BOM 的 JSON 可正常读取")

    # ---------- 查重不可用时必须告警而非静默跳过 ----------
    bad_dir = os.path.join(tmp, "broken")
    os.makedirs(bad_dir, exist_ok=True)
    with open(os.path.join(bad_dir, "zotero.sqlite"), "wb") as f:
        f.write(b"this is not a sqlite database")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        d2, t2 = zs.load_existing(bad_dir)
    ck.eq((d2, t2), (set(), set()), "库损坏时查重集合为空")
    ck.contains(err.getvalue(), "查重", "库损坏时打印查重不可用告警（不静默）")

    # ---------- 找不到数据目录 ----------
    os.environ["USERPROFILE"] = os.path.join(tmp, "nowhere")
    ck.eq(zq.find_data_dir(), "", "找不到 zotero.sqlite 时返回空串")

    _test_pdf_attach(ck, tmp)
    _test_auth_required(ck, tmp)
    _test_collections(ck, tmp)
    _test_author_parsing(ck)
    _test_ris_write_failure(ck, tmp)

    shutil.rmtree(tmp, ignore_errors=True)
    return ck.report()


@contextlib.contextmanager
def _raise_ctx(exc):
    """上下文管理器：进入即抛异常，用于模拟 sqlite 副本不可用。"""
    raise exc
    yield          # noqa: unreachable  —— 仅为让它成为生成器函数


def _test_collections(ck, tmp):
    """分类：列表并集、三种写法解析、多分类、未命中报错、api_create 带分类。

    注意：主流程末尾把 USERPROFILE 指向了 nowhere，这里必须显式还原到夹具，
    否则 find_data_dir() 读不到夹具库，list_collections 的 sqlite 来源会全空。
    """
    import zotero_query as zq
    import zotero_save as zs

    os.environ["USERPROFILE"] = os.path.join(tmp, "zotero")
    os.environ["APPDATA"] = os.path.join(tmp, "nonexistent_appdata")
    data_dir = zq.find_data_dir()
    ck.check(os.path.abspath(data_dir).startswith(os.path.abspath(tmp)),
             "分类：数据目录已还原到夹具内")

    # ---------- 两来源取并集（核心回归：只信 API 会漏掉新分类） ----------
    fake = _FakeAPI()
    restore = _with_fake_api(zs, fake)
    try:
        sets = zs.list_collections(data_dir)
    finally:
        restore()
    got = dict(sets)          # 名称 -> Key
    ck.eq(len(sets), 2, "分类：两个来源合并后共 2 个（API 只回 1 个）")
    ck.eq(got.get("Thesis References"), "TU38AQXQ",
          "分类：并集包含 API 来源的分类")
    ck.eq(got.get("Ontology Papers"), "IN7CD4ST",
          "回归：并集包含**只存在于 sqlite** 的分类（API 索引滞后）")
    ck.eq([n for n, _ in sets], sorted(n for n, _ in sets), "分类：结果按名称排序")

    # ---------- 两来源都失败 -> 空列表，不抛异常 ----------
    # 注意要 patch `zs.open_ro_copy`（zotero_save 用 from-import 绑了**自己的**模块全局名），
    # 改 `zq.open_ro_copy` 对它无效——这正是这个模块容易被写错的地方。
    saved_open = zs.open_ro_copy
    zs.open_ro_copy = lambda d: _raise_ctx(RuntimeError("no sqlite"))
    try:
        import urllib.request as _ur
        saved = _ur.urlopen
        _ur.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("no api"))
        try:
            ck.eq(zs.list_collections(data_dir), [],
                  "分类：两来源都不可用时返回空列表（不抛异常）")
        finally:
            _ur.urlopen = saved
    finally:
        zs.open_ro_copy = saved_open

    # ---------- resolve_collections：三种写法 ----------
    restore = _with_fake_api(zs, _FakeAPI())
    try:
        ck.eq(zs.resolve_collections("Ontology Papers", data_dir), ["IN7CD4ST"],
              "分类解析：全名精确匹配")
        ck.eq(zs.resolve_collections("ontology papers", data_dir), ["IN7CD4ST"],
              "分类解析：全名忽略大小写")
        ck.eq(zs.resolve_collections("IN7CD4ST", data_dir), ["IN7CD4ST"],
              "分类解析：8 位 Key 直接命中")
        ck.eq(zs.resolve_collections("Ontolog", data_dir), ["IN7CD4ST"],
              "分类解析：唯一名称片段命中")
        ck.eq(zs.resolve_collections("", data_dir), [], "分类解析：空串返回空列表（不指定分类）")
        ck.eq(zs.resolve_collections("Ontology Papers,TU38AQXQ", data_dir),
              ["IN7CD4ST", "TU38AQXQ"], "分类解析：逗号分隔多个且保持输入顺序")
        ck.eq(zs.resolve_collections("TU38AQXQ,TU38AQXQ", data_dir), ["TU38AQXQ"],
              "分类解析：重复项去重")
    finally:
        restore()

    # ---------- resolve_collections：未命中 / 多义都要报错并列出候选 ----------
    restore = _with_fake_api(zs, _FakeAPI())
    try:
        msg = ""
        try:
            zs.resolve_collections("No Such Collection", data_dir)
        except ValueError as e:
            msg = str(e)
        ck.contains(msg, "找不到分类", "分类解析：未命中抛 ValueError")
        ck.contains(msg, "Ontology Papers", "分类解析：未命中时报错列出候选分类")
        ck.contains(msg, "IN7CD4ST", "分类解析：候选分类带 8 位 Key")

        msg2 = ""
        try:
            # 两类都含 "o"（Thesis References 里没有 o，用 "e" 则两类都含）
            zs.resolve_collections("e", data_dir)
        except ValueError as e:
            msg2 = str(e)
        ck.contains(msg2, "多个匹配", "分类解析：片段多义时抛 ValueError")
    finally:
        restore()

    # ---------- api_create：带 / 不带 collections ----------
    for label, spec, want in (
            ("带分类", ["IN7CD4ST"], ["IN7CD4ST"]),
            ("不带分类", None, None)):
        fake3 = _FakeAPI()
        restore = _with_fake_api(zs, fake3)
        try:
            key = zs.api_create({"title": "T", "authors": ["A B"], "year": "2024"},
                                data_dir, collections=spec)
        finally:
            restore()
        payload = fake3.item_keys.get(key, {})
        ck.eq(payload.get("collections"), want,
              f"api_create：{label}时请求体的 collections 字段正确")
        ck.eq(payload.get("title"), "T", f"api_create：{label}时题录字段不受影响")

    # ---------- CLI：--list-collections 与 --collection ----------
    ck.eq(zsmain_stub(zs, ["--list-collections"], data_dir), 0,
          "CLI：--list-collections 返回 0（不被互斥组拦住）")
    ck.eq(zsmain_stub(zs, ["--list-collections", "--collection", "IN7CD4ST"], data_dir), 0,
          "CLI：--list-collections 与其他参数并存时仍返回 0（它优先执行）")
    ck.eq(zsmain_stub(zs, ["--json", "x.json", "--all", "--collection", "No Such"],
                      data_dir, bad_dir=True), 1,
          "CLI：分类名写错时在入库前就返回 1（不必等建完条目）")


def _test_author_parsing(ck):
    """作者姓名解析：两种形态都不能写反（这是会写坏用户 Zotero 库的路径）。

    回归背景：`split_author()` 早先只按空格切分，于是本 skill 自己
    `search_papers.parse_crossref()` 产出的 "姓 名"（带逗号）形态——
    如 "Smith, John"——会被解析成 firstName="Smith," / lastName="John"，
    即姓名颠倒且姓氏带逗号，直接写进用户库里的作者字段。
    """
    import zotero_save as zs

    ck.eq(zs.split_author("Zhang Wei"),
          {"creatorType": "author", "firstName": "Zhang", "lastName": "Wei"},
          "作者解析：空格形态（OpenAlex/S2）姓在后")
    ck.eq(zs.split_author("Smith, John"),
          {"creatorType": "author", "firstName": "John", "lastName": "Smith"},
          "作者解析：逗号形态（Crossref）姓在前，姓名不得颠倒")
    ck.eq(zs.split_author("van der Berg, Anna"),
          {"creatorType": "author", "firstName": "Anna", "lastName": "van der Berg"},
          "作者解析：逗号前的复姓整体作为姓氏")
    ck.eq(zs.split_author("李雷"),
          {"creatorType": "author", "firstName": "", "lastName": "李雷"},
          "作者解析：单节中文名整串作姓氏")
    ck.eq(zs.split_author("Smith, Jr., John")["lastName"], "Smith",
          "作者解析：带后缀的多逗号形态仍以首节为姓氏")
    ck.eq(zs.split_author("   "), None, "作者解析：空白字符串返回 None")
    ck.eq(zs.split_author(""), None, "作者解析：空字符串返回 None")

    # 端到端：Crossref 形态的作者经 api_create 写入请求体后，字段顺序必须正确
    ck.eq(zs.split_author("Noy, Natalya"),
          {"creatorType": "author", "firstName": "Natalya", "lastName": "Noy"},
          "作者解析：Crossref 'family given' 形态端到端正确")


def _test_ris_write_failure(ck, tmp):
    """RIS 兜底写入失败时必须**受控报错**，不能裸 traceback。

    回归背景：`main()` 早先对 `import_dir` 的创建做了 try/except，却把真正写
    `batch.ris` 的那句 `open(..., "w")` 留在保护之外——目录不可写时脚本以
    `[运行失败] PermissionError` 结束（违反 SKILL.md 的退出码契约），而且
    「文件→导入」的指引根本不会打印，用户的降级路径整体失效。

    构造方式：把 `skill-import/batch.ris` 先建成**目录**，`open(..., "w")` 必定
    抛 IsADirectoryError（受限写环境下同样常见的失败形态）。
    """
    import zotero_query as zq
    import zotero_save as zs

    data_dir = zq.find_data_dir()
    if not data_dir:
        ck.check(False, "RIS 写入失败用例：找不到夹具数据目录")
        return
    batch = os.path.join(tmp, "payloads", "batch.json")
    paper = {"index": 1, "title": "RIS Failure Probe Paper", "authors": ["Smith, John"],
             "year": "2024", "doi": "10.1000/ris-fail-001", "venue": "J",
             "link": "https://doi.org/10.1000/ris-fail-001", "abstract": "a",
             "pdf_url": "", "local_pdf": ""}
    with open(batch, "w", encoding="utf-8") as f:
        json.dump([paper], f, ensure_ascii=False)

    ris_path = os.path.join(data_dir, "skill-import", "batch.ris")
    os.makedirs(os.path.dirname(ris_path), exist_ok=True)
    # 上一次用例可能留下同名文件/目录，先清干净再占位成目录
    if os.path.isfile(ris_path) or os.path.islink(ris_path):
        os.remove(ris_path)
    elif os.path.isdir(ris_path):
        shutil.rmtree(ris_path, ignore_errors=True)
    os.makedirs(ris_path, exist_ok=True)

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = zs.main(["--json", batch, "--all"])
    shutil.rmtree(ris_path, ignore_errors=True)

    ck.eq(code, 1, "RIS 兜底写入失败：以受控失败退出（非 0）")
    ck.contains(err.getvalue(), "RIS 兜底写入失败", "RIS 写入失败时打印受控错误说明")
    ck.not_contains(err.getvalue() + out.getvalue(), "Traceback", "RIS 写入失败时不裸露 traceback")


def zsmain_stub(zs, argv, data_dir, bad_dir=False):
    """在隔离环境里调 zs.main，返回退出码。data_dir 用于构造可用的 --json。"""
    import contextlib as _c
    import io as _io
    if bad_dir:
        batch = os.path.join(os.path.dirname(data_dir), "payloads", "batch.json")
        argv = [batch if a == "x.json" else a for a in argv]
    with _c.redirect_stdout(_io.StringIO()), _c.redirect_stderr(_io.StringIO()):
        return zs.main(argv)



def _tree(root):
    """目录内容的确定性快照：相对路径 -> 大小。"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            fp = os.path.join(dirpath, fn)
            out[os.path.relpath(fp, root)] = os.path.getsize(fp)
    return out


def _tmp_copy_count():
    return len(_tmp_copy_names())


def _tmp_copy_names():
    """系统临时目录里 zotero_ro_* 副本目录的集合（用于前后快照比对）。"""
    try:
        return {n for n in os.listdir(tempfile.gettempdir()) if n.startswith("zotero_ro_")}
    except OSError:
        return set()


def _report_tmp_leftovers(ck, before):
    """如实报告本次运行新产生的临时副本目录（不作为失败条件）。

    为什么不硬断言：受限沙箱（如 DSH 的 workspace-write）下 `shutil.rmtree`
    可能被拒绝，**目录壳**会留下来——那是环境权限问题，不是「用后即清」的逻辑失效。
    而「副本是否还留着数据」这一条已经由 `_tree(data_dir)` 的严格只读断言覆盖。
    """
    new = _tmp_copy_names() - before
    if not new:
        ck.check(True, "临时副本用后即清（无新增副本目录）")
        return
    print(f"  [提示] 环境不允许删除临时目录外壳，残留 {len(new)} 个目录（{sorted(new)}）；"
          "在可写环境下不会发生，可用管理员权限清理")


# --------------------------------------------------------------------------
# PDF 附件上传：用假本地 API 走通全部分支，绝不联网、绝不碰真实 Zotero
# --------------------------------------------------------------------------

class _FakeAPI:
    """Zotero 7 本地 API 的最小替身。

    只实现 zotero_save.py 真正用到的那几个端点，并记录每次请求，
    供断言「三步协议是否按序走完」。任何未注册的 URL 一律抛异常，
    避免测试悄悄依赖了没被声明出来的端点。
    """

    def __init__(self):
        self.calls = []          # (method, url, headers, body)
        self.item_keys = {}      # key -> item payload
        self.uploaded = {}       # uploadKey -> 上传的字节
        self.sid = "FAKE-SERVER-ID"
        self.key = "FAKEAPIKEY"
        self.key_requests = 0
        self.authorize_returns_key = True
        # 本地 API 的分类列表。刻意**只放一条**，而夹具库里有两类——
        # 用来验证 list_collections 必须取两来源并集（API 索引会滞后于库内实况）。
        self.collections = [{"key": "TU38AQXQ", "data": {"name": "Thesis References"}}]
        self._seq = 0

    def _next_key(self):
        self._seq += 1
        return f"KEY{self._seq:04d}"

    def _json(self, payload):
        return _Resp(200, json.dumps(payload).encode("utf-8"))

    def __call__(self, req, timeout=None, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req
        method = getattr(req, "method", "GET") or "GET"
        headers = dict(getattr(req, "headers", {}) or {})
        # urllib 会把头名首字母大写，这里统一成小写比较
        low = {k.lower(): v for k, v in headers.items()}
        body = getattr(req, "data", None)
        self.calls.append((method, url, low, body))

        if url.endswith("/api/local/authorize"):
            self.key_requests += 1
            return self._json({"key": self.key} if self.authorize_returns_key else {})
        if url.endswith("/api/users/0/collections"):
            return self._json(self.collections)
        if url.endswith("/api/users/0/items?limit=1"):
            return _Resp(200, b"[]", extra_headers={"Zotero-Server-ID": self.sid})
        if url == "http://localhost:23119/api/users/0/items" and method == "POST":
            payload = json.loads(body.decode("utf-8"))
            key = self._next_key()
            self.item_keys[key] = payload[0]
            return self._json({"successful": {"0": {"key": key}}, "failed": {}})
        if "/file" in url and method == "POST":
            text = (body or b"").decode("utf-8", "replace")
            if "upload=" in text:
                up = re.search(r"upload=([^&]+)", text).group(1)
                self.uploaded.setdefault(up, b"")
                return _Resp(204, b"")
            md5 = re.search(r"md5=([^&]+)", text).group(1)
            fname = re.search(r"filename=([^&]+)", text).group(1)
            size = re.search(r"filesize=(\d+)", text).group(1)
            self.last_md5_req = (md5, fname, size)
            return self._json({"url": "http://localhost:23119/api/local/uploads/UP1",
                               "uploadKey": "UP1"})
        if url == "http://localhost:23119/api/local/uploads/UP1" and method == "POST":
            self.uploaded["UP1"] = body
            return _Resp(201, b"")
        raise AssertionError(f"测试替身未声明该请求：{method} {url}")

class _Resp:
    """最小响应对象：支持 with 语法、read()、headers、status。"""

    def __init__(self, status, body, extra_headers=None):
        self.status = status
        self._body = body
        self.headers = {"Zotero-Server-ID": "FAKE-SERVER-ID"}
        if extra_headers:
            self.headers.update(extra_headers)

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _with_fake_api(zs, fake):
    """把 zotero_save 用到的网络入口全部换成替身，返回还原函数。

    注意要连 `urllib.request.urlopen` 一起换掉——`_server_id()` 是直接调它取
    Server-ID 的，只替换 `_server_id` 不足以拦住所有出网路径，漏掉会真的去连
    本机 23119 端口（若 Zotero 恰好在运行，测试就会打到真实服务上）。
    """
    import urllib.request as _ur

    saved = {
        "server_id": zs._server_id,
        "server_id_cache": zs._server_id_cache,
        "api_key_cache": zs._api_key_cache,
        "request_key": zs.request_key,
        "urlopen": _ur.urlopen,
    }
    zs._server_id = lambda timeout=3: fake.sid
    zs._server_id_cache = fake.sid
    zs._api_key_cache = None
    zs.request_key = lambda data_dir, timeout=60, reporter=None, force=False: (
        fake.key if fake.authorize_returns_key else "")
    _ur.urlopen = fake

    def restore():
        zs._server_id = saved["server_id"]
        zs._server_id_cache = saved["server_id_cache"]
        zs._api_key_cache = saved["api_key_cache"]
        zs.request_key = saved["request_key"]
        _ur.urlopen = saved["urlopen"]

    return restore


def _test_pdf_attach(ck, tmp):
    """附件上传三步协议 + 失败分支，全部用假 API 在本进程内跑。"""
    import zotero_save as zs

    # 造一个假 PDF（内容任意，只验证字节被原样上传）
    pdf_dir = os.path.join(tmp, "fakepdf")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf = os.path.join(pdf_dir, "2023_Test_Paper.pdf")
    payload = b"%PDF-1.4\n" + b"x" * 4096
    with open(pdf, "wb") as f:
        f.write(payload)

    # ---------- MD5 分块计算与整读一致 ----------
    ck.eq(zs._md5_file(pdf), hashlib.md5(payload).hexdigest(),
          "附件：分块算出的 MD5 与整读一致")
    ck.eq(zs._md5_file(pdf, chunk=7), hashlib.md5(payload).hexdigest(),
          "附件：任意分块大小结果一致（小块边界正确）")

    # ---------- 正常路径：三步走完 ----------
    fake = _FakeAPI()
    restore = _with_fake_api(zs, fake)
    try:
        att_key = zs.api_attach_pdf("PARENT01", pdf, os.path.join(tmp, "zotero", "Zotero"))
    finally:
        restore()

    ck.check(bool(att_key), "附件：成功返回附件条目 Key")
    ck.eq(fake.item_keys.get(att_key, {}).get("itemType"), "attachment",
          "附件：先建了 itemType=attachment 的条目")
    ck.eq(fake.item_keys.get(att_key, {}).get("parentItem"), "PARENT01",
          "附件：附件条目挂在父条目上")
    ck.eq(fake.item_keys.get(att_key, {}).get("linkMode"), "imported_url",
          "附件：linkMode 为 imported_url（文件收进 storage/）")
    ck.eq(fake.item_keys.get(att_key, {}).get("contentType"), "application/pdf",
          "附件：contentType 为 application/pdf")

    ck.eq(getattr(fake, "last_md5_req", None),
          (hashlib.md5(payload).hexdigest(), "2023_Test_Paper.pdf", str(len(payload))),
          "附件：第 1 步带上正确的 md5/文件名/大小")
    ck.eq(fake.uploaded.get("UP1"), payload, "附件：第 2 步上传的字节与源文件完全一致")

    posts = [c for c in fake.calls if c[0] == "POST" and "/file" in c[1]]
    ck.eq(len(posts), 2, "附件：上报与登记各一次（三步协议里 /file 被调两次）")
    ck.eq((posts[0][2].get("if-none-match"), (posts[0][3] or b"").decode().find("md5=") >= 0),
          ("*", True), "附件：第 1 步带 If-None-Match: * 且 body 含 md5")
    ck.contains((posts[1][3] or b"").decode(), "upload=UP1", "附件：第 3 步回传 uploadKey")

    # 写请求必须都带 Server-ID 与 Bearer 凭据
    writes = [c for c in fake.calls if c[0] == "POST"]
    ck.eq([c[2].get("zotero-server-id") for c in writes].count("FAKE-SERVER-ID"), len(writes),
          "附件：每个写请求都带 Zotero-Server-ID")
    ck.check(all(c[2].get("authorization") == "Bearer " + fake.key for c in writes),
             "附件：每个写请求都带 Bearer 凭据")

    # ---------- 失败分支：拿不到 uploadKey 必须抛，绝不假装成功 ----------
    class _NoUrl(_FakeAPI):
        def __call__(self, req, timeout=None, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else req
            method = getattr(req, "method", "GET") or "GET"
            if method == "POST" and "/file" in url and b"upload=" not in (getattr(req, "data", b"") or b""):
                self.calls.append((method, url, {}, getattr(req, "data", None)))
                return _Resp(200, b"{}")
            return _FakeAPI.__call__(self, req, timeout, **kwargs)

    fake2 = _NoUrl()
    restore = _with_fake_api(zs, fake2)
    try:
        raised = ""
        try:
            zs.api_attach_pdf("PARENT01", pdf, os.path.join(tmp, "zotero", "Zotero"))
        except Exception as e:      # noqa: BLE001
            raised = type(e).__name__
    finally:
        restore()
    ck.eq(raised, "RuntimeError", "附件：取不到 uploadKey 时抛出而非静默返回空")

    # ---------- 失败分支：PDF 不存在，提前拒绝 ----------
    restore = _with_fake_api(zs, _FakeAPI())
    try:
        raised = ""
        try:
            zs.api_attach_pdf("PARENT01", os.path.join(tmp, "nope.pdf"),
                              os.path.join(tmp, "zotero", "Zotero"))
        except Exception as e:      # noqa: BLE001
            raised = type(e).__name__
    finally:
        restore()
    ck.eq(raised, "ValueError", "附件：PDF 不存在时提前抛 ValueError（不发网络请求）")

    # ---------- 失败分支：服务端 412（同名文件已存在 / md5 不符）要给人话 ----------
    class _Precondition(_FakeAPI):
        def __call__(self, req, timeout=None, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else req
            method = getattr(req, "method", "GET") or "GET"
            body = getattr(req, "data", b"") or b""
            if method == "POST" and "/file" in url and b"upload=" not in body:
                self.calls.append((method, url, {}, body))
                raise urllib.error.HTTPError(url, 412, "Precondition Failed", {}, None)
            return _FakeAPI.__call__(self, req, timeout, **kwargs)

    fake3 = _Precondition()
    restore = _with_fake_api(zs, fake3)
    try:
        msg = ""
        try:
            zs.api_attach_pdf("PARENT01", pdf, os.path.join(tmp, "zotero", "Zotero"))
        except Exception as e:      # noqa: BLE001
            msg = str(e)
    finally:
        restore()
    ck.contains(msg, "412", "附件：412 报错写明状态码")
    ck.contains(msg, "同名文件", "附件：412 报错给出可读原因（不是裸 HTTPError）")


def _test_auth_required(ck, tmp):
    """授权缺失/失效必须抛 AuthRequired，且不得对不可自愈的失败反复重试。"""
    import zotero_save as zs

    data_dir = os.path.join(tmp, "authdir")
    os.makedirs(os.path.join(data_dir, "skill-import"), exist_ok=True)

    # 取不到 Server-ID -> AuthRequired，且一次网络请求都不该发起
    fake = _FakeAPI()
    fake.sid = ""
    saved = (zs._server_id, zs._server_id_cache, zs._api_key_cache)
    zs._server_id = lambda timeout=3: ""
    zs._server_id_cache = ""
    zs._api_key_cache = None
    try:
        raised = ""
        try:
            zs.api_create({"title": "T"}, data_dir)
        except Exception as e:      # noqa: BLE001
            raised = type(e).__name__
    finally:
        zs._server_id, zs._server_id_cache, zs._api_key_cache = saved
    ck.eq(raised, "AuthRequired", "授权：无 Server-ID 时抛 AuthRequired")
    ck.eq(len(fake.calls), 0, "授权：无 Server-ID 时不发起任何写请求")

    # 有 Server-ID 但授权被拒 -> AuthRequired
    fake2 = _FakeAPI()
    fake2.authorize_returns_key = False
    restore = _with_fake_api(zs, fake2)
    try:
        raised = ""
        try:
            zs.api_create({"title": "T"}, data_dir)
        except Exception as e:      # noqa: BLE001
            raised = type(e).__name__
    finally:
        restore()
    ck.eq(raised, "AuthRequired", "授权：用户拒绝授权时抛 AuthRequired")
    ck.eq(fake2.authorize_returns_key, False, "授权：拒绝后不再重试申请（弹窗只弹一次）")

    # AuthRequired 是 RuntimeError 的子类（调用方可用 RuntimeError 兜底）
    ck.check(issubclass(zs.AuthRequired, RuntimeError),
             "授权：AuthRequired 继承 RuntimeError，旧调用方仍能捕获")



if __name__ == "__main__":
    run_main(run)
