#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试公共设施：路径常量、夹具装载、极简断言器。纯标准库，无第三方依赖。

夹具由 `fixtures/make_fixtures.py` 现场合成，写到系统临时目录，**不落在技能包内**，
因此仓库里不含任何生成物，也没有任何第三方真实文档。

各用例文件暴露 `run()`，返回 (通过数, 失败数)；run_all.py 汇总后决定退出码。
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TEST_DIR)
SCRIPTS = os.path.join(ROOT, "scripts")
FIXTURE_MODULE_DIR = os.path.join(TEST_DIR, "fixtures")
FIXTURE_DATA_DIR = os.environ.get(
    "AVLIT_FIXTURES", os.path.join(tempfile.gettempdir(), "avlit_fixtures"))

for _p in (SCRIPTS, TEST_DIR, FIXTURE_MODULE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def build_all(target):
    """调用夹具构造器。"""
    from make_fixtures import build_all as _b
    return _b(target)


def make_temp_dir(prefix, parent=None):
    """建用例用的临时目录，并在随机名目录不可写时降级。

    为什么不能只用 `tempfile.mkdtemp()`：受限环境（如 DSH 的 workspace-write 沙箱）
    下它会**建成功却写不进去**——mkdtemp 本身不报错，写第一个文件才 PermissionError，
    整套用例就此崩掉，看起来像是代码缺陷。所以这里建完**立刻验证可写性**，
    不行就换成固定名目录（父目录已存在时在同样环境下可写）。
    """
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
    base = parent or FIXTURE_DATA_DIR
    os.makedirs(base, exist_ok=True)
    d = os.path.join(base, prefix + uuid.uuid4().hex[:8])
    os.makedirs(d, exist_ok=True)
    return d


@contextlib.contextmanager
def quiet():
    """吞掉被测代码的 stdout/stderr，让验证集报告保持可读。"""
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            yield


@contextlib.contextmanager
def capture():
    """同时捕获被测代码的 stdout 与 stderr，退出时把两段文本写入一个对象。"""

    class _Cap:
        out = ""
        err = ""

    cap = _Cap()
    o, e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
        yield cap
    cap.out, cap.err = o.getvalue(), e.getvalue()


def fixture_data_dir():
    """确保夹具已就绪，返回承载数据的目录。

    除"目录不存在就生成"外，还比对夹具源码与构建标记（.built）的 mtime：
    源码更新过就强制重建。否则改了 make_fixtures.py 之后旧缓存会静默生效，
    制造出一批与代码无关的假失败。

    注：用 .built 标记而非目录 mtime——makedirs(exist_ok=True) 不会更新
    已存在目录的时间戳，拿目录 mtime 当锚点会让整个检测形同虚设。
    """
    payloads = os.path.join(FIXTURE_DATA_DIR, "payloads")
    src = os.path.join(FIXTURE_MODULE_DIR, "make_fixtures.py")
    stamp = os.path.join(FIXTURE_DATA_DIR, ".built")
    needs_build = not os.path.isdir(payloads) or not os.path.isfile(stamp)
    if not needs_build and os.path.isfile(src):
        needs_build = os.path.getmtime(src) > os.path.getmtime(stamp)
    if needs_build:
        build_all(FIXTURE_DATA_DIR)
    return FIXTURE_DATA_DIR


def load_json(name):
    import json
    with open(os.path.join(fixture_data_dir(), "payloads", name), encoding="utf-8") as f:
        return json.load(f)


def load_text(name):
    with open(os.path.join(fixture_data_dir(), "payloads", name), encoding="utf-8") as f:
        return f.read()


class Checker:
    def __init__(self, name):
        self.name = name
        self.passed = 0
        self.failures = []

    def check(self, cond, label):
        if cond:
            self.passed += 1
        else:
            self.failures.append(label)
            print(f"  [FAIL] {label}")
        return bool(cond)

    def eq(self, got, want, label):
        if got == want:
            self.passed += 1
            return True
        self.failures.append(f"{label}（期望 {want!r}，实际 {got!r}）")
        print(f"  [FAIL] {label}（期望 {want!r}，实际 {got!r}）")
        return False

    def contains(self, haystack, needle, label):
        if needle in (haystack or ""):
            self.passed += 1
            return True
        self.failures.append(f"{label}（未找到 {needle!r}）")
        print(f"  [FAIL] {label}（未找到 {needle!r}）")
        return False

    def not_contains(self, haystack, needle, label):
        if needle not in (haystack or ""):
            self.passed += 1
            return True
        self.failures.append(f"{label}（不应出现 {needle!r}）")
        print(f"  [FAIL] {label}（不应出现 {needle!r}）")
        return False

    def report(self):
        print(f"  {self.name}: 通过 {self.passed} 项，失败 {len(self.failures)} 项")
        return self.passed, len(self.failures)


def run_main(module_main):
    """用例文件的标准收尾：`if __name__ == '__main__': run_main(run)`。"""
    _, f = module_main()
    sys.exit(1 if f else 0)
