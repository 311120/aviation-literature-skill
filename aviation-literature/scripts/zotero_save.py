#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把检索结果自动存入 Zotero（条目 + PDF 全文附件 + 可选分类）。绝不直接写 zotero.sqlite。

用法：
  python zotero_save.py --json 文献库/batch.json --items 2,5   # 入库指定编号
  python zotero_save.py --json 文献库/batch.json --all          # 入库全部
  python zotero_save.py --authorize                             # 只做写入授权
  python zotero_save.py --list-collections                      # 列出库中分类
  python zotero_save.py --json 文献库/batch.json --all \
      --collection AircraftAssemblyToleranceOntology            # 入库并归入指定分类

输入是 search_papers.py --json 导出的文件。双路径自动择优：
  A. Zotero 正在运行且本地 API 可写：先按 DOI/标题查重，再 POST 创建条目，
     条目建成后继续把 PDF 全文作为附件上传（三步协议见下）。写入需三步就绪
     （缺一即被拒，脚本会自动探测并降级）：
       1) Zotero 设置→高级 勾选「允许其他应用与此电脑上的 Zotero 通信」——否则读都不通；
       2) 写请求必须带 Zotero-Server-ID 头（从 GET 响应头取），否则返回
          428 Precondition Required；
       3) 首次写入需先 POST /api/local/authorize 换取 API Key，
          该请求会**在 Zotero 界面弹出授权窗口，需用户点「允许」**。
          Key 有效期受 Zotero 的「记住」选项影响，脚本会把换到的 Key
          缓存在 <数据目录>/skill-import/.zotero_api_key 供后续批次复用。
  B. 上面任一步不满足：PDF 与 batch.ris 落到 <Zotero数据目录>/skill-import/，
     由用户在 Zotero 中 文件→导入 一次完成。
     **注意：RIS 格式不含分类信息**，走这条路时分类归属需用户手工拖入。

PDF 附件上传的三步协议（Zotero 7 本地 API，已实测）：
  1. POST /api/users/0/items/{附件Key}/file
     body: md5=&filename=&filesize=&mtime=0（form-urlencoded），带 If-None-Match: *
     → 返回 {url, uploadKey}
  2. POST <返回的 url>，body 为 PDF 原始字节，Content-Type: application/pdf
  3. POST /api/users/0/items/{附件Key}/file，body: upload=<uploadKey>
附件条目本身用 POST /api/users/0/items 创建（itemType=attachment,
linkMode=imported_url, parentItem=<父条目Key>）。

分类归属（v1.4.0）：条目创建时在请求体带 "collections": ["<8 位分类 Key>"] 即归入该分类。
分类 Key 是 8 位大写字母数字（如 IN7CD4ST），不是数字 collectionID。用 --list-collections
查看，用 --collection 指定（接受全名 / 8 位 Key / 唯一名称片段三种写法）。

附件上传失败**不影响条目**，但脚本会如实报「PDF 未挂上」并保留 skill-import/
里的文件供手工拖拽——绝不谎称已附加。

退出码：0 正常完成；1 输入非法或受控失败；2 命令行用法错误。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_papers import download_pdf_ex, to_ris_entry  # noqa: E402
from zotero_query import find_data_dir, open_ro_copy  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_API = "http://localhost:23119/api/users/0/items"
LOCAL_API_BASE = "http://localhost:23119/api"
APP_NAME = "aviation-literature"
UA = "zotero-save-script"

_server_id_cache = None
_api_key_cache = None


class AuthRequired(RuntimeError):
    """需要用户授权/开关未开——重试无用，应立刻降级并如实告知。

    与网络抖动、服务端 5xx 区分开，避免对不可自愈的失败做无意义的重试。
    """


