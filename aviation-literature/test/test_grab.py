#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zotero_grab 用例：URL 分流、条目构造、批量清洗，以及 CLI 退出码。

全程离线：抓取器 HTTP 调用被替换成替身，不发任何真实请求，也不碰真实 Zotero 库。
"""
import json
import os
import tempfile

from harness import Checker, capture, make_temp_dir, quiet, run_main


class _FakeConnector:
    """替换 urllib.request.urlopen 的替身：按 URL 分派响应。"""

    def __init__(self, up=True, save_status=201, raise_on_save=None):
        self.up = up
        self.save_status = save_status
        self.raise_on_save = raise_on_save
        self.saved = []          # 记录提交过的载荷，供断言检查

    def __call__(self, req, timeout=None):
        url = req.full_url
        if "/connector/ping" in url:
            if not self.up:
                raise OSError("connector down")
            return _Resp(200, b"<html><body>Zotero is running</body></html>")
        if "/connector/saveItems" in url:
            if self.raise_on_save:
                raise self.raise_on_save
            self.saved.append(json.loads(req.data.decode("utf-8")))
            return _Resp(self.save_status, b"")
        raise OSError("unmapped url")


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run():
    import zotero_grab as zg

    ck = Checker("test_grab")
    tmp = make_temp_dir(prefix="avlit_grab_")

    # ---------- 浏览器专用来源分流 ----------
    ck.eq(zg.needs_browser("https://kns.cnki.net/kcms/detail/11.2127.TP.html"), "知网",
          "分流：知网 URL 判为需浏览器插件")
    ck.eq(zg.needs_browser("https://www.wanfangdata.com.cn/details/detail.do"), "万方",
          "分流：万方 URL 判为需浏览器插件")
    ck.eq(zg.needs_browser("http://www.cqvip.com/QK/90000X/202001/1.html"), "维普",
          "分流：维普 URL 判为需浏览器插件")
    ck.eq(zg.needs_browser("https://arxiv.org/abs/2401.00001"), "",
          "分流：arXiv 不需要浏览器插件（可自动抓）")
    ck.eq(zg.needs_browser("https://doi.org/10.1000/oa-001"), "",
          "分流：DOI 链接不需要浏览器插件")
    ck.eq(zg.needs_browser("https://KNS.CNKI.NET/x"), "知网",
          "分流：大小写不敏感")
    ck.eq(zg.needs_browser(""), "", "分流：空串返回空")
    ck.eq(zg.needs_browser(None), "", "分流：None 不崩且返回空")

    # ---------- 条目构造：不编造字段 ----------
    it = zg.build_item("https://arxiv.org/abs/2401.00001")
    ck.eq(it["itemType"], "journalArticle", "构造：条目类型为 journalArticle")
    ck.eq(it["url"], "https://arxiv.org/abs/2401.00001", "构造：带上 url")
    ck.check("title" not in it, "构造：未提供标题时不编造 title")
    ck.check("DOI" not in it, "构造：未提供 DOI 时不编造 DOI")
    ck.check("creators" not in it, "构造：绝不编造作者")
    ck.check("date" not in it, "构造：绝不编造年份")
    it2 = zg.build_item("https://x/y", title="T", doi="10.1/z")
    ck.eq(it2["title"], "T", "构造：提供标题时带上")
    ck.eq(it2["DOI"], "10.1/z", "构造：提供 DOI 时带上")

    # ---------- 批量输入清洗 ----------
    ck.eq(zg.normalize_urls(["  a  ", "", "b", "a", None]),
          ["a", "b"], "清洗：去空白、去空行、按序去重")
    ck.eq(zg.normalize_urls([]), [], "清洗：空列表返回空")
    ck.eq(zg.normalize_urls(["x"]), ["x"], "清洗：单元素保序")

    # ---------- 抓取器可用性探测 ----------
    import urllib.request
    real = urllib.request.urlopen
    try:
        urllib.request.urlopen = _FakeConnector(up=True)
        ck.check(zg.connector_up(), "探测：抓取器运行时返回 True")
        urllib.request.urlopen = _FakeConnector(up=False)
        ck.check(not zg.connector_up(), "探测：抓取器不可用时返回 False")
    finally:
        urllib.request.urlopen = real

    # ---------- grab：成功与失败 ----------
    fake = _FakeConnector()
    try:
        urllib.request.urlopen = fake
        ok, fails = zg.grab(["https://arxiv.org/abs/1"])
        ck.eq(ok, 1, "抓取：成功受理返回 1 条")
        ck.eq(fails, [], "抓取：成功时无失败项")
        ck.eq(len(fake.saved), 1, "抓取：确实向抓取器提交了 1 次")
        ck.eq(fake.saved[0]["items"][0]["url"], "https://arxiv.org/abs/1",
              "抓取：提交载荷里含目标 URL")
    finally:
        urllib.request.urlopen = real

    import urllib.error
    fake = _FakeConnector(raise_on_save=urllib.error.HTTPError(
        "u", 500, "boom", {}, None))
    try:
        urllib.request.urlopen = fake
        ok, fails = zg.grab(["https://arxiv.org/abs/1"])
        ck.eq(ok, 0, "抓取：HTTP 错误时成功数为 0")
        ck.eq(len(fails), 1, "抓取：HTTP 错误时如实报 1 条失败")
        ck.contains(fails[0][1], "500", "抓取：失败原因含状态码")
    finally:
        urllib.request.urlopen = real

    fake = _FakeConnector(raise_on_save=OSError("net down"))
    try:
        urllib.request.urlopen = fake
        ok, fails = zg.grab(["https://x/a"])
        ck.eq(ok, 0, "抓取：网络异常时成功数为 0")
        ck.contains(fails[0][1], "OSError", "抓取：网络异常时如实报异常类型")
    finally:
        urllib.request.urlopen = real

    # ---------- CLI：--check ----------
    def call(argv):
        with quiet(), capture() as cap:
            code = zg.main(argv)
        return code, cap

    # ---------- CLI：无输入 ----------
    code, cap = call([])
    ck.eq(code, 1, "CLI：无任何输入返回 1")
    ck.contains(cap.err, "没有可抓取的 URL", "CLI：无输入时给出用法提示")

    # ---------- CLI：--urls 指向不存在的文件 ----------
    code, cap = call(["--urls", os.path.join(tmp, "nope.txt")])
    ck.eq(code, 1, "CLI：URL 列表文件不存在返回 1")
    ck.contains(cap.err, "找不到 URL 列表文件", "CLI：文件不存在时如实报错")

    # ---------- CLI：--dry-run 不提交 ----------
    fake = _FakeConnector()
    try:
        urllib.request.urlopen = fake
        code, cap = call(["https://arxiv.org/abs/1", "--dry-run"])
        ck.eq(code, 0, "CLI：--dry-run 正常返回 0")
        ck.eq(len(fake.saved), 0, "CLI：--dry-run 不向抓取器提交任何载荷")
        ck.contains(cap.out, "dry-run", "CLI：--dry-run 明确标注未提交")
    finally:
        urllib.request.urlopen = real

    # ---------- CLI：仅知网链接 -> 正常分流，不提交，返回 0 ----------
    fake = _FakeConnector()
    try:
        urllib.request.urlopen = fake
        code, cap = call(["https://kns.cnki.net/kcms/detail/x.html"])
        ck.eq(code, 0, "CLI：仅知网链接时返回 0（正常分流不算失败）")
        ck.eq(len(fake.saved), 0, "CLI：知网链接不提交给抓取器")
        ck.contains(cap.out, "浏览器插件", "CLI：知网链接明确提示用浏览器插件")
        ck.contains(cap.out, "正常分流", "CLI：说明这不是失败")
    finally:
        urllib.request.urlopen = real

    # ---------- CLI：混合输入（可自动抓 + 需浏览器） ----------
    mixed = os.path.join(tmp, "mixed.txt")
    with open(mixed, "w", encoding="utf-8", newline="\n") as f:
        f.write("https://arxiv.org/abs/1\nhttps://kns.cnki.net/x\n")
    fake = _FakeConnector()
    try:
        urllib.request.urlopen = fake
        code, cap = call(["--urls", mixed])
        ck.eq(code, 0, "CLI：混合输入返回 0")
        ck.eq(len(fake.saved), 1, "CLI：混合输入只提交可自动抓的那条")
        ck.eq(len(fake.saved[0]["items"]), 1, "CLI：提交载荷只含 1 条自动抓条目")
        ck.contains(cap.out, "[知网]", "CLI：单独列出需浏览器插件的来源")
        ck.eq(fake.saved[0]["items"][0]["url"], "https://arxiv.org/abs/1",
              "CLI：提交的正是可自动抓的那条 URL")
    finally:
        urllib.request.urlopen = real

    # ---------- CLI：抓取器未运行 ----------
    fake = _FakeConnector(up=False)
    try:
        urllib.request.urlopen = fake
        code, cap = call(["https://arxiv.org/abs/1"])
        ck.eq(code, 1, "CLI：抓取器未运行时返回 1")
        ck.contains(cap.err, "Zotero", "CLI：抓取器未运行时提示启动 Zotero")
    finally:
        urllib.request.urlopen = real

    # ---------- CLI：--check ----------
    fake = _FakeConnector(up=True)
    try:
        urllib.request.urlopen = fake
        code, cap = call(["--check"])
        ck.eq(code, 0, "CLI：--check 抓取器可用返回 0")
        ck.contains(cap.out, "可用", "CLI：--check 报告抓取器可用")
    finally:
        urllib.request.urlopen = real

    fake = _FakeConnector(up=False)
    try:
        urllib.request.urlopen = fake
        code, cap = call(["--check"])
        ck.eq(code, 1, "CLI：--check 抓取器不可用返回 1")
    finally:
        urllib.request.urlopen = real

    # ---------- CLI：--doi 拼出 doi.org 链接 ----------
    fake = _FakeConnector()
    try:
        urllib.request.urlopen = fake
        code, cap = call(["--doi", "10.1000/oa-001"])
        ck.eq(code, 0, "CLI：--doi 正常返回 0")
        ck.eq(fake.saved[0]["items"][0]["url"], "https://doi.org/10.1000/oa-001",
              "CLI：--doi 自动拼 https://doi.org/ 前缀")
    finally:
        urllib.request.urlopen = real

    # ---------- CLI：--urls 批量读文件 ----------
    lst = os.path.join(tmp, "urls.txt")
    with open(lst, "w", encoding="utf-8", newline="\n") as f:
        f.write("https://arxiv.org/abs/1\n\nhttps://arxiv.org/abs/2\n")
    fake = _FakeConnector()
    try:
        urllib.request.urlopen = fake
        code, cap = call(["--urls", lst])
        ck.eq(code, 0, "CLI：--urls 批量返回 0")
        ck.eq(len(fake.saved[0]["items"]), 2, "CLI：批量读入 2 条（跳过空行）")
    finally:
        urllib.request.urlopen = real

    return ck.report()


if __name__ == "__main__":
    run_main(run)
