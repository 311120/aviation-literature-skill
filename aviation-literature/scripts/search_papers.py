#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""学术文献检索脚本：封装 OpenAlex（默认）、Crossref、arXiv、Semantic Scholar 公开 API。

用法：
  python search_papers.py "retrieval augmented generation manufacturing" --max 10
  python search_papers.py "process knowledge graph" --source arxiv --download 文献库/pdf
  python search_papers.py "tolerance specification" --source all --ris 文献库/batch.ris

输出 Markdown 文献清单（标题/作者/年份/来源/ID或DOI/链接/摘要摘录），
可用 --ris 生成 RIS 题录文件供 Zotero 导入。
仅返回 API 真实返回的条目，不做任何补全或编造。

结构约定：`parse_*` 是纯函数（输入原始 API 载荷，输出规范化 dict 列表），
`search_*` 只负责取数据再交给 `parse_*`。纯函数层可离线单测。

退出码：0 正常完成（含"无结果"）；1 输入非法或受控运行失败；2 命令行用法错误。
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (academic-literature-search-script)"}

PAPER_FIELDS = ("title", "authors", "year", "venue", "id", "doi", "link", "pdf",
                "abstract", "access")

# --------------------------------------------------------------------------
# 全文可得性分级
#
# 三级标签，取值必须落在 ACCESS_LEVELS 内：
#   OA   公开开放获取，真免费——链接可直接下载，无需任何账号
#   SUB  出版商页面，需机构订阅——本校图书馆/校内网通常可下，脚本无法核实权限
#   CNKI 中文库（知网/万方等）——需登录学校账号，无公开 API
#   ?    无法判定（如无 DOI 又无 OA 标识）
#
# 红线：脚本只能给出**分级标注**，不能声称"已确认可下载"。SUB 与 CNKI 的
# 实际可获取性取决于学校的订阅与授权范围（IP/VPN），脚本看不到这部分信息。
# --------------------------------------------------------------------------
ACCESS_LEVELS = ("OA", "SUB", "CNKI", "?")

# 优先顺序：免费可得的排前面。数值越小越优先。
ACCESS_RANK = {"OA": 0, "CNKI": 1, "SUB": 2, "?": 3}

ACCESS_LABEL = {
    "OA": "公开开放获取（免费，可直接下载）",
    "SUB": "需机构订阅（本校图书馆/校内网通常可下）",
    "CNKI": "中文库（知网/万方，需登录学校账号）",
    "?": "可得性未知（无 DOI 也无开放获取标识）",
}

# 本地 PDF 下载结果的状态与文案。
# **必须把「本来就没有 PDF 链接」与「下载失败」分开说**：把后者说成前者，等于
# 把脚本/网络的故障谎报成"该文献没有公开全文"，用户会据此放弃一条本可拿到的文献。
LOCAL_PDF_LABEL = {
    "no_url": "该条目没有开放获取 PDF 链接（需按「获取方式」自行获取）",
    "not_pdf": "下载被拒：响应不是 PDF（出版商直链常 403，需手动获取）",
    "error": "下载失败（网络或写盘错误），需重试或手动获取",
}

# 判断"是不是中文文献"：标题或期刊名含中日韩统一表意文字
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
        # 本机缺证书链/经代理时降级为不校验
        print("[警告：SSL 证书校验失败，已降级为不校验模式]", file=sys.stderr)
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def resolve_access(is_oa=None, has_pdf=False, doi="", title="", venue="", source=""):
    """给出全文可得性分级。返回 ACCESS_LEVELS 中的一个。

    判定顺序（先免费后收费）：
      1. 明确的开放获取标识（is_oa 为真，或拿到了免费 PDF 链接）-> OA
      2. 中文文献（标题/期刊含汉字）且来源不是 arXiv/OpenAlex 英文库 -> CNKI
         （知网/万方无公开 API，脚本无法直接检索，只能提示走中文库）
      3. 有 DOI -> SUB（出版商页面，靠学校订阅）
      4. 其余 -> ?
    """
    if is_oa or has_pdf:
        return "OA"
    if source == "arxiv":            # arXiv 预印本一律免费
        return "OA"
    if _CJK_RE.search(title or "") or _CJK_RE.search(venue or ""):
        return "CNKI"
    if doi:
        return "SUB"
    return "?"


