#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大大方方 Agent · 卸载 / 彻底清理本机文件

作用：卸载这个程序 —— 删掉应用窗口缓存、自检报告，可选**连程序文件夹一起删**。

      ⚠️ **默认绝不动你的作品目录**（稿子、设定、配置都在那里，会原样留着）。
         只有你显式加 --purge-data 才会把它删掉；加 --purge-config 只删配置里的 API Key，稿子照旧保留。

用法（在本文件所在目录执行）：
    python uninstall.py                        # 交互式：先列清单，再问你确认（推荐）
    python uninstall.py --dry-run              # 只看会删什么，绝不动手
    python uninstall.py --yes                  # 不问，删缓存/报告（作品目录保留）
    python uninstall.py --yes --purge-program   # 连程序文件夹一起删（干净卸载，稿子仍在）
    python uninstall.py --yes --purge-config    # 额外删掉配置（里面的 API Key），稿子保留
    python uninstall.py --yes --purge-data      # 额外删掉**整个作品目录**（稿子也删！慎用）

安全承诺：
  · 只删下面 `targets()` 里**逐个列出来的已知路径**，绝不递归乱扫、不碰别的目录；
  · 每一条都先打印它的实际路径与大小，删完打印结果；
  · **作品目录默认只"报告"不"删除"** —— 如果哪里需要删，清单里会写清为什么。
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time


# Windows 的 cmd 默认是 cp936，直接 print 中文会 UnicodeEncodeError —— 先兜住
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return '%.1f %s' % (n, u)
        n /= 1024.0


def size_of(p):
    if os.path.isfile(p):
        try:
            return os.path.getsize(p)
        except Exception:
            return 0
    tot = 0
    for r, _ds, fs in os.walk(p):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(r, f))
            except Exception:
                pass
    return tot


def home_candidates():
    """桌面版可能把作品放这几个地方（与程序里的 _default_home 一致）。"""
    h = os.path.expanduser('~')
    out = []
    for c in (os.path.join(h, 'Documents'), os.path.join(h, 'OneDrive', 'Documents'),
              os.path.join(h, 'OneDrive', '文档'), os.path.join(h, '文档'),
              os.path.join(h, 'Desktop'), h):
        if os.path.isdir(c):
            p = os.path.join(c, '大大方方Agent')
            if p not in out:
                out.append(p)
    out.append(os.path.join(h, '.dafang'))          # 服务版 / 兜底
    return out


def targets(build_dir, purge_data=False, purge_config=False):
    """返回 [(分组, 说明, 路径, 是否可恢复)] —— 全部是"已知位置"，不含通配乱删。

       分组含义：
         缓存 = 默认就删（浏览器缓存、自检报告，删了没影响）
         程序 = 加 --purge-program 才删（程序文件夹本体）
         数据 = **默认绝不删**；只有 --purge-data 才删整个作品目录
         配置 = 只有 --purge-config 才删（只清 config.json，也就是 API Key；稿子保留）
         保留 = 只报告、不删（让用户知道东西还在哪）"""
    t = []
    for p in home_candidates():
        if not os.path.exists(p):
            continue
        if purge_data:
            t.append(('数据', '作品目录（含稿子/设定/配置/日志/回收站）', p, False))
        else:
            t.append(('保留', '作品目录 —— **不动它**（你的稿子与设定都在这里）', p, False))
        # --purge-config：只删配置（API Key），稿子留着
        cfg = os.path.join(p, 'config.json')
        if purge_config and os.path.isfile(cfg):
            t.append(('配置', '配置（里面是你的 API Key）', cfg, False))
        lg = os.path.join(p, 'logs')
        if purge_config and os.path.isdir(lg):
            t.append(('配置', '请求日志（开着才有的那个 llm_io 日志）', lg, True))
    for p in sorted(glob.glob(os.path.join(os.path.expanduser('~'), '.dafang-webview-*'))):
        t.append(('缓存', '应用窗口的浏览器缓存（按版本分开的，可随便删）', p, True))
    for p in (os.path.join(os.path.expanduser('~'), '大大方方自检报告.txt'),
              os.path.join(os.path.expanduser('~'), 'dafang-selftest-report.txt')):
        if os.path.exists(p):
            t.append(('缓存', '自检报告（--selftest 生成的）', p, True))
    if build_dir:
        t.append(('程序', '程序文件夹（本体；--purge-program 才会删）', build_dir, False))
    return t


def kill_instances():
    """先把还在跑的「大方」进程关掉 —— 不然 Windows 上文件被占用，删不掉。
       只杀命令行里含 dafang.py 的进程，**不碰**别的 python 程序。"""
    killed = 0
    try:
        if os.name == 'nt':
            ps = ('Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*dafang.py*" } '
                  '| ForEach-Object { try{ Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }catch{} }')
            r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                               capture_output=True, text=True, timeout=25)
            killed = len([x for x in (r.stdout or '').split() if x.strip().isdigit()])
        else:
            r = subprocess.run(['pkill', '-f', 'dafang.py'], capture_output=True, text=True)
            killed = 1 if r.returncode == 0 else 0
            time.sleep(0.8)
    except Exception:
        pass
    return killed


