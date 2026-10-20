#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现场合成测试夹具。全部手写，不引入任何第三方真实文档或技能包。

生成内容：
  <target>/payloads/   四个数据源的原始载荷（正常 / 空 / 畸形）+ CLI 用批量 JSON
  <target>/zotero/Zotero/zotero.sqlite   复刻 Zotero 库表结构的最小库
  <target>/zotero/Zotero/storage/...     附件目录（一个存在、一个刻意缺失）
用法：
  python make_fixtures.py <target-dir>
被 run_all.py 与各用例自动调用。
"""
import json
import os
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# --------------------------------------------------------------------------
# 数据源载荷
# --------------------------------------------------------------------------

OPENALEX = {
    "results": [
        {
            "id": "https://openalex.org/W1001",
            "doi": "https://doi.org/10.1000/oa-001",
            "display_name": "Knowledge Graph Enabled Tolerance Specification",
            "publication_year": 2023,
            "authorships": [
                {"author": {"display_name": "Jia Jia"}},
                {"author": {"display_name": "Yingzhong Zhang"}},
            ],
            "primary_location": {"source": {"display_name": "IJAMT"}, "pdf_url": ""},
            "best_oa_location": {"pdf_url": "https://example.org/oa-001.pdf"},
            "open_access": {"is_oa": True, "oa_status": "gold"},
            "relevance_score": 42.5,
            "abstract_inverted_index": {
                "Tolerance": [0], "specification": [1], "via": [2], "knowledge": [3],
                "graphs": [4],
            },
        },
        {
            "id": "https://openalex.org/W1002",
            "doi": None,
            "display_name": "Aviation Domain Ontology Construction",
            "publication_year": None,
            "authorships": [],
            "primary_location": None,
            "best_oa_location": None,
            "abstract_inverted_index": None,
        },
        {
            # 无 OA 标识但有 DOI：应判为 SUB（需机构订阅）
            "id": "https://openalex.org/W1003",
            "doi": "https://doi.org/10.1000/sub-001",
            "display_name": "Tolerance Stack-up Analysis for Aircraft Assembly",
            "publication_year": 2022,
            "authorships": [{"author": {"display_name": "Wei Wang"}}],
            "primary_location": {"source": {"display_name": "JAMT"}, "pdf_url": ""},
            "best_oa_location": None,
            "open_access": {"is_oa": False, "oa_status": "closed"},
            "abstract_inverted_index": None,
        },
        {
            # 中文文献：应判为 CNKI
            "id": "https://openalex.org/W1004",
            "doi": "https://doi.org/10.1000/cn-001",
            "display_name": "飞机装配容差建模方法研究",
            "publication_year": 2021,
            "authorships": [{"author": {"display_name": "李雷"}}],
            "primary_location": {"source": {"display_name": "航空学报"}, "pdf_url": ""},
            "best_oa_location": None,
            "abstract_inverted_index": None,
        },
    ]
}

# 畸形：results 不是列表、元素不是字典、authorships 结构错位、摘要索引类型错
OPENALEX_MALFORMED = {
    "results": [
        "not-a-dict",
        {"id": "https://openalex.org/W2001", "display_name": None,
         "authorships": ["bad", {"nope": 1}, {"author": None}],
         "primary_location": "bad", "best_oa_location": 3,
         "abstract_inverted_index": {"w": "not-a-list"}},
        {"authorships": [{"author": {"display_name": "Ok Author"}}],
         "display_name": "Valid After Garbage",
         "abstract_inverted_index": {"b": [1, 0], "a": [0], "c": [2]}},
    ]
}

# bronze 档：源站可免费读到 PDF，但**没有开放许可**。它必须仍被判为 OA
# （用户真能免费拿到），同时提醒：这不是"开放授权"，转载/复用仍受限制。
OPENALEX_BRONZE = {
    "results": [
        {
            "id": "https://openalex.org/W3001",
            "doi": "https://doi.org/10.1000/bronze-001",
            "display_name": "Bronze Open Access Tolerance Datasets",
            "publication_year": 2024,
            "authorships": [{"author": {"display_name": "Ann Lee"}}],
            "primary_location": {"source": {"display_name": "J. Tolerancing"}, "pdf_url": ""},
            "best_oa_location": {"pdf_url": "https://example.org/bronze-001.pdf"},
            "open_access": {"is_oa": True, "oa_status": "bronze"},
            "abstract_inverted_index": None,
        },
    ]
}

CROSSREF = {
    "message": {
        "items": [
            {   # 真开放获取：license 为 CC-BY，才判 OA
                "title": ["Ontology Based Process Review for Aerospace"],
                "author": [{"family": "Noy", "given": "Natalya"}],
                "issued": {"date-parts": [[2001, 1, 1]]},
                "DOI": "10.1000/cr-001",
                "container-title": ["IEEE Intelligent Systems"],
                "link": [{"content-type": "application/pdf", "URL": "https://example.org/cr-001.pdf"}],
                "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/",
                             "content-version": "vor"}],
            },
            {   # 付费期刊：只有出版商 TDM 端点、无 CC 授权 -> 不得判 OA
                # 回归用例：早先「拿到 pdf link 即视为 OA」会把这类条目误标为免费
                "title": ["Paywalled Tolerance Study"],
                "author": [{"family": "Smith", "given": "Ann"}],
                "issued": {"date-parts": [[2019, 3, 1]]},
                "DOI": "10.1000/cr-002",
                "container-title": ["Journal of Tolerancing"],
                "link": [{"content-type": "application/pdf",
                          "URL": "https://link.springer.com/content/pdf/10.1000/cr-002.pdf",
                          "intended-application": "text-mining"}],
                "license": [{"URL": "https://www.springernature.com/gp/researchers/"
                                    "text-and-data-mining",
                             "content-version": "tdm"}],
            },
            {"title": [], "author": None, "issued": None, "DOI": ""},
        ]
    }
}

ARXIV = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-01T00:00:00Z</published>
    <title>Graph RAG for Manufacturing Knowledge</title>
    <summary>We study graph retrieval augmented generation.</summary>
    <author><name>Alice Wu</name></author>
    <author><name>Bob Li</name></author>
  </entry>
  <entry>
    <title>Entry Without An Id</title>
    <published>2025-05-05T00:00:00Z</published>
  </entry>
</feed>
"""