def normalize_paper(p):
    """补齐固定字段，保证下游（RIS 生成、zotero_save）不会因缺键而崩。"""
    out = {}
    for k in PAPER_FIELDS:
        v = p.get(k)
        if k in ("authors",):
            out[k] = [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
        elif k in ("year",):
            out[k] = str(v) if v not in (None, "") else "?"
        elif k in ("access",):
            # 非法或缺失的可得性一律降级为 ?，绝不让脏值流到下游
            out[k] = v if v in ACCESS_LEVELS else "?"
        else:
            out[k] = ("" if v is None else str(v))
    if p.get("relevance") is not None:
        out["relevance"] = p["relevance"]
    return out


# --------------------------------------------------------------------------
# 纯解析层：输入原始载荷，输出规范化结果。不含任何网络与文件访问。
# --------------------------------------------------------------------------

def rebuild_abstract(inv_index):
    """OpenAlex 用倒排索引存摘要，这里还原成文本。"""
    if not isinstance(inv_index, dict):
        return ""
    positions = []
    for word, idxs in inv_index.items():
        if not isinstance(idxs, list):
            continue
        for i in idxs:
            if isinstance(i, int):
                positions.append((i, word))
    positions.sort()
    return clean(" ".join(w for _, w in positions))[:300]


def parse_openalex(payload, max_results=None):
    """解析 OpenAlex /works 响应。"""
    data = payload if isinstance(payload, dict) else {}
    papers = []
    for w in data.get("results") or []:
        if not isinstance(w, dict):
            continue
        t = clean(w.get("display_name"))
        if not t:            # 无标题的条目不可用，丢弃
            continue
        pdf = ""
        for loc in (w.get("best_oa_location"), w.get("primary_location")):
            if isinstance(loc, dict) and loc.get("pdf_url"):
                pdf = loc["pdf_url"]
                break
        # 注意：OpenAlex 的 /works 响应**没有顶层 is_oa**（实测核对过 51 个顶层键），
        # 开放获取信息只在嵌套的 `open_access` 里（含 is_oa 与 oa_status）。
        # 早先写成 `w.get("is_oa") or (...)`，前半段在生产环境恒为 None，是死代码，
        # 会让人误以为返回值里也有该字段（测试夹具曾照此写，导致那条断言测的是另一分支）。
        oa_status = (w.get("open_access") or {}).get("oa_status") \
            if isinstance(w.get("open_access"), dict) else ""
        is_oa = isinstance(oa_status, str) and oa_status not in ("", "closed")
        src = ((w.get("primary_location") or {}).get("source") or {}) \
            if isinstance(w.get("primary_location"), dict) else {}
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        venue = clean(src.get("display_name")) or "OpenAlex"
        papers.append(normalize_paper({
            "title": t,
            "authors": [a["author"]["display_name"]
                        for a in (w.get("authorships") or [])
                        if isinstance(a, dict) and isinstance(a.get("author"), dict)],
            "year": w.get("publication_year") or "?",
            "venue": venue,
            "id": doi or (w.get("id") or "").rsplit("/", 1)[-1],
            "doi": doi,
            "link": w.get("doi") or w.get("id") or "",
            "pdf": pdf,
            "abstract": rebuild_abstract(w.get("abstract_inverted_index")),
            "access": resolve_access(is_oa=is_oa, has_pdf=bool(pdf), doi=doi,
                                     title=t, venue=venue, source="openalex"),
            "relevance": w.get("relevance_score") or 0,
        }))
        if max_results and len(papers) >= max_results:
            break
    return papers


# Crossref 的 license 里出现 Creative Commons 类开放授权，才算真开放获取。
_OA_LICENSE_RE = re.compile(
    r"creativecommons\.org|/licenses?/(?:by|by-sa|by-nc|by-nc-sa|by-nd|by-nc-nd|zero)|"
    r"publicdomain|opensource\.org|openaccess", re.IGNORECASE)


def _crossref_is_oa(item):
    """判断 Crossref 条目是否**真**开放获取——只认开放授权（Creative Commons 等）。

    坑：Crossref 的 `link` 里常带出版商的 TDM（text-mining）PDF 端点，
    `intended-application` 为 `text-mining` / `similarity-checking`——那是给机器批量
    抓取用的授权通道，**不是**免费全文。早先「拿到 pdf link 即视为 OA」会把 Springer
    等付费期刊误标成 OA：实测同一篇 10.1007/s00170-023-12644-y，OpenAlex 判 `SUB`、
    Crossref 判 `OA`，后者是错的（该文 license 为 springernature 的 TDM 条款，无 CC）。
    故改为只认开放授权，避免夸大可得性（对应 SKILL.md 红线第 10 条）。
    """
    for lic in item.get("license") or []:
        if isinstance(lic, dict) and _OA_LICENSE_RE.search(lic.get("URL", "") or ""):
            return True
    return False


def parse_crossref(payload, max_results=None):
    """解析 Crossref /works 响应。"""
    data = payload if isinstance(payload, dict) else {}
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    papers = []
    for p in message.get("items") or []:
        if not isinstance(p, dict):
            continue
        title_list = p.get("title") or [""]
        t = clean(title_list[0] if title_list else "")
        if not t:            # 无标题的条目不可用，丢弃
            continue
        venue = (p.get("container-title") or [""])
        is_oa = _crossref_is_oa(p)
        pdf = ""
        if is_oa:          # 只有真开放获取，才把 pdf 链接当作可取全文
            for l in p.get("link") or []:
                if isinstance(l, dict) and l.get("content-type") == "application/pdf":
                    pdf = l.get("URL", "")
                    break
        year = "?"
        issued = (p.get("issued") or {}).get("date-parts") or []
        if issued and isinstance(issued[0], list) and issued[0] and issued[0][0]:
            year = issued[0][0]
        doi = p.get("DOI", "") or ""
        venue = clean(venue[0] if venue else "") or "Crossref"
        papers.append(normalize_paper({
            "title": t,
            "authors": [f"{a.get('family', '')} {a.get('given', '')}".strip()
                        for a in (p.get("author") or []) if isinstance(a, dict)],
            "year": year,
            "venue": venue,
            "id": doi,
            "doi": doi,
            "link": ("https://doi.org/" + doi) if doi else "",
            "pdf": pdf,
            "abstract": clean(p.get("abstract") or "")[:300],
            "access": resolve_access(is_oa=is_oa, doi=doi,
                                     title=t, venue=venue, source="crossref"),
        }))
        if max_results and len(papers) >= max_results:
            break
    return papers


def _tag(entry, tag, default=""):
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", entry, re.S)
    return clean(m.group(1)) if m else default


def parse_arxiv(xml_text, max_results=None):
    """解析 arXiv Atom 响应。"""
    papers = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml_text or "", re.S):
        link = _tag(e, "id")
        t = _tag(e, "title")
        if not link or not t:      # 缺 id 或缺标题的条目不可用，丢弃
            continue
        m = re.search(r"<published>(\d{4})", e)
        papers.append(normalize_paper({
            "title": t,
            "authors": [_tag(a, "name") for a in re.findall(r"<author>(.*?)</author>", e, re.S)],
            "year": m.group(1) if m else "?",
            "venue": "arXiv",
            "id": link.rsplit("/", 1)[-1],
            "doi": "",
            "link": link,
            "pdf": (link.replace("/abs/", "/pdf/")
                    + ("" if link.endswith(".pdf") else ".pdf")) if "/abs/" in link else "",
            "abstract": _tag(e, "summary")[:300],
            # arXiv 预印本一律免费：resolve_access 对 source=arxiv 直接判 OA
            "access": resolve_access(source="arxiv", title=t, venue="arXiv"),
        }))
        if max_results and len(papers) >= max_results:
            break
    return papers


