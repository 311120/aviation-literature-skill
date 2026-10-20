#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取 Zotero 文献库：题录、PDF 附件路径、笔记与 PDF 标注。

优先走 Zotero 7 本地 HTTP API；未运行时回退到只读查询复制出来的
zotero.sqlite（避免锁库）。需要笔记/标注（--notes/--key）时直接走
sqlite 路径（对运行中的 Zotero 也安全，因为查的是副本副本）。

用法：
  python zotero_query.py "knowledge graph" --pdf   # 关键词搜馆藏（标题/作者/摘要/笔记全文）
  python zotero_query.py "" --limit 20             # 列出最近 20 条
  python zotero_query.py "公差" --notes            # 同时显示笔记摘录
  python zotero_query.py --key YZA4D3CK            # 导出某条目的字段、笔记、PDF 标注

仅输出数据库/API 中真实存在的内容，不做任何补全或推断。
绝不直接连接原库——一律查复制到独立临时目录的副本。

退出码：0 正常完成（含"馆藏为空"）；1 输入非法或受控失败；2 命令行用法错误。
"""
import argparse
import contextlib
import glob
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_API = "http://localhost:23119/api/users/0/items"

# 馆藏检索覆盖的条目类型（note = 独立笔记条目）
ITEM_TYPES = ("journalArticle", "conferencePaper", "preprint", "report",
              "thesis", "book", "bookSection", "document", "note")


def find_data_dir():
    """定位 Zotero 数据目录（含 zotero.sqlite 的目录）。找不到返回空串。"""
    candidates = []
    profile_prefs = glob.glob(os.path.join(os.environ.get("APPDATA", ""),
                                           "Zotero", "Zotero", "Profiles", "*", "prefs.js"))
    for pf in profile_prefs:
        try:
            with open(pf, encoding="utf-8", errors="replace") as f:
                content = f.read()
            m = re.search(r'"extensions\.zotero\.dataDir"\s*,\s*"([^"]+)"', content)
            if m:
                path = m.group(1).replace("\\\\", "\\")
                # 相对路径按 profile 目录解析。早先写成 `if not path.startswith("C:")`，
                # 会把 D:\… 或 \\server\share 这类绝对路径也当相对路径拼接，从而找不到库。
                if not os.path.isabs(path):
                    path = os.path.join(os.path.dirname(pf), path)
                candidates.append(path)
        except Exception:
            pass
    candidates += [
        os.path.join(os.environ.get("USERPROFILE", ""), "Zotero"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Documents", "Zotero"),
    ]
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "zotero.sqlite")):
            return c
    return ""


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _temp_dir(prefix, parent=None):
    """建临时目录；随机名目录不可写时降级为「固定名 + 短随机后缀」。

    为什么要这个降级：`tempfile.mkdtemp()` 建出的随机名目录，在受限环境
    （如 DSH 的 workspace-write 沙箱）下可能**创建成功但不可写**——
    mkdtemp 本身不报错，写第一个文件才 PermissionError，于是表现为
    「读取馆藏数据库失败（PermissionError）」，而真实原因跟 Zotero 毫无关系。
    故这里建完立刻验证可写性，不行就换固定名目录兜底。
    """
    d = ""
    try:
        d = tempfile.mkdtemp(prefix=prefix, dir=parent)
    except (PermissionError, OSError):
        d = ""
    if d:
        try:
            probe = os.path.join(d, ".writable")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("x")
            os.remove(probe)
            return d
        except OSError:
            shutil.rmtree(d, ignore_errors=True)
    base = parent or tempfile.gettempdir()
    d = os.path.join(base, prefix + uuid.uuid4().hex[:8])
    os.makedirs(d, exist_ok=True)
    return d


@contextlib.contextmanager
def open_ro_copy(data_dir):
    """把 zotero.sqlite（连同 WAL/SHM 日志）复制到独立临时目录后打开，退出时清理。

    用独立临时目录而非固定文件名：并发运行时互不覆盖，且不会在磁盘上留下副本。
    绝不直接连接原库——Zotero 运行时原库处于锁定状态。
    """
    tmpdir = _temp_dir("zotero_ro_")
    db = os.path.join(tmpdir, "zotero.sqlite")
    try:
        # 用 copyfile 而非 copy2：副本只需内容与 WAL 一致，复制无谓的文件元数据
        # 反而可能在只读源上失败（copy2 会尝试把源文件的权限/时间戳写回目标）。
        shutil.copyfile(os.path.join(data_dir, "zotero.sqlite"), db)
        for ext in ("-wal", "-shm"):
            src = os.path.join(data_dir, "zotero.sqlite" + ext)
            if os.path.isfile(src):
                shutil.copyfile(src, db + ext)
        con = sqlite3.connect(db)
        try:
            yield con
        finally:
            con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def query_local_api(query, limit):
    """Zotero 7 本地 API（需 Zotero 正在运行），题录级。"""
    url = LOCAL_API + f"?format=json&limit={limit}&itemType=-attachment"
    if query:
        url += "&q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "zotero-query-script"})
    data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    papers = []
    for it in data if isinstance(data, list) else []:
        d = it.get("data", {}) if isinstance(it, dict) else {}
        creators = [f"{c.get('lastName', '')} {c.get('firstName', '')}".strip()
                    for c in (d.get("creators") or []) if isinstance(c, dict)]
        papers.append({
            "title": d.get("title", ""),
            "year": (d.get("date") or "")[:4],
            "authors": creators,
            "item_type": d.get("itemType", ""),
            "key": d.get("key", ""),
            "pdf": "",
            "publication": d.get("publicationTitle", ""),
            "notes": [],
            "source": "local-api",
        })
    return papers


_SQLITE_SQL_TMPL = """
SELECT i.itemID, i.key, it.typeName,
       MAX(CASE WHEN f.fieldName='title' THEN v.value END) AS title,
       MAX(CASE WHEN f.fieldName='date' THEN v.value END) AS date,
       MAX(CASE WHEN f.fieldName='publicationTitle' THEN v.value END) AS pub