S2 = {
    "data": [
        {"paperId": "abc123def456ghi", "title": "Process Planning with LLM",
         "year": 2024, "venue": "CIRP", "externalIds": {"DOI": "10.1000/s2-001"},
         "openAccessPdf": {"url": "https://example.org/s2-001.pdf"},
         "authors": [{"name": "Cara Chen"}], "abstract": "A study."},
        {"paperId": None, "title": None, "year": None, "venue": None,
         "externalIds": None, "openAccessPdf": None, "authors": None, "abstract": None},
    ]
}

# CLI 用批量结果（zotero_save.py 的输入）：含馆藏已有的、含 PDF 的、含重复 DOI 的
BATCH = [
    {"index": 1, "title": "Knowledge Graph Enabled Tolerance Specification",
     "authors": ["Jia Jia"], "year": "2023", "venue": "IJAMT",
     "id": "10.1000/oa-001", "doi": "10.1000/oa-001",
     "link": "https://doi.org/10.1000/oa-001", "pdf": "",
     "pdf_url": "", "local_pdf": "", "abstract": ""},
    {"index": 2, "title": "Aviation Ontology Construction",       # 与馆藏 DOI 相同 -> 应跳过
     "authors": ["Zhang San"], "year": "2023", "venue": "JMS",
     "id": "10.1000/aaa", "doi": "10.1000/aaa",
     "link": "https://doi.org/10.1000/aaa", "pdf": "",
     "pdf_url": "", "local_pdf": "", "abstract": ""},
    {"index": 3, "title": "Brand New Paper On HugeGraph",         # 馆藏没有 -> 应入库
     "authors": ["New Author"], "year": "2025", "venue": "GraphConf",
     "id": "10.1000/new-001", "doi": "10.1000/new-001",
     "link": "https://doi.org/10.1000/new-001", "pdf": "",
     "pdf_url": "", "local_pdf": "", "abstract": ""},
]