def parse_s2(payload, max_results=None):
    """解析 Semantic Scholar graph/v1/paper/search 响应。"""
    data = payload if isinstance(payload, dict) else {}
    papers = []
    for p in data.get("data") or []:
        if not isinstance(p, dict):
            continue
        t = clean(p.get("title"))
        if not t:            # 无标题的条目不可用，丢弃
            continue
        ext = p.get("externalIds") if isinstance(p.get("externalIds"), dict) else {}
        oa = p.get("openAccessPdf") if isinstance(p.get("openAccessPdf"), dict) else {}
        doi = ext.get("DOI", "") or ""
        venue = clean(p.get("venue")) or "Semantic Scholar"
        papers.append(normalize_paper({
            "title": t,
            "authors": [a["name"] for a in (p.get("authors") or [])
                        if isinstance(a, dict) and a.get("name")],
            "year": p.get("year") or "?",
            "venue": venue,
            "id": doi or (p.get("paperId") or "")[:12],
            "doi": doi,
            "link": ("https://doi.org/" + doi) if doi
                    else "https://www.semanticscholar.org/paper/" + (p.get("paperId") or ""),
            "pdf": oa.get("url", ""),
            "abstract": clean(p.get("abstract"))[:300],
            "access": resolve_access(has_pdf=bool(oa.get("url")), doi=doi,
                                     title=t, venue=venue, source="s2"),
        }))
        if max_results and len(papers) >= max_results:
            break
    return papers


