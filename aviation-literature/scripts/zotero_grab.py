#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Zotero 抓取器（Connector）把网页/DOI 抓成条目并直接入库，含可获取的全文。

与 zotero_save.py 的分工：
  - zotero_save.py：把**已经检索到手**的条目写入 Zotero，PDF 走本地 API 上传；
  - zotero_grab.py：把**一个 URL 或 DOI** 交给 Zotero 自己去解析抓取，
    由 Zotero 决定能抓到什么（元数据、以及页面上的全文 PDF）。

用法：
  python zotero_grab.py "https://arxiv.org/abs/2401.00001"          # 抓单个页面
  python zotero_grab.py --doi 10.1000/oa-001                        # 按 DOI 抓
  python zotero_grab.py --urls 待抓.txt                             # 批量（每行一个）
  python zotero_grab.py --check                                     # 只检测抓取器是否可用

能自动抓到全文 PDF 的情形（无需登录，可直接用本脚本）：
  - arXiv / bioRxiv 等预印本
  - 开放获取期刊（DOAJ、PLOS、MDPI、Frontiers 等）
  - 任何提供了公开 PDF 直链的页面
  - 出版商页面上标着 Open Access 的论文

抓不到全文、只拿到题录（或完全抓不到）的情形：
  - 知网 / 万方 / 维普等中文库：PDF 需登录 + 机构授权，且反爬严格。
    **请用浏览器打开知网页面，点 Zotero 浏览器插件图标抓取**——
    插件带着你已登录的会话，能正常抓；命令行没有会话，抓不到。
  - 学校图书馆订阅的出版商页面：依赖 IP/VPN 授权，同理需走浏览器插件。

本脚本绝不尝试绕过登录、付费墙或反爬，也不保存任何账号凭据。
抓取失败时如实报告，不伪造成功。

退出码：0 正常完成；1 输入非法或受控失败（如抓取器未运行）；2 命令行用法错误。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CONNECTOR = "http://127.0.0.1:23119/connector"
UA = "aviation-literature-grab"
# 连接器要求声明 API 版本，缺失会被拒
CONNECTOR_HEADERS = {
    "Content-Type": "application/json",
    "X-Zotero-Connector-API-Version": "3",
    "User-Agent": UA,
}

# 已知抓不到全文的来源特征：命中就明确告知走浏览器插件，不做无谓尝试
BROWSER_ONLY_HINTS = (
    ("cnki.net", "知网"),
    ("wanfangdata.com.cn", "万方"),
    ("cqvip.com", "维普"),
    ("cnki.com.cn", "知网"),
)


