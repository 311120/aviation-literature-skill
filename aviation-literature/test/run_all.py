#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证集总入口：跑全部用例，任一失败整体非零退出。

用法：
  python test/run_all.py            # 全部用例
  python test/run_all.py --verbose  # 打印每个用例的失败明细

夹具由 test/fixtures/make_fixtures.py 现场合成到系统临时目录，
全部手写、复刻真实结构，不含任何第三方真实文档或技能包。
"""
import argparse
import importlib
import os
import sys
import time

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)

MODULES = ["test_parse", "test_cli", "test_grab", "test_zotero", "test_boundary"]


def main():
    ap = argparse.ArgumentParser(description="运行 aviation-literature 验证集")
    ap.add_argument("--verbose", action="store_true", help="打印用例级明细（默认已打印失败项）")
    ap.add_argument("--only", metavar="NAME", help="只跑指定用例模块")
    args = ap.parse_args()

    modules = [args.only] if args.only else MODULES

    print("=" * 66)
    print(f"aviation-literature 验证集 · {len(modules)} 个套件")
    print("=" * 66)

    total_pass, total_fail, failed_modules = 0, 0, []
    t0 = time.time()
    for name in modules:
        print(f"\n[{name}]")
        try:
            mod = importlib.import_module(name)
        except Exception as e:                      # noqa: BLE001
            print(f"  [FAIL] 用例模块导入失败：{type(e).__name__}: {e}")
            failed_modules.append(name)
            total_fail += 1
            continue
        try:
            p, f = mod.run()
        except Exception as e:                      # noqa: BLE001
            print(f"  [FAIL] 用例执行中断：{type(e).__name__}: {e}")
            failed_modules.append(name)
            total_fail += 1
            continue
        total_pass += p
        total_fail += f
        if f:
            failed_modules.append(name)

    elapsed = time.time() - t0
    print("\n" + "=" * 66)
    print(f"合计：通过 {total_pass} 项，失败 {total_fail} 项，耗时 {elapsed:.1f}s")
    if failed_modules:
        print(f"未通过的套件：{', '.join(failed_modules)}")
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