def dedup(papers):
    """跨源去重：优先按 DOI，无 DOI 时按规范化标题；保留首次出现，顺序稳定。"""
    seen_doi, seen_title, out = set(), set(), []
    for p in papers:
        doi = (p.get("doi") or "").strip().lower()
        title = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (p.get("title") or "").lower())
        if doi and doi in seen_doi:
            continue
        if not doi and title and title in seen_title:
            continue
        if doi:
            seen_doi.add(doi)
        if title:
            seen_title.add(title)
        out.append(p)
    return out


# --------------------------------------------------------------------------
# 取数据层
# --------------------------------------------------------------------------

def search_openalex(query, max_results):
    api = ("https://api.openalex.org/works?filter=title_and_abstract.search:"
           + urllib.parse.quote(query)
           + f"&per-page={max_results}&sort=relevance_score:desc"
             "&mailto=literature-skill@example.com")
    return parse_openalex(json.loads(http_get(api, timeout=40)), max_results)


DOI_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s]+)$", re.IGNORECASE)


def doi_of(query):
    """查询串本身就是 DOI（或 doi.org 链接）时返回规范化的 DOI，否则返回空串。"""
    m = DOI_RE.match((query or "").strip())
    return m.group(1) if m else ""


def search_crossref(query, max_results):
    """Crossref：查询串是 DOI 时走 /works/{doi} 精确核验题录，否则走 /works?query= 检索。

    为什么要有 DOI 分支：`/works?query=` 是**书目模糊检索**，把 DOI 当检索词丢进去
    只会返回一堆无关文献（实测搜 10.1007/s00170-023-12644-y 返回超导、胰腺炎等条目）。
    而 SKILL.md 红线要求「只给 DOI 时用 Crossref 核验原字段」，故必须直查 DOI 端点。
    """
    doi = doi_of(query)
    if doi:
        api = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
        try:
            payload = json.loads(http_get(api, timeout=40))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"[Crossref 核不到该 DOI：{doi}]", file=sys.stderr)
                return []
            raise
        msg = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(msg, dict):
            return []
        # /works/{doi} 的 message 就是单条题录，包成 items 列表复用解析器
        return parse_crossref({"message": {"items": [msg]}}, max_results)
    api = ("https://api.crossref.org/works?query=" + urllib.parse.quote(query)
           + f"&rows={max_results}"
             "&select=title,author,issued,DOI,container-title,abstract,link")
    return parse_crossref(json.loads(http_get(api, timeout=40)), max_results)


def search_arxiv(query, max_results):
    # 本机证书链不全：https + 不校验上下文。arXiv 在部分网络下限流/超时，
    # 故超时较短、只重试一次，失败即跳过（caller 会打印提示）。
    api = ("https://export.arxiv.org/api/query?search_query=all:"
           + urllib.parse.quote(query) + f"&max_results={max_results}&sortBy=relevance")
    for attempt in range(2):
        if attempt:
            print("[arXiv 限流，等待 10 秒重试]", file=sys.stderr)
            time.sleep(10)
        try:
            xml = http_get(api, timeout=30).decode("utf-8", "replace")
            return parse_arxiv(xml, max_results)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
    return []