FROM items i
JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
LEFT JOIN itemData idata ON idata.itemID = i.itemID
LEFT JOIN fields f ON f.fieldID = idata.fieldID
LEFT JOIN itemDataValues v ON v.valueID = idata.valueID
WHERE it.typeName IN (__TYPES__)
  AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
GROUP BY i.itemID
__HAVING__
ORDER BY i.itemID DESC
LIMIT :lim
"""

# 单个检索词在「标题 / 作者 / 摘要 / 笔记」四类字段任一命中即算命中。
# {i} 由 build_sqlite_query() 替换成词序号，保证每个词绑定各自的 :kwN 参数。
_MATCH_ONE_TERM = """(IFNULL(title,'') LIKE :kw{i}
        OR EXISTS (SELECT 1 FROM itemCreators ic
                   JOIN creators c ON c.creatorID = ic.creatorID
                   WHERE ic.itemID = i.itemID
                     AND (IFNULL(c.lastName,'') || ' ' || IFNULL(c.firstName,'')) LIKE :kw{i})
        OR EXISTS (SELECT 1 FROM itemData id2 JOIN itemDataValues v2 ON v2.valueID=id2.valueID
                   JOIN fields f2 ON f2.fieldID=id2.fieldID AND f2.fieldName='abstractNote'
                   WHERE id2.itemID=i.itemID AND v2.value LIKE :kw{i})
        OR EXISTS (SELECT 1 FROM itemNotes n
                   WHERE (n.parentItemID=i.itemID
                          OR (n.parentItemID IS NULL AND n.itemID=i.itemID))
                     AND n.note LIKE :kw{i}))"""


def build_sqlite_query(kw):
    """把关键词按空白分词，拼成「每个词都必须命中」的 AND 条件。

    为什么必须分词：本地 API 路径把整串交给 Zotero 的 `q=`，由 Zotero 自己分词做
    AND 匹配；而 sqlite 路径早先用 `LIKE '%整串%'`，多词查询会退化成**短语匹配**。
    实测 `tolerance ontology` 在 API 下命中 2 条、sqlite 下 0 条——而
    `--pdf` / `--notes` 会强制走 sqlite，导致查重环节**静默漏检**（后果是重复下载）。
    两条路径语义必须一致，故此处对齐为分词 AND。

    单词语义不变；多词只会比原来的短语匹配命中更多（原文匹配短语的必然匹配全部词），
    因此本改动只修漏检、不会引入新的漏检。
    """
    terms = (kw or "").split()
    if terms:
        having = "HAVING " + " AND ".join(
            _MATCH_ONE_TERM.replace("{i}", str(n)) for n in range(len(terms)))
    else:
        having = ""          # 空关键词：不设 HAVING，列出全部（等价于旧版的 :kw = '' 短路）
    sql = (_SQLITE_SQL_TMPL
           .replace("__TYPES__", ",".join(repr(t) for t in ITEM_TYPES))
           .replace("__HAVING__", having))
    params = {f"kw{n}": f"%{t}%" for n, t in enumerate(terms)}
    return sql, params

# 作者单独取：主查询不再 JOIN itemCreators。否则 itemData 的多行会与作者行做笛卡尔积，
# GROUP_CONCAT 会把同一个作者重复拼 N 次（N = 该条目的字段数）。
AUTHORS_SQL = """
SELECT ic.itemID, c.lastName, c.firstName
FROM itemCreators ic
JOIN creators c ON c.creatorID = ic.creatorID
WHERE ic.itemID IN ({placeholders})
ORDER BY ic.itemID, ic.orderIndex
"""


def query_sqlite(kw, limit, data_dir, want_notes=False):
    """sqlite 只读副本查询。关键词同时匹配标题/作者/摘要/笔记内容。"""
    with open_ro_copy(data_dir) as con:
        return _query_sqlite(con, kw, limit, data_dir, want_notes)


def _query_sqlite(con, kw, limit, data_dir, want_notes):
    sql, params = build_sqlite_query(kw)
    params["lim"] = limit
    cur = con.execute(sql, params)
    papers = []
    for row in cur:
        item_id, key, type_name, title, date, pub = row
        papers.append({
            "item_id": item_id,
            "title": title or "",
            "year": (date or "")[:4],
            "authors": [],
            "item_type": type_name,
            "key": key,
            "pdf": "",
            "publication": pub or "",
            "notes": [],
            "source": "sqlite",
        })
    if not papers:
        return papers

    by_id = {p["item_id"]: p for p in papers}
    id_to_key = dict(con.execute("SELECT itemID, key FROM items"))

    # 作者单独取回，按 orderIndex 保序，并剔除完全重复的名字
    ids = list(by_id)
    for item_id, last, first in con.execute(
            AUTHORS_SQL.format(placeholders=",".join("?" * len(ids))), ids):
        name = f"{last or ''} {first or ''}".strip()
        if name and name not in by_id[item_id]["authors"]:
            by_id[item_id]["authors"].append(name)

    # 笔记：子笔记挂父条目；独立笔记（parentItemID 为空）挂自身条目
    if want_notes:
        for note_item_id, parent, note in con.execute(
                "SELECT itemID, parentItemID, note FROM itemNotes"):
            target_id = parent if parent is not None else note_item_id
            target = by_id.get(target_id)
            if target is not None:
                target["notes"].append(strip_html(note))

    # 独立笔记条目的标题回退为笔记开头
    for p in papers:
        if p["item_type"] == "note" and not p["title"]:
            own = con.execute("SELECT note FROM itemNotes WHERE itemID=?",
                              (p["item_id"],)).fetchone()
            p["title"] = (strip_html(own[0]) if own else "")[:80]

    # PDF 附件：parentItemID 是数字 itemID，storage 子目录名是附件自身的 item key
    for parent, att_id, path in con.execute(
            "SELECT parentItemID, itemID, path FROM itemAttachments "
            "WHERE contentType='application/pdf'"):
        target = by_id.get(parent)
        if not target or target["pdf"] or not path:
            continue
        target["pdf"] = _resolve_attachment(data_dir, id_to_key.get(att_id, ""), path)
    return papers


def _resolve_attachment(data_dir, att_key, path):
    """storage:<文件名> 形式解析为本地路径；文件不在本地时原样返回 storage: 前缀。"""
    if path and path.startswith("storage:"):
        local = os.path.join(data_dir, "storage", att_key, path[len("storage:"):])
        return local if os.path.isfile(local) else path
    return path or ""


def dump_key(key, data_dir):
    """导出单个条目的字段、笔记与 PDF 标注。返回是否找到该条目。"""
    with open_ro_copy(data_dir) as con:
        return _dump_key(con, key, data_dir)


def _dump_key(con, key, data_dir):
    row = con.execute(
        "SELECT itemID FROM items WHERE key=? "
        "AND itemID NOT IN (SELECT itemID FROM deletedItems)", (key,)).fetchone()
    if not row:
        print(f"未找到 Zotero Key 为 {key} 的条目（或在回收站）。")
        return False
    item_id = row[0]

    print(f"# Zotero 条目 {key}\n")
    for fname, value in con.execute(
            "SELECT f.fieldName, v.value FROM itemData d "
            "JOIN fields f ON f.fieldID=d.fieldID "
            "JOIN itemDataValues v ON v.valueID=d.valueID WHERE d.itemID=?",
            (item_id,)):
        text = strip_html(value) if fname == "abstractNote" else (value or "").strip()
        if text:
            print(f"- {fname}：{text[:500]}")
    creators = [strip_html(f"{r[0]} {r[1] or ''}") for r in con.execute(
        "SELECT c.lastName, c.firstName FROM itemCreators ic "
        "JOIN creators c ON c.creatorID=ic.creatorID WHERE ic.itemID=? "
        "ORDER BY ic.orderIndex", (item_id,))]
    if creators:
        print("- 作者：" + "; ".join(creators))

    notes = [strip_html(n[0]) for n in con.execute(
        "SELECT note FROM itemNotes WHERE parentItemID=?", (item_id,))]
    own = con.execute("SELECT note FROM itemNotes WHERE itemID=? "
                      "AND (parentItemID IS NULL OR parentItemID=itemID)",
                      (item_id,)).fetchone()
    if own and strip_html(own[0]) not in notes:
        print(f"\n## 本条目为独立笔记，内容：\n{strip_html(own[0])[:800]}")
    print(f"\n## 笔记（{len(notes)} 条）")
    for i, n in enumerate(notes, 1):
        print(f"\n[笔记 {i}] {n[:800]}{'……' if len(n) > 800 else ''}")

    id_to_key = dict(con.execute("SELECT itemID, key FROM items"))
    print("\n## PDF 附件与标注")
    atts = list(con.execute(
        "SELECT itemID, path FROM itemAttachments "
        "WHERE parentItemID=? AND contentType='application/pdf'", (item_id,)))
    if not atts:
        print("（无 PDF 附件记录）")
    for att_id, path in atts:
        print(f"\n附件：{_resolve_attachment(data_dir, id_to_key.get(att_id, ''), path)}")
        try:
            anns = list(con.execute(
                "SELECT type, text, comment, pageLabel FROM itemAnnotations "
                "WHERE parentItemID=? ORDER BY sortIndex", (att_id,)))
        except sqlite3.OperationalError:
            anns = []
            print("（该 Zotero 版本数据库无标注表）")
        for a_type, text, comment, page in anns:
            label = {"highlight": "高亮", "note": "批注", "text": "文本"}.get(a_type, a_type)
            content = strip_html(text or "") or strip_html(comment or "")
            if content:
                print(f"  [p.{page or '?'} {label}] {content[:300]}")
        if not anns:
            print("  （无标注）")
    return True


def _read_failure_hint(e):
    """读取失败时给出**指向正确方向**的提示。

    坑：早先所有异常都打印「若 Zotero 正在运行，稍等片刻重试；仍失败就先关闭 Zotero」。
    但真实原因常常是权限/文件系统问题（数据目录或临时目录不可写），与 Zotero 是否
    在运行毫无关系——那句话会把用户引向错误的排查方向（实测复现过：
    PermissionError 时提示"关闭 Zotero"，而 Zotero 当时根本没运行）。
    """
    if isinstance(e, (PermissionError, OSError)):
        return (f"读取馆藏数据库失败（{type(e).__name__}）：数据目录或其临时副本不可写/被占用。"
                f"数据库目录：{os.environ.get('TEMP') or tempfile.gettempdir()}（临时副本写在这里）。"
                "请检查该目录与 zotero.sqlite 所在目录的权限，或确认磁盘空间充足。")
    if isinstance(e, sqlite3.Error):
        return (f"读取馆藏数据库失败（{type(e).__name__}）：数据库可能被占用或副本不完整。"
                "若 Zotero 正在运行，稍等片刻重试；仍失败就先关闭 Zotero 再试。")
    return f"读取馆藏数据库失败（{type(e).__name__}）：{e}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="读取 Zotero 文献库（题录/附件/笔记/标注）")
    ap.add_argument("query", nargs="?", default="", help="关键词（留空列出最近文献）")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--pdf", action="store_true", help="显示 PDF 附件本地路径")
    ap.add_argument("--notes", action="store_true", help="显示笔记摘录（走 sqlite 路径）")
    ap.add_argument("--key", metavar="ZOTERO_KEY", help="导出指定条目的字段、笔记、PDF 标注")
    args = ap.parse_args(argv)

    if args.limit <= 0:
        print("--limit 必须为正整数。", file=sys.stderr)
        return 1

    data_dir = find_data_dir()
    if args.key:
        if not data_dir:
            print("未找到 zotero.sqlite，无法导出条目详情。", file=sys.stderr)
            return 1
        try:
            return 0 if dump_key(args.key, data_dir) else 1
        except Exception as e:
            print(_read_failure_hint(e), file=sys.stderr)
            return 1

    papers, mode = [], ""
    # --pdf/--notes 需要本地文件与笔记细节，直接走 sqlite 副本（对运行中的 Zotero 也安全）
    if not (args.notes or args.pdf):
        try:
            papers = query_local_api(args.query, args.limit)
            mode = "本地 API（Zotero 正在运行）"
        except Exception:
            mode = ""
    if not papers:
        if not data_dir:
            print("无法连接 Zotero 本地 API，也未找到 zotero.sqlite。"
                  "请确认 Zotero 已安装（或运行中）。", file=sys.stderr)
            return 1
        try:
            papers = query_sqlite(args.query, args.limit, data_dir, want_notes=args.notes)
        except Exception as e:
            print(_read_failure_hint(e), file=sys.stderr)
            return 1
        mode = f"sqlite 只读副本（数据目录：{data_dir}）"

    if not papers:
        print(f"馆藏中没有匹配“{args.query}”的文献。" if args.query else "馆藏为空。")
        return 0

    print(f"# Zotero 馆藏检索：{mode}\n")
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p["authors"][:4]) + (" et al." if len(p["authors"]) > 4 else "")
        pdf_line = f"\n   PDF：{p['pdf']}" if args.pdf and p.get("pdf") else ""
        notes_line = ""
        if args.notes:
            if p["notes"]:
                first = p["notes"][0]
                notes_line = (f"\n   笔记：{len(p['notes'])} 条，摘录："
                              f"{first[:100]}{'……' if len(first) > 100 else ''}")
            else:
                notes_line = "\n   笔记：（无）"
        print(f"{i}. [{p['year'] or '?'}] {p['title']}\n"
              f"   作者：{authors or '不详'}｜类型：{p['item_type']}｜Zotero Key：{p['key']}"
              + (f"｜出处：{p['publication']}" if p.get("publication") else "")
              + pdf_line + notes_line)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"[运行失败] {type(e).__name__}：{e}", file=sys.stderr)
        sys.exit(1)