def connector_up(timeout=3):
    """探测 Zotero 抓取器是否在运行。"""
    try:
        req = urllib.request.Request(CONNECTOR + "/ping", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return b"Zotero is running" in resp.read()
    except Exception:
        return False


def needs_browser(url):
    """该 URL 是否属于「必须用浏览器插件抓」的来源。返回来源名或空串。"""
    low = (url or "").lower()
    for key, name in BROWSER_ONLY_HINTS:
        if key in low:
            return name
    return ""


def build_item(url, title="", doi=""):
    """构造交给 Zotero 抓取器的条目。

    只给最少的识别信息（url / DOI / 标题），其余交由 Zotero 自己解析。
    这里不编造作者、年份等字段——抓取器抓不到就让它抓不到。
    """
    item = {"itemType": "journalArticle", "url": url}
    if title:
        item["title"] = title
    if doi:
        item["DOI"] = doi
    return item


def grab(urls, timeout=60):
    """把若干 URL 交给 Zotero 抓取器。返回 (成功数, 失败清单)。

    连接器对每个 URL 独立抓取：整体提交成功（201）即视为全部受理，
    因为 Zotero 不逐个回报抓取结果——能抓到多少由 Zotero 自己决定，
    故这里不谎称"每个都抓到了全文"。
    """
    items = [build_item(u) for u in urls]
    payload = json.dumps({"items": items, "uri": urls[0] if urls else ""}).encode("utf-8")
    req = urllib.request.Request(CONNECTOR + "/saveItems", data=payload,
                                 headers=CONNECTOR_HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 连接器成功时返回 201 且无正文
            if resp.status in (200, 201):
                return len(urls), []
            return 0, [(u, f"HTTP {resp.status}") for u in urls]
    except urllib.error.HTTPError as e:
        return 0, [(u, f"HTTP {e.code}") for u in urls]
    except Exception as e:                      # noqa: BLE001
        return 0, [(u, f"{type(e).__name__}") for u in urls]


def normalize_urls(raw):
    """清洗输入：去空白、去空行、按出现顺序去重（保序，便于对账）。"""
    out, seen = [], set()
    for u in raw:
        u = (u or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="用 Zotero 抓取器把 URL/DOI 抓成条目并入库（含可获取的全文）")
    ap.add_argument("url", nargs="?", help="要抓取的页面 URL")
    ap.add_argument("--doi", metavar="DOI", help="按 DOI 抓取（自动拼 https://doi.org/）")
    ap.add_argument("--urls", metavar="FILE", help="批量抓取：文件每行一个 URL")
    ap.add_argument("--check", action="store_true", help="只检测抓取器是否可用")
    ap.add_argument("--dry-run", action="store_true", help="只校验输入，不真正提交")
    args = ap.parse_args(argv)

    if args.check:
        if connector_up():
            print("Zotero 抓取器可用（127.0.0.1:23119）。")
            return 0
        print("Zotero 抓取器不可用：请确认 Zotero 正在运行。"
              "若已运行仍失败，检查 设置→高级 里是否允许其他应用与本机 Zotero 通信。",
              file=sys.stderr)
        return 1

    targets = []
    if args.doi:
        targets.append("https://doi.org/" + args.doi.strip())
    if args.url:
        targets.append(args.url)
    if args.urls:
        if not os.path.isfile(args.urls):
            print(f"找不到 URL 列表文件：{args.urls}", file=sys.stderr)
            return 1
        with open(args.urls, encoding="utf-8") as f:
            targets += f.read().splitlines()

    targets = normalize_urls(targets)
    if not targets:
        print("没有可抓取的 URL。用法示例："
              "python zotero_grab.py \"https://arxiv.org/abs/2401.00001\"", file=sys.stderr)
        return 1

    # 先分流：需浏览器插件的直接给出明确指引，不提交、不假装成功
    browser_only, auto_targets = [], []
    for u in targets:
        name = needs_browser(u)
        (browser_only if name else auto_targets).append((u, name))

    if not connector_up():
        print("Zotero 抓取器不可用（Zotero 未运行）。请先启动 Zotero 再重试。",
              file=sys.stderr)
        return 1

    # 退出码语义：需浏览器插件 ≠ 失败（那是正常分流，返回 0）；
    # 只有「本可自动抓却提交失败」才算受控失败。
    submit_failed = False
    if auto_targets:
        if args.dry_run:
            print(f"[dry-run] 将通过抓取器提交 {len(auto_targets)} 个 URL：")
            for u, _ in auto_targets:
                print(f"  - {u}")
        else:
            ok, fails = grab([u for u, _ in auto_targets])
            if ok:
                print(f"已提交 {ok} 个 URL 给 Zotero 抓取器；"
                      "全文 PDF 能抓到的会自动挂为附件，请稍后在 Zotero 中查看。")
            for u, err in fails:
                print(f"  抓取失败：{u}（{err}）", file=sys.stderr)
            submit_failed = bool(fails)

    if browser_only:
        print("\n以下来源需用 Zotero 浏览器插件抓取（命令行拿不到登录会话）：")
        for u, name in browser_only:
            print(f"  - [{name}] {u}")
        print("做法：在浏览器里打开该页面（确保已登录学校账号）→ 点 Zotero 插件图标 → "
              "选择目标分类保存。")
        if not auto_targets:
            print("（以上条目未提交给抓取器，属正常分流，不是失败。）")

    return 1 if submit_failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:                          # noqa: BLE001
        print(f"[运行失败] {type(e).__name__}：{e}", file=sys.stderr)
        sys.exit(1)