def search_s2(query, max_results):
    api = ("https://api.semanticscholar.org/graph/v1/paper/search?query="
           + urllib.parse.quote(query)
           + f"&limit={max_results}"
             "&fields=title,authors,year,venue,externalIds,openAccessPdf,abstract")
    waits = [5, 10, 20]  # S2 对未认证请求限流严格（常 429），退避重试
    data = None
    for wait in [0] + waits:
        if wait:
            time.sleep(wait)
        try:
            data = json.loads(http_get(api, timeout=40))
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:
                print(f"[Semantic Scholar 请求失败：HTTP {e.code}，跳过]", file=sys.stderr)
                return []
        except Exception:
            continue
    if data is None:
        print("[Semantic Scholar 请求失败（限流或网络），已跳过]", file=sys.stderr)
        return []
    return parse_s2(data, max_results)


# --------------------------------------------------------------------------
# 输出与下载
# --------------------------------------------------------------------------

def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "", s or "").strip()


def _first_author_surname(paper):
    """取第一作者姓氏做文件名。作者缺失或为空串时退化为 Unknown。

    早先写成 `(paper.get("authors") or ["Unknown"])[0].split()[-1]`：
    当 authors 是 `[""]`（源站返回空名）时 `[""][0].split()` 得 `[]`，
    `[-1]` **抛 IndexError**，被外层 `except` 静默吞掉——表现为"这条没有全文"，
    而真相是"下载代码崩了"。这里改成不会抛的取值方式。
    """
    for a in (paper.get("authors") or []):
        parts = str(a or "").split()
        if parts:
            return safe_name(parts[-1]) or "Unknown"
    return "Unknown"


def download_pdf(paper, out_dir):
    """下载 PDF。只认文件头 %PDF 的响应，其余一律视为失败（不落半个文件）。

    返回本地路径；失败返回空串。失败原因由 `download_pdf_ex()` 区分，
    调用方（main）据此把「无 PDF 链接」「下载被拒」「写盘失败」分开如实汇报。
    """
    return download_pdf_ex(paper, out_dir)[0]


def download_pdf_ex(paper, out_dir):
    """下载 PDF 并返回 (本地路径, 状态)。

    状态取值：
      ok        下载成功并落盘
      no_url    该条目没有 pdf 链接（不是失败）
      not_pdf   拿到响应但文件头不是 %PDF（403 页面/HTML 等）
      error     网络、写盘等异常（**必须与 no_url 区分**，否则会把下载故障说成"无全文"）
    """
    if not paper.get("pdf"):
        return "", "no_url"
    try:
        data = http_get(paper["pdf"], timeout=60)
    except Exception:
        return "", "error"
    if data[:4] != b"%PDF":
        return "", "not_pdf"
    try:
        os.makedirs(out_dir, exist_ok=True)
        first = _first_author_surname(paper)
        name = f"{paper.get('year', '?')}_{first}_{safe_name(paper.get('title'))[:60]}.pdf"
        path = os.path.join(out_dir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path, "ok"
    except Exception:
        return "", "error"


def sort_by_access(papers):
    """按可得性优先排序：OA -> CNKI -> SUB -> ?，同级保持原有顺序（稳定排序）。

    只做重排，不丢弃任何条目——付费文献仍然看得见，只是排在后面。
    """
    return sorted(papers, key=lambda p: ACCESS_RANK.get(p.get("access", "?"), 3))


def access_hint(p):
    """给出"怎么拿到全文"的具体下一步，而非笼统说"需手动获取"。"""
    a = p.get("access", "?")
    if a == "OA":
        return "可直接下载（已给出 PDF 链接）" if p.get("pdf") else "公开开放获取，从链接页面下载"
    if a == "SUB":
        return "走学校图书馆：在图书馆网站或校内网按 DOI 打开；订阅期刊可直接下 PDF"
    if a == "CNKI":
        return "中文文献：登录学校账号到知网/万方检索下载，或用 Zotero 浏览器插件在页面一键抓取"
    return "无 DOI 也无开放获取标识，建议用标题在图书馆统一检索里搜一次"


def to_ris_entry(paper):
    lines = ["TY  - JOUR", "TI  - " + (paper.get("title") or "")]
    lines += ["AU  - " + a for a in (paper.get("authors") or [])]
    if paper.get("year") and paper["year"] != "?":
        lines.append("PY  - " + str(paper["year"]))
    if paper.get("doi"):
        lines.append("DO  - " + paper["doi"])
    if paper.get("link"):
        lines.append("UR  - " + paper["link"])
    if paper.get("abstract"):
        lines.append("AB  - " + paper["abstract"])
    lines.append("ER  - ")
    return "\n".join(lines)


def render_markdown(query, papers, downloaded, download_status=None):
    """渲染 Markdown 清单。

    downloaded: {index: 本地路径}。键存在但值为空串 = 已尝试下载但未成功，
    此时按 download_status 如实写明**失败原因**；键不存在 = 本次没有启用下载，不输出该行。
    download_status: {index: ok/no_url/not_pdf/error}，用于区分"本来就没有 PDF"与"下载失败"。
    """
    download_status = download_status or {}
    lines = [f"# 检索结果：{query}", ""]
    n_free = sum(1 for p in papers if p.get("access") in ("OA", "CNKI"))
    if n_free:
        lines.append(f"> 其中 {n_free}/{len(papers)} 条可免费获取"
                     f"（公开开放获取或中文库），已按可得性优先排列。")
        lines.append("")
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p["authors"][:4]) + (" et al." if len(p["authors"]) > 4 else "")
        access = p.get("access", "?")
        if i in downloaded:
            status = download_status.get(i, "") if download_status else ""
            detail = LOCAL_PDF_LABEL.get(
                status, "未获取到开放获取 PDF（需手动获取）")
            local = f"- 本地文件：{downloaded[i] or detail}"
        else:
            local = ""
        lines += [
            f"## {i}. {p['title']}",
            f"- 作者：{authors or '不详'}",
            f"- 年份：{p['year']}｜来源：{p['venue']}｜ID/DOI：{p['id']}",
            f"- 可得性：[{access}] {ACCESS_LABEL.get(access, ACCESS_LABEL['?'])}",
            f"- 获取方式：{access_hint(p)}",
            f"- 链接：{p['link']}",
            f"- 摘要摘录：{p['abstract'] or '（无）'}",
            local,
            "",
        ]
    return "\n".join(l for l in lines if l != "") + "\n"