def purge_program_later(build_dir):
    """删掉程序文件夹本身。
       Windows 上不能"自己删自己所在的目录"：先落一个临时小脚本，等本进程退出后再删。"""
    if os.name != 'nt':
        ok = shutil.rmtree(build_dir, ignore_errors=True) is None and not os.path.exists(build_dir)
        return ok
    helper = os.path.join(tempfile.gettempdir(), '_df_uninstall_helper.py')
    code = (
        "import os, shutil, time, sys\n"
        "p = %r\n"
        "for i in range(6):\n"
        "    shutil.rmtree(p, ignore_errors=True)\n"
        "    if not os.path.exists(p):\n"
        "        break\n"
        "    time.sleep(1.0)\n"
        "try:\n"
        "    os.remove(os.path.abspath(__file__))\n"
        "except Exception:\n"
        "    pass\n" % build_dir)
    with open(helper, 'w', encoding='utf-8') as f:
        f.write(code)
    try:
        flags = 0
        if hasattr(subprocess, 'DETACHED_PROCESS'):
            flags |= subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, helper], creationflags=flags, close_fds=True)
        return True
    except Exception as e:
        print('  ⚠️ 启动清理助手失败：%s' % e)
        return False


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--dry-run', action='store_true', help='只列出会删什么，不动手')
    ap.add_argument('--yes', action='store_true', help='不询问，直接删')
    ap.add_argument('--purge-program', action='store_true', help='连程序文件夹一起删')
    ap.add_argument('--purge-data', action='store_true',
                    help='【慎用】连作品目录（稿子）一起删 —— 默认不动作品目录')
    ap.add_argument('--purge-config', action='store_true',
                    help='额外删掉配置 config.json（里面的 API Key）；稿子保留')
    args = ap.parse_args()

    build_dir = os.path.dirname(os.path.abspath(__file__))
    ts = targets(build_dir, purge_data=args.purge_data, purge_config=args.purge_config)
    data = [x for x in ts if x[0] == '数据']
    cache = [x for x in ts if x[0] == '缓存']
    prog = [x for x in ts if x[0] == '程序']
    conf = [x for x in ts if x[0] == '配置']
    keep = [x for x in ts if x[0] == '保留']

    print('=' * 64)
    print('大大方方 Agent · 卸载清理')
    print('=' * 64)
    print('程序位置：%s' % build_dir)
    print()
    print('【会删除的数据】← 默认**没有这一项**（作品目录不动）；只有加 --purge-data 才有')
    if not data:
        print('   （无 —— 你的稿子在下面【保留】里，不会被删）')
    for _g, d, p, _r in data:
        print('   · %s\n       %s  (%s)' % (d, p, human(size_of(p))))
    if conf:
        print()
        print('【会删除的配置】← 只删 API Key，稿子不动（--purge-config）')
        for _g, d, p, _r in conf:
            print('   · %s\n       %s  (%s)' % (d, p, human(size_of(p))))
    print()
    print('【会删除的缓存/报告】← 删了没影响')
    if not cache:
        print('   （没找到）')
    for _g, d, p, _r in cache:
        print('   · %s\n       %s  (%s)' % (d, p, human(size_of(p))))
    print()
    print('【程序本体】%s' % ('（本次会一起删）' if args.purge_program else '（保留；要一起删就加 --purge-program）'))
    for _g, d, p, _r in prog:
        print('   · %s  (%s)' % (p, human(size_of(p))))
    print()
    print('【保留（不会动）】')
    if not keep:
        print('   （没找到）')
    for _g, d, p, _r in keep:
        print('   · %s\n       %s  (%s)' % (d, p, human(size_of(p))))
    print()

    if args.dry_run:
        print('（--dry-run：什么都没删。）')
        return 0

    if not (data or cache or conf or (args.purge_program and prog)):
        print('没有找到需要删除的东西，收工。')
        return 0

    if not args.yes:
        if data:
            print('⚠️  你加了 --purge-data：上面【会删除的数据】里包含**你的稿子**，删了无法恢复！')
        elif conf:
            print('⚠️  你加了 --purge-config：会删掉配置里的 API Key（稿子不动）。')
        a = input('确认删除？（输入 yes 才会删，其它任何输入＝放弃）: ').strip().lower()
        if a != 'yes':
            print('已放弃，什么都没删。')
            return 0

    n = kill_instances()
    if n:
        print('已关闭 %d 个正在运行的「大方」进程。' % n)

    ok, fail = 0, 0
    for _g, desc, p, _r in (data + cache + conf):
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=False)
            elif os.path.isfile(p):
                os.remove(p)
            else:
                continue
            gone = not os.path.exists(p)
            print('  %s 删除：%s' % ('✅' if gone else '⚠️', p))
            ok += 1 if gone else 0
            fail += 0 if gone else 1
        except Exception as e:
            print('  ❌ 删不掉：%s（%s）' % (p, str(e)[:70]))
            fail += 1

    if args.purge_program and prog:
        print('正在删除程序文件夹…（它会等本进程退出后自己删干净）')
        if purge_program_later(build_dir):
            time.sleep(1.5)
            print('  ✅ 已安排删除：%s' % build_dir)
        else:
            print('  ⚠️ 没能自动删，请手动删除这个文件夹：%s' % build_dir)

    print()
    print('=' * 64)
    print('完成：删掉 %d 项，失败 %d 项。' % (ok, fail))
    if fail:
        print('失败的多半是"文件正被占用"：把大方窗口都关掉（或重启一次电脑）再跑一遍。')
    if not args.purge_program:
        print('程序本体还留着：不想要了就把它的文件夹直接删掉。')
    if keep and not args.purge_data:
        print('你的作品目录**没有被删**（稿子、设定都在原地）：')
        for _g, _d, p, _r in keep:
            print('   %s' % p)
        print('   连这些也要清掉：加 --purge-data（会删稿子，想清楚再跑）')
    print('=' * 64)
    return 0


if __name__ == '__main__':
    sys.exit(main())