def write_payloads(root):
    d = os.path.join(root, "payloads")
    os.makedirs(d, exist_ok=True)
    files = {
        "openalex.json": OPENALEX,
        "openalex_empty.json": {"results": []},
        "openalex_bronze.json": OPENALEX_BRONZE,
        "openalex_malformed.json": OPENALEX_MALFORMED,
        "crossref.json": CROSSREF,
        "crossref_empty.json": {"message": {"items": []}},
        "crossref_malformed.json": {"message": "not-a-dict"},
        "s2.json": S2,
        "s2_empty.json": {"data": []},
        "s2_malformed.json": {"data": "not-a-list"},
        "batch.json": BATCH,
        "batch_empty.json": [],
        "batch_not_list.json": {"not": "a list"},
    }
    for name, obj in files.items():
        with open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, "arxiv.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(ARXIV)
    with open(os.path.join(d, "arxiv_empty.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write("<feed></feed>")
    with open(os.path.join(d, "batch_bom.json"), "w", encoding="utf-8-sig", newline="\n") as f:
        json.dump(BATCH, f, ensure_ascii=False)
    return d


# --------------------------------------------------------------------------
# Zotero 夹具库
# --------------------------------------------------------------------------

def build_zotero(root):
    """手写复刻 Zotero 库表结构，制造覆盖各分支的条目。"""
    zd = os.path.join(root, "zotero", "Zotero")
    os.makedirs(zd, exist_ok=True)
    db = os.path.join(zd, "zotero.sqlite")
    for p in (db, db + "-wal", db + "-shm"):
        if os.path.isfile(p):
            os.remove(p)

    con = sqlite3.connect(db)
    c = con.cursor()
    c.executescript("""
CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT, key TEXT, dateAdded TEXT);
CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, lastName TEXT, firstName TEXT);
CREATE TABLE itemCreators (itemID INT, creatorID INT, orderIndex INT);
CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INT, note TEXT);
CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INT,
                              contentType TEXT, path TEXT);
CREATE TABLE itemAnnotations (itemID INTEGER PRIMARY KEY, parentItemID INT, type TEXT,
                              text TEXT, comment TEXT, pageLabel TEXT, sortIndex TEXT);
CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT,
                          parentCollectionID INT, libraryID INT, key TEXT,
                          version INT, synced INT);
CREATE TABLE collectionItems (collectionID INT, itemID INT);
""")

    types = ["journalArticle", "conferencePaper", "note", "attachment"]
    c.executemany("INSERT INTO itemTypes VALUES (?,?)", list(enumerate(types, 1)))
    fields = ["title", "date", "publicationTitle", "DOI", "abstractNote"]
    c.executemany("INSERT INTO fields VALUES (?,?)", list(enumerate(fields, 1)))
    fmap = {n: i for i, n in enumerate(fields, 1)}

    # item 1：正常期刊论文，附件文件存在
    # item 2：期刊论文，附件文件刻意缺失（应保留 storage: 前缀）
    # item 3：会议论文，已进回收站（应被排除）
    # item 4：独立笔记条目（parentItemID 为空）
    c.executemany("INSERT INTO items VALUES (?,?,?,?)", [
        (1, 1, "AAAA1111", "2023-01-01"), (2, 1, "BBBB2222", "2023-02-01"),
        (3, 2, "CCCC3333", "2023-03-01"), (4, 3, "DDDD4444", "2023-04-01"),
        (5, 4, "EEEE5555", "2023-05-01"),   # 附件条目
        (6, 4, "FFFF6666", "2023-06-01"),   # 附件条目（文件缺失）
    ])
    c.execute("INSERT INTO deletedItems VALUES (3)")

    vals = ["Aviation Ontology Construction", "2023-01-15", "Journal of Manufacturing Systems",
            "10.1000/aaa", "Ontology reuse for aerospace assembly."]
    c.executemany("INSERT INTO itemDataValues VALUES (?,?)", list(enumerate(vals, 1)))
    c.executemany("INSERT INTO itemData VALUES (?,?,?)", [
        (1, fmap["title"], 1), (1, fmap["date"], 2), (1, fmap["publicationTitle"], 3),
        (1, fmap["DOI"], 4), (1, fmap["abstractNote"], 5),
    ])
    c.executemany("INSERT INTO creators VALUES (?,?,?)",
                  [(1, "Zhang", "San"), (2, "Li", "Si")])
    c.execute("INSERT INTO itemCreators VALUES (1,1,0)")
    c.execute("INSERT INTO itemCreators VALUES (1,2,1)")   # 第二作者：验证保序且不重复
    c.execute("INSERT INTO itemNotes VALUES (?,?,?)",
              (1, 1, "<p>Key insight: ontology reuse cuts modeling cost.</p>"))

    c.execute("INSERT INTO itemDataValues VALUES (7,'Tolerance Annotation Review')")
    c.execute("INSERT INTO itemData VALUES (2,?,7)", (fmap["title"],))
    c.execute("INSERT INTO itemDataValues VALUES (8,'10.1000/bbb')")
    c.execute("INSERT INTO itemData VALUES (2,?,8)", (fmap["DOI"],))

    c.execute("INSERT INTO itemAttachments VALUES (?,?,?,?)", (5, 1, "application/pdf", "storage:paper_ok.pdf"))
    c.execute("INSERT INTO itemAttachments VALUES (?,?,?,?)", (6, 2, "application/pdf", "storage:missing.pdf"))
    c.execute("INSERT INTO itemAnnotations VALUES (?,?,?,?,?,?,?)",
              (1, 5, "highlight", "tolerance is critical", "check this", "5", "00001"))

    # item 4 是独立笔记条目：note 表里 parentItemID 为空
    c.execute("INSERT INTO itemNotes VALUES (?,?,?)",
              (4, None, "<p>Standalone note about HugeGraph migration.</p>"))

    # 分类：两条，用于验证 list_collections 的 sqlite 来源与 resolve_collections 解析。
    # 注意其中 "Ontology Papers"（IN7CD4ST）刻意**只存在于 sqlite**——本地 API 索引
    # 会滞后于库内实际状态，list_collections 必须取两来源并集才能拿到它（回归用例）。
    c.executemany("INSERT INTO collections VALUES (?,?,?,?,?,?,?)", [
        (1, "Thesis References", None, 1, "TU38AQXQ", 1, 1),
        (2, "Ontology Papers", None, 1, "IN7CD4ST", 1, 1),
    ])
    c.executemany("INSERT INTO collectionItems VALUES (?,?)", [(1, 1), (2, 2)])

    con.commit()
    con.close()

    # 附件目录：一份存在，一份刻意不建
    storage = os.path.join(zd, "storage")
    ok_dir = os.path.join(storage, "EEEE5555")
    os.makedirs(ok_dir, exist_ok=True)
    with open(os.path.join(ok_dir, "paper_ok.pdf"), "wb") as f:
        f.write(b"%PDF-1.4\n% fixture\n")

    return zd


def build_all(target):
    os.makedirs(target, exist_ok=True)
    write_payloads(target)
    build_zotero(target)
    # 落一个构建标记：harness 靠它判断夹具是否比源码旧（目录 mtime 不可靠，
    # makedirs(exist_ok=True) 不会更新已存在目录的时间戳）
    stamp = os.path.join(target, ".built")
    with open(stamp, "w", encoding="utf-8", newline="\n") as f:
        f.write("aviation-literature test fixtures\n")
    return target


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法：python make_fixtures.py <target-dir>")
        sys.exit(2)
    out = build_all(os.path.abspath(sys.argv[1]))
    print(f"夹具已生成：{out}")