def _write_text(path, text, label="文件"):
    """写文本文件（自动建父目录）。失败时**受控报错**并返回 False。

    早先此处没有异常处理，写不进去会以裸 traceback 结束——而 `--ris`/`--json`
    常常被写到用户以为可写的目录（如只读介质、被占用的路径）。
    """
    try:
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return True
    except OSError as e:
        print(f"[{label}写入失败] {path}（{type(e).__name__}: {e}）", file=sys.stderr)
        print("  请换一个可写目录（例如工作区下的 文献库/），或检查该文件是否被占用。",
              file=sys.stderr)
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="检索 OpenAlex / Crossref / arXiv / Semantic Scholar 学术文献")
    ap.add_argument("query", help="检索词（建议英文）")
    ap.add_argument("--source", choices=["openalex", "crossref", "arxiv", "s2", "all"],
                    default="openalex",
                    help="检索来源；默认 openalex（学术检索精度高、稳定）；all = 四源合并去重")
    ap.add_argument("--max", type=int, default=10, help="每个来源的最大条数")
    ap.add_argument("--download", metavar="DIR", help="下载有 PDF 链接的文献到该目录")
    ap.add_argument("--ris", metavar="FILE", help="生成 RIS 题录文件，供 Zotero 文件->导入")
    ap.add_argument("--out", metavar="FILE", help="结果另存为 Markdown 文件")
    ap.add_argument("--json", metavar="FILE", dest="json_out",
                    help="结果导出为 JSON（含本地 PDF 路径），供 zotero_save.py 自动入库")
    ap.add_argument("--no-prefer-free", dest="prefer_free", action="store_false",
                    default=True,
                    help="关闭“可得性优先”排序，改回原始顺序（默认开启，免费可得的排前面）")
    ap.add_argument("--only-free", action="store_true",
                    help="只输出可免费获取的条目（OA + CNKI），过滤掉需订阅的")
    args = ap.parse_args(argv)

    query = (args.query or "").strip()
    if not query:
        print("检索词不能为空。示例：python search_papers.py \"knowledge graph\"", file=sys.stderr)
        return 1
    if args.max <= 0:
        print("--max 必须为正整数。", file=sys.stderr)
        return 1

    papers, failed = [], []
    if args.source in ("openalex", "all"):
        try:
            got = search_openalex(query, args.max)
            papers += got
            if not got:
                failed.append("OpenAlex（无结果）")
        except Exception as e:
            failed.append(f"OpenAlex（{type(e).__name__}）")
    if args.source in ("crossref", "all"):
        try:
            got = search_crossref(query, args.max)
            papers += got
            if not got:
                failed.append("Crossref（无结果）")
        except Exception as e:
            failed.append(f"Crossref（{type(e).__name__}）")
    if args.source in ("arxiv", "all"):
        try:
            got = search_arxiv(query, args.max)
            papers += got
            if not got:
                # 空结果的成因不止一种：中文词搜英文库、词太偏、以及真的限流/超时。
                # 一律报成「限流或超时」会把前两种误导成"稍后重试就好"。
                failed.append("arXiv（无结果：该库以英文预印本为主，也可能是限流/超时）")
        except Exception as e:
            failed.append(f"arXiv（{type(e).__name__}）")
    if args.source in ("s2", "all"):
        got = search_s2(query, args.max)
        papers += got
        if not got:
            failed.append("Semantic Scholar（无结果，或未认证请求被限流后跳过）")

    if args.source == "all":
        before = len(papers)
        papers = dedup(papers)
        if before != len(papers):
            print(f"[跨源去重：{before} -> {len(papers)} 条]")

    if not papers:
        print("未检索到结果。可尝试更换检索词或 --source 单一来源重试。")
        if failed:
            print("失败来源：" + "、".join(failed))
        return 0

    if args.only_free:
        kept = [p for p in papers if p.get("access") in ("OA", "CNKI")]
        if kept:
            print(f"[--only-free：{len(papers)} -> {len(kept)} 条（已滤掉需订阅的）]")
        else:
            # 宁缺毋假：过滤后为空就如实说明，并输出空清单，绝不悄悄回退成全部
            print("[--only-free：没有可免费获取的条目；"
                  "去掉该开关可查看全部结果]")
        papers = kept

    if args.prefer_free:
        papers = sort_by_access(papers)

    downloaded, download_status = {}, {}
    if args.download:
        for i, p in enumerate(papers, 1):
            path, status = download_pdf_ex(p, args.download)
            downloaded[i] = path
            download_status[i] = status
            if status in ("not_pdf", "error"):
                print(f"[下载失败] {p.get('title', '')[:60]}（{LOCAL_PDF_LABEL[status]}）",
                      file=sys.stderr)

    text = render_markdown(query, papers, downloaded, download_status)
    print(text)
    if failed:
        print(f"[未能检索的来源：{'、'.join(failed)}]"
              "；可改用 --source 指定单一来源，或按 SKILL.md 用 WebSearch 兜底")

    rc = 0
    if args.out:
        if _write_text(args.out, text, "Markdown"):
            print(f"[Markdown 已保存到 {args.out}]")
        else:
            rc = 1
    if args.ris:
        if _write_text(args.ris, "\n\n".join(to_ris_entry(p) for p in papers) + "\n", "RIS"):
            print(f"[RIS 题录已保存到 {args.ris}，可在 Zotero 中 文件->导入 以去重方式入库]")
        else:
            rc = 1
    if args.json_out:
        payload = []
        for i, p in enumerate(papers, 1):
            item = {"index": i}
            item.update({k: p[k] for k in PAPER_FIELDS})
            item["pdf_url"] = p.get("pdf", "")
            item["local_pdf"] = downloaded.get(i, "")
            # 供下游区分「本来没有 PDF」与「下载失败」；不启用 --download 时为空串
            item["local_pdf_status"] = download_status.get(i, "")
            payload.append(item)
        if _write_text(args.json_out, json.dumps(payload, ensure_ascii=False, indent=2),
                       "JSON"):
            print(f"[JSON 已保存到 {args.json_out}，"
                  "入库命令：zotero_save.py --json 该文件 --items 编号]")
        else:
            rc = 1
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"[运行失败] {type(e).__name__}：{e}", file=sys.stderr)
        sys.exit(1)