def _server_id(timeout=3):
    """取 Zotero 本地 API 的 Server-ID。

    Zotero 7 为防跨站请求伪造，要求写请求（POST/PATCH/DELETE）带上
    Zotero-Server-ID 头，否则返回 428 Precondition Required
    （响应体 "Zotero-Server-ID not provided"）。该值由服务端随机生成，
    从任意 GET 响应的同名响应头里取。取不到时返回空串，由调用方决定降级。
    """
    global _server_id_cache
    if _server_id_cache is not None:
        return _server_id_cache
    sid = ""
    try:
        req = urllib.request.Request(LOCAL_API + "?limit=1",
                                     headers={"User-Agent": "zotero-save-script"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            sid = resp.headers.get("Zotero-Server-ID", "") or ""
    except Exception:
        sid = ""
    _server_id_cache = sid
    return sid


def api_up(timeout=3):
    """探测 Zotero 本地 API 是否可用（读通即可）。"""
    try:
        req = urllib.request.Request(LOCAL_API + "?limit=1",
                                     headers={"User-Agent": "zotero-save-script"})
        urllib.request.urlopen(req, timeout=timeout).read()
        return True
    except Exception:
        return False


def api_writable(timeout=3):
    """本地 API 是否可写：读通且能取到 Server-ID。取不到 ID 时写入必被拒。"""
    return api_up(timeout=timeout) and bool(_server_id(timeout=timeout))


def _key_file(data_dir):
    return os.path.join(data_dir, "skill-import", ".zotero_api_key")


def _load_key(data_dir):
    try:
        with open(_key_file(data_dir), encoding="utf-8") as f:
            return (json.load(f) or {}).get("key") or ""
    except Exception:
        return ""


def _save_key(data_dir, key):
    try:
        path = _key_file(data_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"key": key, "app": APP_NAME}, f, ensure_ascii=False)
    except Exception:
        pass


def request_key(data_dir, timeout=60, reporter=None, force=False):
    """向 Zotero 申请本地 API Key。

    此调用会**在 Zotero 界面弹出授权窗口**，阻塞直到用户点「允许」或拒绝，
    故 timeout 给得较长。成功返回 key 并落盘缓存；失败返回空串。

    force=True 时跳过缓存，直接重新申请（缓存的 Key 被服务端拒绝后使用）。
    """
    global _api_key_cache
    sid = _server_id()
    if not sid:
        return ""
    if reporter:
        reporter("正在向 Zotero 申请本地写入授权——请到 Zotero 窗口点击「允许」")
        try:
            sys.stdout.flush()
        except Exception:
            pass
    payload = json.dumps({"appName": APP_NAME, "keyName": "skill-import"}).encode("utf-8")
    req = urllib.request.Request(
        LOCAL_API_BASE + "/local/authorize", data=payload, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "Zotero-Server-ID": sid, "Zotero-API-Version": "3"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            key = (json.loads(resp.read()) or {}).get("key") or ""
    except Exception:
        return ""
    if key:
        _save_key(data_dir, key)
        _api_key_cache = key
    return key


def _api_key(data_dir, reporter=None):
    """取可用的 API Key：先读缓存，取不到再申请。"""
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    key = _load_key(data_dir)
    if not key:
        key = request_key(data_dir, reporter=reporter)
    _api_key_cache = key
    return key


def api_key_refresh(data_dir, reporter=None):
    """缓存 Key 被服务端拒绝（401）后重新授权一次。返回新 Key 或空串。

    单独抽出来是因为条目创建与附件上传都会遇到 401，两处都要能刷新。
    """
    global _api_key_cache
    _api_key_cache = None
    _save_key(data_dir, "")
    return request_key(data_dir, reporter=reporter, force=True) or ""



def norm_title(t):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (t or "").lower())


def _already_in_ris(paper, existing):
    """同一文献是否已在此前批次的 RIS 里（按 DOI / 链接 / 标题行识别）。"""
    if not existing:
        return False
    candidates = []
    if paper.get("doi"):
        candidates.append(f"DO  - {paper['doi']}")
    if paper.get("link"):
        candidates.append(f"UR  - {paper['link']}")
    if paper.get("title"):
        candidates.append(f"TI  - {paper['title']}")
    return any(c in existing for c in candidates)


def load_existing(data_dir):
    """馆藏已有的 DOI 与规范化标题集合，用于查重。读 sqlite 副本，不碰原库。"""
    dois, titles = set(), set()
    try:
        with open_ro_copy(data_dir) as con:
            for field, sink in (("DOI", dois), ("title", titles)):
                for (value,) in con.execute(
                        "SELECT v.value FROM itemData d "
                        f"JOIN fields f ON f.fieldID=d.fieldID AND f.fieldName='{field}' "
                        "JOIN itemDataValues v ON v.valueID=d.valueID"):
                    if field == "DOI":
                        sink.add((value or "").lower())
                    else:
                        sink.add(norm_title(value))
    except Exception as e:
        # 查重不可用时必须明说，否则静默跳过查重会造成重复入库
        print(f"[警告：无法读取馆藏数据库做查重（{type(e).__name__}），"
              "本次入库可能产生重复条目]", file=sys.stderr)
        return set(), set()
    return dois, titles


def split_author(name):
    """把作者字符串拆成 Zotero 的 lastName / firstName。

    必须同时认两种形态，否则会**把姓名写反**：
      - "Zhang Wei"          空格分隔，姓在后（OpenAlex / Semantic Scholar 形态）
      - "Smith, John"        逗号分隔，姓在前（**Crossref 形态**）
      - "van der Berg, Anna" 逗号前是复姓
      - "李雷"                单节，整串当姓氏

    为什么要处理逗号：本 skill 自己的 `search_papers.parse_crossref()` 产出的就是
    "family given"（即 "姓 名" 带逗号）形态，用 `--source crossref` 检索后入库时，
    早先只按空格切分会把 "Smith, John" 解析成 firstName="Smith," / lastName="John"，
    即**姓名颠倒且姓氏带逗号**，直接写坏用户 Zotero 库里的作者字段。
    """
    raw = (name or "").strip()
    if not raw:
        return None
    if "," in raw:
        # 逗号形态：至多切成「姓, 名」两段；多余逗号（如 "Smith, Jr., John"）退回空格规则
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 2 and parts[0] and parts[1]:
            return {"creatorType": "author", "firstName": parts[1], "lastName": parts[0]}
        # 三节以上常见于 "姓, 后缀, 名"：保留原节序，仅把首节当姓氏
        if len(parts) >= 3 and parts[0]:
            given = " ".join(p for p in parts[2:] if p)
            return {"creatorType": "author",
                    "firstName": " ".join(x for x in (parts[1], given) if x),
                    "lastName": parts[0]}
        raw = " ".join(p for p in parts if p)
    parts = raw.split()
    if not parts:
        return None
    if len(parts) == 1:
        return {"creatorType": "author", "firstName": "", "lastName": parts[0]}
    return {"creatorType": "author",
            "firstName": " ".join(parts[:-1]), "lastName": parts[-1]}


# --------------------------------------------------------------------------
# 分类（collections）
# --------------------------------------------------------------------------

def list_collections(data_dir, reporter=None):
    """列出库中全部分类，返回 [(名称, Key)] 按名称排序。

    **两个来源取并集，不能只取其一**：实测本机本地 API 返回的分类比库里实际少
    （新建的分类短期内不在 API 索引里，API 只回了 2 个而库里有 3 个）。因此
    不能写成「API 优先、失败才回退 sqlite」——那会漏掉新建的分类。
    同一 Key 以 API 返回的名称为准（若有）。

    reporter：可选回调，用来**如实汇报来源读失败的原因**。两个来源都失败时
    绝不能只说「库里没有分类」——那是把「读不到」说成「没有」，与本 skill
    「依赖不可用不得静默失败」的约定相悖（这两处早先是 `except Exception: pass`）。
    """
    api_sets, db_sets = {}, {}
    failures = []
    try:
        req = urllib.request.Request(LOCAL_API_BASE + "/users/0/collections",
                                     headers={"Zotero-API-Version": "3"}, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            for c in json.loads(resp.read()):
                nm = (c.get("data") or {}).get("name") or ""
                if nm and c.get("key"):
                    api_sets[c["key"]] = nm
    except Exception as e:                      # noqa: BLE001
        failures.append(("本地 API", type(e).__name__, str(e)[:150]))
    try:
        # open_ro_copy 是上下文管理器（内部用 yield），必须 with，
        # 写成 con = open_ro_copy(...) 会拿到生成器对象，异常被静默吞掉
        with open_ro_copy(data_dir) as con:
            cur = con.cursor()
            cur.execute("SELECT collectionName, key FROM collections")
            db_sets = {r[1]: r[0] for r in cur.fetchall() if r[0] and r[1]}
    except Exception as e:                      # noqa: BLE001
        failures.append(("sqlite 只读副本", type(e).__name__, str(e)[:150]))
    if reporter and failures:
        for src, exc, msg in failures:
            reporter(f"[分类来源读取失败] {src}：{exc}：{msg}")
    merged = dict(db_sets)
    merged.update(api_sets)
    return sorted(((n, k) for k, n in merged.items()), key=lambda t: t[0])


_KEY_RE = re.compile(r"^[A-Z0-9]{8}$")


def resolve_collections(spec, data_dir, reporter=None):
    """把 --collection 的写法解析成分类 Key 列表，去重并保持输入顺序。

    接受三种写法：
      - 分类全名（精确，忽略大小写与首尾空白）
      - 8 位分类 Key（如 IN7CD4ST）
      - 唯一名称片段（子串匹配；命中多个视为多义，报错并列出候选）

    也支持逗号分隔的多个分类。未命中或多义时抛 ValueError，报错里列出候选分类，
    让调用方能直接告诉用户「你可能是想要这几个」。
    reporter 透传给 list_collections()，让来源读取失败的原因能被如实打印。
    """
    if not spec:
        return []
    known = list_collections(data_dir, reporter=reporter)
    out = []
    for raw in spec.split(","):
        want = raw.strip()
        if not want:
            continue
        low = want.lower()
        hit = ""
        exact = [k for n, k in known if n.lower() == low]
        if exact:
            hit = exact[0]
        elif _KEY_RE.match(want.upper()) and any(k == want.upper() for _, k in known):
            hit = want.upper()
        else:
            partial = [(n, k) for n, k in known if low in n.lower()]
            if len(partial) == 1:
                hit = partial[0][1]
            elif len(partial) > 1:
                names = "｜".join(f"{n}（{k}）" for n, k in partial)
                raise ValueError(f"分类「{want}」有多个匹配：{names}。请写全名或 8 位 Key。")
        if not hit:
            avail = "｜".join(f"{n}（{k}）" for n, k in known) or "（库中暂无分类）"
            raise ValueError(f"找不到分类「{want}」。现有分类：{avail}")
        if hit not in out:
            out.append(hit)
    return out


def _write_headers(data_dir, reporter=None, allow_authorize=True):
    """构造写请求头。缺 Server-ID 或 Key 时抛 AuthRequired（无法靠重试解决）。

    allow_authorize=False 时只用缓存的 Key，不触发新的授权弹窗——批量入库
    中途弹第二次窗会让用户困惑，第一次已经弹过了。
    """
    sid = _server_id()
    if not sid:
        raise AuthRequired("未取到 Zotero-Server-ID，本地 API 不可写")
    if allow_authorize:
        key = _api_key(data_dir, reporter=reporter)
    else:
        key = _api_key_cache or _load_key(data_dir)
    if not key:
        raise AuthRequired("未取得 Zotero 本地 API 授权（需在 Zotero 窗口点「允许」）")
    return {"Content-Type": "application/json",
            "User-Agent": UA,
            "Zotero-API-Version": "3",
            "Zotero-Server-ID": sid,
            "Authorization": "Bearer " + key}


def api_create(paper, data_dir, reporter=None, collections=None):
    """POST 创建条目。成功返回 Zotero Key，失败抛异常。

    collections 是分类 Key 列表；传入即让条目建出来就落在这些分类下
    （请求体的 collections 字段）。为空则落在「我的文库」根下。

    Key 被拒（401）时刷新一次并重试；仍失败则如实抛出，由调用方降级。
    """
    item = {
        "itemType": "journalArticle",
        "title": paper["title"],
        "creators": [c for c in (split_author(a) for a in (paper.get("authors") or [])[:20]) if c],
        "DOI": paper.get("doi") or "",
        "url": paper.get("link") or "",
        "abstractNote": paper.get("abstract") or "",
        "tags": [],
    }
    if paper.get("venue"):
        item["publicationTitle"] = paper["venue"]
    if paper.get("year") and paper["year"] != "?":
        item["date"] = str(paper["year"])
    if collections:
        item["collections"] = list(collections)

    headers = _write_headers(data_dir, reporter=reporter)
    for attempt in (1, 2):
        req = urllib.request.Request(
            LOCAL_API, data=json.dumps([item]).encode("utf-8"), method="POST",
            headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            ok = data.get("successful") or {}
            return (ok.get("0") or {}).get("key", "")
        except urllib.error.HTTPError as exc:
            # 缓存的 key 失效（过期/Zotero 重启）：清掉缓存重授权一次
            if exc.code in (401, 403) and attempt == 1:
                key = api_key_refresh(data_dir, reporter=reporter)
                if not key:
                    raise AuthRequired("Zotero 本地 API 授权失效，且重新申请未成功") from None
                headers["Authorization"] = "Bearer " + key
                continue
            raise


# --------------------------------------------------------------------------
# PDF 附件上传（Zotero 7 本地 API 的三步协议）
# --------------------------------------------------------------------------

def _md5_file(path, chunk=1 << 20):
    """分块算 MD5，避免把大 PDF 整个读进内存。返回小写十六进制摘要。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _upload_target(parent_key, filename, filesize, md5, headers):
    """第 1 步：向 Zotero 声明要上传的文件，换回上传地址与 uploadKey。

    body 是 form-urlencoded 的 md5/filename/filesize/mtime，缺 MD5 会被
    400 拒绝（服务端要它做完整性校验）。带 If-None-Match: * 表示这是一次
    全新上传而非续传。
    """
    url = f"{LOCAL_API}/{parent_key}/file"
    body = urllib.parse.urlencode({
        "md5": md5, "filename": filename, "filesize": filesize, "mtime": 0,
    }).encode("utf-8")
    h = dict(headers)
    h["Content-Type"] = "application/x-www-form-urlencoded"
    h["If-None-Match"] = "*"
    h["Zotero-API-Version"] = "3"
    req = urllib.request.Request(url, data=body, method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            info = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 412:
            # If-None-Match: * 只在「服务端尚无该文件」时放行；已存在或 MD5 不符会 412
            raise RuntimeError(
                "Zotero 拒绝本次上传（412 Precondition Failed）："
                "该附件已存在同名文件，或本地文件与声明的 md5 不符") from None
        raise
    return (info or {}).get("url", ""), (info or {}).get("uploadKey", "")


def _upload_bytes(url, path, headers):
    """第 2 步：把 PDF 原始字节 POST 到 Zotero 给的临时上传地址。"""
    with open(path, "rb") as f:
        data = f.read()
    h = dict(headers)
    h["Content-Type"] = "application/pdf"
    h["Content-Length"] = str(len(data))
    h["Zotero-API-Version"] = "3"
    req = urllib.request.Request(url, data=data, method="POST", headers=h)
    with urllib.request.urlopen(req, timeout=180) as resp:
        return getattr(resp, "status", 200)


def _upload_register(parent_key, upload_key, headers):
    """第 3 步：登记 uploadKey，Zotero 才把文件归档到 storage/。"""
    url = f"{LOCAL_API}/{parent_key}/file"
    h = dict(headers)
    h["Content-Type"] = "application/x-www-form-urlencoded"
    h["Zotero-API-Version"] = "3"
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode({"upload": upload_key}).encode("utf-8"),
        method="POST", headers=h)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return getattr(resp, "status", 200)


def api_attach_pdf(parent_key, pdf_path, data_dir, reporter=None):
    """把本地 PDF 作为附件挂到已有条目上。成功返回附件条目的 Zotero Key。

    三步缺一不可，见 references/zotero.md。任何一步失败都如实抛出，
    调用方必须把「附件没挂上」告诉用户，并保留 PDF 兜底，不得谎报成功。
    """
    if not parent_key or not pdf_path or not os.path.isfile(pdf_path):
        raise ValueError("缺少父条目 Key 或 PDF 文件不存在")
    filename = os.path.basename(pdf_path)
    filesize = os.path.getsize(pdf_path)
    md5 = _md5_file(pdf_path)

    # 附件条目先建：linkMode=imported_url 让 Zotero 把文件收进 storage/
    att_item = {
        "itemType": "attachment",
        "linkMode": "imported_url",
        "parentItem": parent_key,
        "title": filename,
        "url": "",
        "contentType": "application/pdf",
        "tags": [],
    }
    headers = _write_headers(data_dir, reporter=reporter)
    for attempt in (1, 2):
        req = urllib.request.Request(
            LOCAL_API, data=json.dumps([att_item]).encode("utf-8"), method="POST",
            headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            att_key = ((data.get("successful") or {}).get("0") or {}).get("key", "")
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and attempt == 1:
                key = api_key_refresh(data_dir, reporter=reporter)
                if not key:
                    raise AuthRequired("Zotero 本地 API 授权失效，无法创建附件条目") from None
                headers["Authorization"] = "Bearer " + key
                continue
            raise
    if not att_key:
        raise RuntimeError("Zotero 未返回附件条目 Key")

    up_url, upload_key = _upload_target(att_key, filename, filesize, md5, headers)
    if not up_url or not upload_key:
        raise RuntimeError("未取到上传地址或 uploadKey")
    _upload_bytes(up_url, pdf_path, headers)
    _upload_register(att_key, upload_key, headers)
    return att_key


# PDF 未获取到时，逐条说明**真实原因**——不能笼统说「无开放获取全文」：
#   有 pdf_url 但下载失败（403/网络/写盘）与「该文献本来就没有免费 PDF」是两件事。
_PDF_ISSUE_LABEL = {
    "no_url": "该文献无开放获取 PDF 链接（源站没有免费全文）",
    "not_pdf": "下载被拒：响应不是 PDF（出版商直链常 403），可手动获取后拖入",
    "error": "下载失败（网络或写盘错误），可重试或手动获取",
    "staged_ok": "PDF 已存入 skill-import",
    "bad_local": "JSON 里的 local_pdf 路径不存在，且无可用 pdf_url",
}


def stage_pdf(paper, import_dir):
    """确保 PDF 落在 import_dir。返回 (本地路径, 状态)。

    状态：ok / no_url / not_pdf / error / bad_local。
    保留 download_pdf() 的兼容行为：成功给路径、失败给空串。
    """
    local = paper.get("local_pdf") or ""
    if local and os.path.isfile(local):
        if os.path.dirname(os.path.abspath(local)) != os.path.abspath(import_dir):
            dest = os.path.join(import_dir, os.path.basename(local))
            try:
                shutil.move(local, dest)
                return dest, "ok"
            except Exception:
                return local, "ok"          # 挪不动就留在原处，文件本身可用
        return local, "ok"
    if paper.get("pdf_url"):
        return download_pdf_ex({"pdf": paper["pdf_url"], "year": paper.get("year", "?"),
                                "authors": paper.get("authors") or ["Unknown"],
                                "title": paper["title"]}, import_dir)
    return "", ("bad_local" if local else "no_url")


def load_batch(path):
    """读取 --json 文件。返回条目列表；文件缺失或格式非法抛 ValueError。"""
    if not os.path.isfile(path):
        raise ValueError(f"找不到输入文件：{path}")
    try:
        with open(path, encoding="utf-8-sig") as f:
            papers = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"输入文件不是合法 JSON（{e.msg}，第 {e.lineno} 行）") from None
    if not isinstance(papers, list):
        raise ValueError("输入 JSON 的顶层结构应为数组（search_papers.py --json 导出的格式）")
    return [p for p in papers if isinstance(p, dict)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="把检索结果自动存入 Zotero")
    ap.add_argument("--json", dest="json", metavar="FILE",
                    help="search_papers.py --json 导出的结果文件（--authorize / --list-collections 时可省）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--items", help="要入库的编号，如 2,5（对应 JSON 里的 index）")
    g.add_argument("--all", action="store_true", help="入库全部条目")
    g.add_argument("--authorize", action="store_true",
                   help="只申请 Zotero 本地 API 写入授权（会在 Zotero 弹窗），不读 --json")
    g.add_argument("--list-collections", action="store_true", dest="list_collections",
                   help="列出 Zotero 全部分类（名称 + Key），不执行入库")
    ap.add_argument("--collection", metavar="NAME|KEY",
                    help="入库到指定分类：接受分类全名 / 8 位 Key / 唯一名称片段；"
                         "多个用逗号分隔。用 --list-collections 查看可用分类")
    args = ap.parse_args(argv)

    if args.list_collections:
        data_dir = find_data_dir()
        if not data_dir:
            print("未找到 Zotero 数据目录（zotero.sqlite）。", file=sys.stderr)
            return 1
        problems = []
        sets = list_collections(data_dir, reporter=problems.append)
        if not sets:
            # 读失败 ≠ 库里没有分类：把真实原因如实说出来，并按受控失败退出
            print("未读到任何分类——两个来源都读取失败：", file=sys.stderr)
            for line in problems or ["（未捕获到具体异常）"]:
                print("  " + line, file=sys.stderr)
            print("请确认 Zotero 正在运行（或关闭后重试），并检查数据目录是否可读。",
                  file=sys.stderr)
            return 1
        if problems:
            for line in problems:
                print(line, file=sys.stderr)
        print(f"# Zotero 分类（{len(sets)} 个）\n")
        for name, key in sets:
            print(f"- {name}    [{key}]")
        return 0

    if args.authorize:
        data_dir = find_data_dir()
        if not data_dir:
            print("未找到 Zotero 数据目录（zotero.sqlite）。", file=sys.stderr)
            return 1
        if not api_up():
            print("Zotero 本地 API 未响应。请先启动 Zotero，并在"
                  "设置→高级 勾选「允许其他应用与此电脑上的 Zotero 通信」。", file=sys.stderr)
            return 1
        if not _server_id():
            print("未能取到 Zotero-Server-ID，本地 API 不支持写入。", file=sys.stderr)
            return 1
        key = request_key(data_dir, reporter=lambda m: print(m))
        if key:
            print(f"授权成功，Key 已缓存到 {_key_file(data_dir)}。后续入库将直接建条目。")
            return 0
        print("授权未完成（在 Zotero 窗口点「允许」后重试）。仍可用 RIS 导入路径。",
              file=sys.stderr)
        return 1

    if not args.json:
        print("用法：--json FILE --items 2,5 ／ 或 --json FILE --all ／ 或 --authorize "
              "／ 或 --list-collections", file=sys.stderr)
        return 2

    try:
        papers = load_batch(args.json)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.all:
        chosen = [p for p in papers if p.get("title")]
    else:
        try:
            want = {int(x) for x in re.split(r"[,\s]+", args.items.strip()) if x}
        except ValueError:
            print("--items 要是编号列表，如 2,5", file=sys.stderr)
            return 1
        chosen = [p for p in papers if p.get("index") in want and p.get("title")]
    if not chosen:
        print("JSON 中没有匹配的编号。", file=sys.stderr)
        return 1

    data_dir = find_data_dir()
    if not data_dir:
        print("未找到 Zotero 数据目录（zotero.sqlite），无法入库。", file=sys.stderr)
        return 1
    import_dir = os.path.join(data_dir, "skill-import")
    try:
        os.makedirs(import_dir, exist_ok=True)
    except Exception as e:
        print(f"无法创建入库暂存目录 {import_dir}（{type(e).__name__}）。", file=sys.stderr)
        return 1

    dois, titles = load_existing(data_dir)

    # 分类在入库前一次性解析：名字写错时不必等建完条目才发现
    try:
        target_sets = resolve_collections(args.collection, data_dir,
                                          reporter=lambda m: print(m, file=sys.stderr))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if target_sets:
        names = "｜".join(n for n, k in list_collections(data_dir) if k in target_sets)
        print(f"[入库后归入分类：{names}]")

    use_api = api_writable()
    if use_api:
        print("[Zotero 本地 API 可写：自动建条目，并尝试把 PDF 全文作为附件上传]")
    elif api_up():
        print("[Zotero 本地 API 只读可用（取不到 Server-ID），走 RIS 导入路径]")

    results = []  # (paper, outcome, detail)
    for p in chosen:
        doi = (p.get("doi") or "").lower()
        nt = norm_title(p["title"])
        if (doi and doi in dois) or (nt and nt in titles):
            results.append((p, "skip", "馆藏已有"))
            continue
        local, pdf_status = stage_pdf(p, import_dir)
        # PDF 没拿到时，用**真实原因**而不是笼统的「PDF 未能获取」
        local_detail = local or _PDF_ISSUE_LABEL.get(pdf_status, "PDF 未能获取")
        if use_api:
            try:
                key = api_create(p, data_dir, collections=target_sets)
            except AuthRequired as e:
                # 授权/开关问题重试无用：本批余下的全部转 RIS，不再反复弹窗
                print(f"[本地 API 不可写：{e}，本批剩余条目转 RIS 导入路径]")
                results.append((p, "staged", local_detail))
                use_api = False
                continue
            except Exception as e:
                print(f"[API 建条目失败（{type(e).__name__}），降级为 RIS 导入]")
                results.append((p, "staged", local_detail))
                continue

            if not key:
                print(f"[API 未成功建立条目：{p['title'][:50]}，降级为 RIS 导入]")
                results.append((p, "staged", local_detail))
                continue

            # 条目建好了：接着把全文 PDF 附上去（用户明确要求入库不能只建条目）
            pdf = local
            if not pdf:
                # 检索时没下 PDF：这里补一次，有 pdf_url 才可能成功
                if p.get("pdf_url"):
                    print(f"[该条目前无本地 PDF，尝试按链接补下：{p['title'][:50]}]")
                    pdf, pdf_status = stage_pdf(p, import_dir)
                else:
                    print(f"[该条目无开放获取 PDF 链接，跳过附件：{p['title'][:50]}]")

            if not pdf:
                results.append((p, "api_nopdf",
                                f"Key：{key}｜仅建条目，"
                                f"{_PDF_ISSUE_LABEL.get(pdf_status, 'PDF 未获取')}"))
            else:
                try:
                    att_key = api_attach_pdf(key, pdf, data_dir)
                    results.append((p, "api",
                                    f"Key：{key}｜PDF 已挂为附件："
                                    f"{os.path.basename(pdf)}（附件 Key：{att_key}）"))
                except Exception as e:
                    # 附件失败不影响条目，但必须如实说明并保留 skill-import 兜底
                    results.append((p, "api+pdf_fail",
                                    f"Key：{key}｜PDF 未挂上（{type(e).__name__}: {e}）"
                                    f"｜PDF 仍在 {pdf}，可在 Zotero 中拖到条目上"))
            continue
        results.append((p, "staged", local_detail))

    ris_items = [p for p, outcome, _ in results if outcome == "staged"]
    ris_fallback_error = ""
    if ris_items:
        ris_path = os.path.join(import_dir, "batch.ris")
        existing = ""
        if os.path.isfile(ris_path):
            try:
                with open(ris_path, encoding="utf-8") as f:
                    existing = f.read()
            except Exception:
                existing = ""
        # 追加合并而不是覆盖：此前批次待导入的题录不能丢，否则其 PDF 成孤儿
        new_entries = [to_ris_entry(p) for p in ris_items
                       if not _already_in_ris(p, existing)]
        if new_entries:
            head = existing.rstrip() + "\n\n" if existing.strip() else ""
            # 写 RIS 是**兜底路径本身**，失败必须受控报出并给出替代做法：
            # 早先此处没有 try，磁盘/权限问题会以裸 traceback 结束（违反退出码契约），
            # 且「文件→导入」的提示根本不会打印，用户拿不到任何指引。
            try:
                with open(ris_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(head + "\n\n".join(new_entries) + "\n")
            except OSError as e:
                ris_fallback_error = f"{type(e).__name__}: {e}"
                print(f"[RIS 兜底写入失败] {ris_path}（{ris_fallback_error}）",
                      file=sys.stderr)
                print("  该目录不可写（权限/只读介质/被占用）。请改用工作区目录，"
                      "例如：python search_papers.py ... --ris 文献库/batch.ris "
                      "然后在 Zotero 中 文件→导入；或把本目录的 PDF 手工拖进 Zotero。",
                      file=sys.stderr)

    print(f"\n# 入库结果（Zotero 数据目录：{data_dir}）\n")
    STATUS = {"skip": "跳过",
              "api": "已建立条目并挂上 PDF 全文",
              "api_nopdf": "已建立条目（该文献无开放获取全文，未挂附件）",
              "api+pdf_fail": "已建立条目，但 PDF 未能挂为附件",
              "staged": "已存入 skill-import，等待导入"}
    for p, outcome, detail in results:
        print(f"- [{p.get('index')}] {str(p['title'])[:70]}\n    {STATUS[outcome]}｜{detail}")
    print()
    if any(o == "api" for _, o, _ in results):
        print("提示：附件已上传到 Zotero，条目下应能看到 PDF，可直接双击阅读。")
    if any(o == "api_nopdf" for _, o, _ in results):
        print("提示：有条目建好了但没有全文。逐条看上面的原因——"
              "「无开放获取 PDF 链接」是该文献在源站没有免费全文（可用 DOI 去出版商页面或图书馆拿，"
              "再拖进 Zotero）；「下载被拒/下载失败」则是**本来有链接但没拿下来**，可重试或手动获取。")
    if any(o == "api+pdf_fail" for _, o, _ in results):
        print("提示：有条目没挂上 PDF（上传被拒或网络中断）。"
              "文件仍在 skill-import/，可在 Zotero 中手工拖到对应条目上。")
    if ris_items:
        if ris_fallback_error:
            print("提示：RIS 兜底文件**没写出去**（原因见上）。请改用工作区目录生成 RIS："
                  "python search_papers.py \"检索词\" --ris 文献库/batch.ris，"
                  "再在 Zotero 中 文件→导入（勾选去重）；PDF 可手工拖到条目上。")
        else:
            print(f"提示：在 Zotero 中 文件→导入 {os.path.join(import_dir, 'batch.ris')}"
                  "（勾选去重），再把同目录 PDF 拖到对应条目。")
        if target_sets:
            print("提示：**RIS 路径不带分类信息**——上面走 RIS 的条目导入后落在「我的文库」根下，"
                  "需要手工拖进目标分类。")
    if target_sets and any(o.startswith("api") for _, o, _ in results):
        print("提示：条目创建时已带上分类字段。**要确认归好，去 Zotero 分类下看条目是否出现**，"
              "别只听本脚本说成功。")
    if not use_api and not any(o.startswith("api") for _, o, _ in results):
        print("（Zotero 未运行或本地 API 不可用，走 RIS 导入路径；想全自动："
              "保持 Zotero 运行，并在 设置→高级 勾选「允许其他应用与此电脑上的 Zotero 通信」）")
    if ris_fallback_error:
        # 唯一的入库路径（RIS 兜底）失败 = 本次入库没有真正完成，按受控失败退出
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"[运行失败] {type(e).__name__}：{e}", file=sys.stderr)
        sys.exit(1)
