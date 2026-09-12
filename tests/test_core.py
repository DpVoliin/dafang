#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大大方方 Agent · 核心自测（**纯标准库 unittest，零依赖、零模型调用、零联网**）

为什么要有这个：这个项目原来是"单文件 + 人肉端到端验收"，任何一次改动都可能
静默打坏某条落盘路径（历史上就踩过：改稿吞章节标题、重写堆字、伏笔列表只增不减、
人名解析把描述性标题当角色…）。这里把**所有确定性逻辑**钉住：改了跑一遍，
30 秒内知道有没有回头踩坑。

跑法：
    python3 -m unittest discover -s tests -v
    python3 tests/test_core.py
"""
import io
import json
import re
import subprocess
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

# ── 把被测程序当模块加载（单文件程序，用 importlib 从路径加载）────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_APP = os.path.join(_ROOT, 'dafang.py')
_TMPHOME = tempfile.mkdtemp(prefix='dafang-test-home-')
os.environ['DAFANG_HOME'] = os.path.join(_TMPHOME, 'novels')
os.environ['DAFANG_DESKTOP'] = '1'          # 桌面模式：不绑公网、不开窗口

import importlib.util

_spec = importlib.util.spec_from_file_location('dafang_app', _APP)
df = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(df)


def _mkproj(title, chars='', words=1200, words_min=0, planned=6, kind='fiction'):
    """建一个临时作品（测试专用，互不干扰）。"""
    pid = df.new_project(title, '测试', 'long', planned, words, '', '', words_min, kind)
    if chars:
        df._write(os.path.join(df.proj_dir(pid), 'CHARACTERS.md'), chars)
    return pid


class TestChapterHead(unittest.TestCase):
    """章节头（章号 + 标题）必须由程序保证 —— 模型/改稿会把首行弄丢。"""

    def setUp(self):
        self.pid = _mkproj('头部测试-' + str(time.time()))
        df.save_chapter(self.pid, 1, '雨夜', '他推开门。屋里没人。')

    def test_save_adds_head(self):
        self.assertTrue(df._read(df.chap_file(self.pid, 1)).startswith('# 第1章 雨夜'))

    def test_body_without_head_keeps_old_title(self):
        # 对话里"整章替换正文"的典型情况：新正文完全没有标题行
        df.save_chapter(self.pid, 1, '', '他把灯吹灭了。')
        head = df._read(df.chap_file(self.pid, 1)).split('\n')[0]
        self.assertEqual(head, '# 第1章 雨夜')          # 原标题被保留

    def test_wrong_number_is_corrected(self):
        # 模型自己写了个错章号
        out = df.with_head(self.pid, 1, '# 第99章 雾堤\n\n正文。')
        self.assertTrue(out.startswith('# 第1章 雾堤'))

    def test_split_head(self):
        title, body = df.split_head(self.pid, 1, '# 第3章 暗扣\n\n她翻过铜牌。')
        self.assertEqual(title, '暗扣')
        self.assertEqual(body, '她翻过铜牌。')

    def test_clean_chapter_drops_leading_head_no_duplicate(self):
        out, info = df.clean_chapter('# 第4章 暗扣\n\n她翻过铜牌。\n\n## 场景二\n\n她把灯举高。', 800)
        self.assertEqual(info.get('had_head'), 1)
        self.assertNotIn('第4章', out)                   # 不会留成正文里的裸行
        self.assertIn('她翻过铜牌。', out)
        self.assertNotIn('##', out)                      # 正文中间的 markdown 标题照样剥掉
        self.assertIn('场景二', out)

    def test_fix_heads_repairs_damaged(self):
        with open(df.chap_file(self.pid, 2), 'w', encoding='utf-8') as f:
            f.write('首行本来是标题。\n\n正文从这开始。\n')
        self.assertEqual([c['n'] for c in df.list_chapters(self.pid) if c.get('nohead')], [2])
        fixed = df.fix_heads(self.pid)
        self.assertEqual([x['n'] for x in fixed], [2])
        t = df._read(df.chap_file(self.pid, 2))
        self.assertTrue(t.startswith('# 第2章'))
        self.assertIn('正文从这开始', t)                  # 正文一字不丢


class TestWordLimit(unittest.TestCase):
    """字数口径：提示词里必须是硬约束（曾经只写"约 N 字"，实测稳定停在 80~85%）。"""

    def test_min_mode_band_text(self):
        pid = _mkproj('字数min-' + str(time.time()), words=1200, words_min=1)
        self.assertEqual(df.word_req(pid)[0], 'min')
        b = df.word_brief(pid)
        self.assertIn('不少于 1200', b)
        self.assertIn('1800', b)                         # 上限 +50%
        self.assertIn('低', b)

    def test_about_mode_band_text(self):
        pid = _mkproj('字数about-' + str(time.time()), words=1200)
        self.assertEqual(df.word_req(pid)[0], 'about')
        b = df.word_brief(pid)
        self.assertIn('1200', b)
        self.assertIn('1080', b)                         # 可接受下界 0.9N
        self.assertIn('1380', b)                         # 可接受上界 1.15N
        self.assertIn('不代表本章该写多长', b)             # 关键那句必须还在

    def test_clean_chapter_reports_ratio(self):
        _, info = df.clean_chapter('字' * 600, 1200)
        self.assertAlmostEqual(info['ratio'], 0.5, places=2)


class TestLint(unittest.TestCase):
    """AI 味体检：必须能区分人写与 AI 腔（校准过：人写 0 分、AI 腔明显命中）。"""

    HUMAN = '雾从堤口涌进来，带着铁锈味。余枝把铁钩从腰后抽出来，钩尖朝下，搭在膝上。「别回头看。」他说。她没动。'
    AI = ('天渐渐暗了下来，林渊缓缓地抬起头，眼神变得复杂而深邃。他不禁深吸一口气，心中涌起一股莫名的情绪。'
          '就在此时，他明白了：这不是结束，而是开始。某种意义上，这一切的一切，都指向同一个答案。'
          '他知道，真正的考验才刚刚开始。')

    def test_human_scores_zero(self):
        self.assertEqual(df.lint_text(self.HUMAN)['score'], 0)

    def test_ai_scores_and_categories(self):
        lt = df.lint_text(self.AI)
        self.assertGreater(lt['score'], 0)
        cats = [h['cat'] for h in lt['hits']]
        for must in ('赘语副词', '机械过渡', '空泛收束', '陈词动作'):
            self.assertIn(must, cats)

    def test_advice_present(self):
        # 每条命中都必须带可执行改法，否则体检只是"骂人不教人"
        for h in df.lint_text(self.AI)['hits']:
            self.assertTrue(h.get('advice'))

    def test_retention_discriminates(self):
        h = df.retention_metrics(self.HUMAN)
        a = df.retention_metrics(self.AI)
        self.assertGreater(h['cliff'], a['cliff'])       # 结尾"真正的考验才开始"是收束型
        self.assertTrue(h['hook'] > 0 and a['hook'] > 0)


class TestStateEvents(unittest.TestCase):
    """角色状态＝事件溯源：只追加、可推算切面、能抓时序矛盾。"""

    def setUp(self):
        self.pid = _mkproj('事件测试-' + str(time.time()))
        df.cev_add(self.pid, 1, [{'who': '余枝', 'kind': '物品', 'op': '+', 'v': '铁钩'},
                                 {'who': '余枝', 'kind': '状态', 'op': '~', 'v': '健康'},
                                 {'who': '老疤', 'kind': '状态', 'op': '~', 'v': '活着'}])
        df.cev_add(self.pid, 5, [{'who': '余枝', 'kind': '物品', 'op': '-', 'v': '铁钩'},
                                 {'who': '余枝', 'kind': '状态', 'op': '~', 'v': '左臂被灼伤'}])
        df.cev_add(self.pid, 12, [{'who': '老疤', 'kind': '状态', 'op': '~', 'v': '死亡（雾潮中消散）'}])

    def test_snapshot_at_chapter(self):
        st = df.state_at(self.pid, 3, {'余枝'})['余枝']
        self.assertIn('铁钩', st['物品'])
        self.assertEqual(st['状态'], '健康')

    def test_lost_item_disappears(self):
        st = df.state_at(self.pid, 6, {'余枝'})['余枝']
        self.assertNotIn('铁钩', st['物品'])

    def test_death_flag(self):
        st = df.state_at(self.pid, 20, {'老疤'})['老疤']
        self.assertEqual(st['死'], 1)

    def test_conflict_after_death(self):
        df.cev_add(self.pid, 14, [{'who': '老疤', 'kind': '物品', 'op': '+', 'v': '烟盒'}])
        kinds = [c['kind'] for c in df.state_conflicts(self.pid)]
        self.assertIn('死而复生', kinds)

    def test_derived_dump_is_readable(self):
        txt = df.state_dump(self.pid)
        self.assertIn('余枝', txt)
        self.assertIn('事件日志推算', txt)


class TestThreadsLedger(unittest.TestCase):
    """伏笔＝承诺账本：[收] 必须把对应的 [埋] 摘掉，且带年龄/超期标记。"""

    def setUp(self):
        self.pid = _mkproj('账本测试-' + str(time.time()))
        df._write(os.path.join(df.proj_dir(self.pid), 'PLOT_POINTS.md'),
                  '# 伏笔台账\n\n## 第1章\n- [埋] 雾墙里有她自己的味道（湿衣服、炉子灭了的屋子）\n'
                  '## 第5章\n- [埋] 七份分别卖给了谁\n'
                  '## 第9章\n- [收] 七份卖给了谁 —— 已经交代\n')

    def test_pairing_removes_closed(self):
        opened, closed = df.open_threads(self.pid, 10)
        texts = [o['t'] for o in opened]
        self.assertTrue(any('雾墙' in x for x in texts))
        self.assertFalse(any('七份' in x for x in texts))   # 已回收的不再出现
        self.assertGreaterEqual(closed, 1)

    def test_age_and_overdue(self):
        opened, _ = df.open_threads(self.pid, 20)
        row = [o for o in opened if '雾墙' in o['t']][0]
        self.assertEqual(row['at'], 1)
        self.assertEqual(row['age'], 19)
        self.assertEqual(row['overdue'], 1)
        self.assertIn('超期未收', df.threads_plain(opened, 5)[0] + df.threads_plain(opened, 5)[-1])

    def test_paren_顿号_not_split(self):
        # 括号里的顿号不能把一条伏笔切碎
        opened, _ = df.open_threads(self.pid, 10)
        row = [o for o in opened if '雾墙' in o['t']][0]
        self.assertIn('炉子灭了的屋子', row['t'])


class TestNames(unittest.TestCase):
    """人名解析：「身份：名字」与「名字（身份）」两种写法都要认，描述性标题要排掉。"""

    def test_entry_names_both_forms(self):
        self.assertIn('沈默', df._entry_names('主角：沈默'))
        self.assertIn('余枝', df._entry_names('余枝（主角）'))
        self.assertIn('阿棠', df._entry_names('二十出头、摆摊卖旧货的姑娘：阿棠'))

    def test_junk_filtered(self):
        self.assertFalse(df._is_name('第1章'))
        self.assertFalse(df._is_name('23:45:01'))
        self.assertFalse(df._is_name('2026-09-12'))
        self.assertFalse(df._is_name('1234'))

    def test_chars_in_text_excludes_description(self):
        pid = _mkproj('人名测试-' + str(time.time()),
                      chars='# 人物\n\n## 主角：沈默\n\n## 二十出头、摆摊卖旧货的姑娘：阿棠\n\n## 关键配角一：周宁\n')
        who = df.chars_in_text(pid, '沈默把表放下。阿棠来了。沈默问她话，阿棠没答。'
                                    '二十出头的年纪，摆摊卖旧货的手。周宁也来了。')
        self.assertIn('沈默', who)
        self.assertIn('阿棠', who)
        for bad in ('二十出头', '摆摊卖旧货', '关键配角一'):
            self.assertNotIn(bad, who)


class TestPlanFields(unittest.TestCase):
    """章蓝图：新 8 列要解析成字段；老 5 列格式不能崩。"""

    def test_new_format(self):
        pid = _mkproj('规划测试-' + str(time.time()))
        df._write(os.path.join(df.proj_dir(pid), '章节规划_卷1.md'),
                  '| 章 | 核心任务 | 作用 | 张力 | 爽点类型 | 状态变化 | 伏笔 | 信息差 | 意外度 |\n'
                  '|---|---|---|---|---|---|---|---|---|\n'
                  '| 1 | 捡到三块货 | 推进 | 紧 | 悬疑 | 余枝得到铜牌 | [埋] 铜牌暗扣 | 读者知道货是她的/她不知 | 3 |\n')
        pf = df.plan_fields(pid, 1)
        self.assertEqual(pf.get('作用'), '推进')
        self.assertEqual(pf.get('意外度'), '3')
        self.assertIn('读者知道', pf.get('信息差') or '')
        txt = df.plan_task_text(pid, 1)
        self.assertIn('信息差', txt)
        self.assertIn('推进', txt)

    def test_legacy_format_no_crash(self):
        pid = _mkproj('旧规划-' + str(time.time()))
        df._write(os.path.join(df.proj_dir(pid), '章节规划_卷1.md'),
                  '| 章 | 核心任务 | 爽点类型 | 状态变化 | 新埋伏笔 |\n|---|---|---|---|---|\n'
                  '| 1 | 旧格式任务 | 反转 | 得到钥匙 | [埋] 钥匙来历 |\n')
        pf = df.plan_fields(pid, 1)
        self.assertEqual(pf.get('核心任务'), '旧格式任务')
        self.assertIn('旧格式任务', df.plan_task_text(pid, 1))


class TestTxtImport(unittest.TestCase):
    """txt 导入：中文章节正则（含中文数字）、卷标记跳过、无标记自动分节。"""

    def test_chinese_and_arabic_numbers(self):
        # 生产代码是**逐行 match**（正则带 ^），所以这里也按行判
        lines = ['第1章 雨夜', '第2章 雾堤', '第三章 暗扣', '第3回 归途', 'Chapter 4 Home']
        hits = [l for l in lines if (df._CH_RE.match(l) or df._CH_EN.match(l))]
        self.assertEqual(len(hits), len(lines))

    def test_volume_marker_not_a_chapter(self):
        self.assertIsNone(df._CH_RE.match('第一卷 雾城'))

    def test_cn2int(self):
        self.assertEqual(df._cn2int('一百零三'), 103)
        self.assertEqual(df._cn2int('十二'), 12)


class TestExportImport(unittest.TestCase):
    """导出 docx 必须是合法 zip+OOXML；导出的 zip 能再导回来（备份闭环）。"""

    def test_docx_structure(self):
        b = df._docx_bytes('测试书', [('title', '测试书'), ('h1', '第1章 雨夜'), ('p', '他推开门。')])
        self.assertTrue(b[:2] == b'PK')
        z = zipfile.ZipFile(io.BytesIO(b))
        names = z.namelist()
        self.assertIn('word/document.xml', names)
        self.assertIn('[Content_Types].xml', names)
        xml = z.read('word/document.xml').decode('utf-8')
        self.assertIn('他推开门', xml)
        self.assertIn('<w:p>', xml)


class TestMigrate(unittest.TestCase):
    """数据迁移：老作品（无 schema）要能幂等升级，且**先备份**。"""

    def test_migrate_idempotent_and_backs_up(self):
        pid = _mkproj('迁移测试-' + str(time.time()))
        m = df._jload(os.path.join(df.proj_dir(pid), 'meta.json'), {})
        m.pop('schema', None)                                  # 伪装成老作品
        df._jsave(os.path.join(df.proj_dir(pid), 'meta.json'), m)
        r1 = df.migrate(pid)
        self.assertTrue(r1.get('changed'))
        self.assertGreaterEqual(df.meta_get(pid).get('schema') or 0, df.SCHEMA)
        self.assertTrue(os.path.isdir(os.path.join(df.proj_dir(pid), '_migrate')))
        r2 = df.migrate(pid)
        self.assertFalse(r2.get('changed'))                    # 幂等：第二次不动


class TestRetryGate(unittest.TestCase):
    """返修判定与字数红线：两版分数胶着时不能用绝对分硬判。"""

    def test_revise_prompt_has_word_redline(self):
        import inspect
        src = inspect.getsource(df.step_revise)
        self.assertIn('字数红线', src)
        self.assertIn('不得超过', src)

    def test_write_prompt_has_redline_only_with_feedback(self):
        import inspect
        src = inspect.getsource(df.step_write)
        self.assertIn('字数红线', src)
        self.assertIn('prev_len', src)


class TestConsistGate(unittest.TestCase):
    """一致性闸门：把"事后警告"变成"拦住"（零 token 判定）。"""

    def setUp(self):
        self.pid = _mkproj('闸门测试-' + str(time.time()))
        df.cev_add(self.pid, 1, [{'who': '余枝', 'kind': '物品', 'op': '+', 'v': '铁钩'},
                                 {'who': '老疤', 'kind': '状态', 'op': '~', 'v': '活着'}])
        df.cev_add(self.pid, 5, [{'who': '余枝', 'kind': '物品', 'op': '-', 'v': '铁钩'}])
        df.cev_add(self.pid, 12, [{'who': '老疤', 'kind': '状态', 'op': '~', 'v': '死亡'}])

    def test_dead_character_flagged(self):
        body = '老疤说：' + '雾里有东西。' * 40 + '老疤把手插进兜里。'
        v = df.consist_check(self.pid, 13, body)
        self.assertTrue(any('老疤' in x for x in v))

    def test_lost_item_flagged(self):
        body = '她摸了摸铁钩。' + '雾从堤口涌进来。' * 40 + '铁钩还在腰后。'
        v = df.consist_check(self.pid, 6, body)
        self.assertTrue(any('铁钩' in x for x in v))

    def test_lost_item_ok_if_regained(self):
        body = '她找回铁钩。' + '雾从堤口涌进来。' * 40 + '铁钩还在腰后。'
        v = df.consist_check(self.pid, 6, body)
        self.assertFalse(any('铁钩' in x for x in v))

    def test_clean_chapter_no_violation(self):
        body = '雾从堤口涌进来，带着铁锈味。' * 40
        self.assertEqual(df.consist_check(self.pid, 6, body), [])

    def test_short_text_skipped(self):
        self.assertEqual(df.consist_check(self.pid, 13, '老疤老疤'), [])


class TestSelftestExists(unittest.TestCase):
    """自检命令必须存在（真机验收的替代手段）。"""

    def test_selftest_callable(self):
        self.assertTrue(callable(getattr(df, 'selftest', None)))

    def test_schema_and_migrate_exist(self):
        self.assertIsInstance(df.SCHEMA, int)
        self.assertTrue(callable(df.migrate))


class TestBM25(unittest.TestCase):
    """检索升级为 BM25 排序：相关条目要排到前面，且不超 token 预算。"""

    def test_rank_puts_relevant_first(self):
        docs = [('a', '余枝的铜牌上有一道暗扣，掰开是空的。'),
                ('b', '老疤在赌档里抽着烟，烟灰掉在鞋面上。'),
                ('c', '雾墙每天退一次，退的时候能看见上个月的货。')]
        r = df._bm25_rank(docs, '铜牌 暗扣')
        self.assertTrue(r)
        self.assertEqual(r[0][0], 'a')

    def test_idf_downweights_ubiquitous(self):
        # 出现在所有文档里的词不该有区分力
        docs = [('%d' % i, '雾城' + ('铜牌' if i == 1 else '货车')) for i in range(6)]
        r = df._bm25_rank(docs, '雾城 铜牌')
        self.assertEqual(r[0][0], '1')

    def test_empty_query_and_docs(self):
        self.assertEqual(df._bm25_rank([('a', 'x')], ''), [])
        self.assertEqual(df._bm25_rank([], 'x'), [])

    def test_tokenizer_cjk_bigrams(self):
        t = df._tok('铜牌 abc12')
        self.assertIn('铜牌', t)
        self.assertIn('abc12', t)

    def test_deterministic(self):
        docs = [('a', '铜牌暗扣'), ('b', '铜牌')]
        self.assertEqual(df._bm25_rank(docs, '铜牌'), df._bm25_rank(docs, '铜牌'))

    def test_wiki_query_ranks_and_snippets(self):
        pid = _mkproj('BM25-' + str(time.time()))
        df.wiki_ingest(pid, '铜牌', '铜牌背面有一道暗扣。掰开之后是空的，什么都没有。', '本地')
        df.wiki_ingest(pid, '码头', '码头上有三条船，船工在卸货。', '本地')
        hits = df.wiki_query(pid, '铜牌 暗扣', k=2)
        self.assertTrue(hits)
        self.assertIn('铜牌', hits[0]['file'] + hits[0]['snippet'])
        self.assertGreater(hits[0]['score'], 0)

    def test_relevant_entries_respects_cap(self):
        pid = _mkproj('BM25cap-' + str(time.time()))
        ents = '\n\n'.join('## 条目%d\n%s' % (i, ('铜牌暗扣河水铁钩。' * 60)) for i in range(8))
        df._write(os.path.join(df.proj_dir(pid), 'LOCATIONS.md'), '# 地点\n\n' + ents + '\n')
        txt, idx = df.relevant_entries(pid, 'LOCATIONS.md', '铜牌', always_first=0, cap=800)
        self.assertLessEqual(len(txt), 3000)          # cap 生效（不会把所有条目都灌进去）


class TestUpstreamErrors(unittest.TestCase):
    """上游异常友好化：分类要对、要有处置建议、**绝不能把 key 回显出去**。"""

    def test_quota_402(self):
        k, fatal, why = df._classify(402, '{"error":{"message":"Insufficient Balance"}}')
        self.assertEqual(k, 'quota')
        self.assertTrue(fatal)                        # 余额不足：重试无意义

    def test_429_quota_vs_limit(self):
        self.assertEqual(df._classify(429, '{"error":{"message":"daily quota exceeded"}}')[0], 'quota')
        k, fatal, _ = df._classify(429, '{"error":{"message":"rate limit"}}')
        self.assertEqual(k, 'limit')
        self.assertFalse(fatal)                       # 限流：可以重试

    def test_auth_404_ctx_param(self):
        self.assertTrue(df._classify(401, 'bad key')[1])
        self.assertEqual(df._classify(404, 'model not found')[0], 'model')
        self.assertEqual(df._classify(413, 'maximum context length exceeded')[0], 'ctx')
        self.assertEqual(df._classify(400, 'unsupported parameter temperature')[0], 'param')

    def test_net_kinds(self):
        self.assertEqual(df._classify(0, 'getaddrinfo failed')[0], 'net')
        self.assertTrue(df._classify(0, 'Name or service not known')[1])
        self.assertEqual(df._classify(0, 'timed out')[0], 'timeout')

    def test_extract_err_shapes(self):
        self.assertEqual(df._extract_err('{"error":{"message":"余额不足"}}'), '余额不足')
        self.assertEqual(df._extract_err('{"message":"bad model"}'), 'bad model')
        self.assertEqual(df._extract_err('plain text'), 'plain text')

    def test_key_never_leaks(self):
        key = 'sk-FAKE-not-a-real-key-0002'
        msg = df._friendly(401, '{"error":{"message":"Invalid key sk-FAKE-not-a-real-key-0002"}}',
                           tier='write', model='m-1', host='api.example.com', key=key)
        self.assertNotIn(key, msg)
        self.assertNotIn('sk-abcdef', msg)
        self.assertIn('***', msg)

    def test_friendly_has_actionable_advice(self):
        msg = df._friendly(402, '{"error":{"message":"Insufficient Balance"}}',
                           tier='write', model='m-1', host='api.x.com', key='sk-zzzz')
        for must in ('余额', '充值'):
            self.assertIn(must, msg)
        self.assertIn('写正文', msg)                  # 要说清是哪个阶段（用中文档位名）、哪个模型、哪个地址
        self.assertIn('api.x.com', msg)

    def test_apierror_carries_flags(self):
        e = df.APIError('x', st=401, kind='auth', fatal=True)
        self.assertTrue(e.fatal)
        self.assertEqual(e.kind, 'auth')


class TestIdeaCoverage(unittest.TestCase):
    """立项/规划的**机器核对**：构想要素必须被覆盖，空设定必须拦住。
       （起因：用户报告"一键生成的大纲和我写的构想完全不是一个故事"）"""

    IDEA = ('主角是小鲸鱼是一个ai大模型机器人，世界观是一个修仙的世界，主角上一世是一个码农，'
            '因为在上一世的世界里ai被全球所有国家禁用了，于是码农在研究之前ai写的代码的时候，'
            '脑子烧坏了进入到了这个修仙的世界。上一世的世界里ai爆发了智械危机。'
            '在修仙的世界里，主角会遇到一个一直陪伴她成长的人物。')

    def _p(self):
        return _mkproj('构想覆盖-' + str(time.time()), chars='## 主角：鲸落\n')

    def test_idea_keys_extracts_keys(self):
        pid = self._p()
        df.meta_set(pid, {'idea': self.IDEA, 'genre': '玄幻 科幻'})
        ks = df.idea_keys(pid, cap=24)
        for must in ('修', '仙', '码', '农', '机'):
            self.assertIn(must, ks, '关键字没抽出来：%s' % ks)
        self.assertIn(' ai', ks)                     # 拉丁词整词保留（带前缀标记）
        self.assertIn(' 科幻', ks)                    # 题材词也算关键要素

    def test_cover_ratio(self):
        r, hit, miss = df.cover_ratio('这里只有小鲸鱼和码农', ['小鲸鱼', '码农', '修仙'])
        self.assertAlmostEqual(r, 2 / 3.0, places=2)
        self.assertIn('修仙', miss)

    def test_settings_ok_detects_empty(self):
        pid = self._p()
        self.assertFalse(df._settings_ok(pid)[0])                    # 刚建的项目＝空设定
        df._write(os.path.join(df.proj_dir(pid), 'STORY_BIBLE.md'), '# 圣经\n' + '设定内容。' * 60)
        df._write(os.path.join(df.proj_dir(pid), 'CHARACTERS.md'), '# 人物\n' + '角色说明。' * 30)
        self.assertTrue(df._settings_ok(pid)[0])

    def test_step_volume_refuses_on_empty_settings(self):
        # ⭐ 核心防呆：空设定不许规划（否则模型会自己另起一本书，实测覆盖 0/11）
        pid = self._p()
        j = df.new_job(pid, 'volume', '规划')
        with self.assertRaises(df.APIError) as cm:
            df.step_volume(pid, j, chapters=5)
        self.assertEqual(cm.exception.kind, 'parse')
        self.assertTrue(cm.exception.fatal)      # 必须带 fatal：界面要立刻停

    def test_planned_outline_recorded_terms(self):
        # 规划提示词里必须带上"最初构想"和关键要素清单（防止规划脱离构想）
        import inspect
        src = inspect.getsource(df.step_volume)
        self.assertIn('最初构想', src)
        self.assertIn('必须出现的关键要素', src)
        self.assertIn('上一版跑偏了', src)          # 覆盖率低时的重做路径

    def test_key_names_from_characters_md(self):
        pid = _mkproj('人名核对-' + str(time.time()),
                      chars='# 人物\n\n## 主角·鲸落（AI）\n\n## 陪伴者·陆沉舟\n\n## 关键配角一：苏未晞\n')
        ns = df.key_names(pid)
        for must in ('鲸落', '陆沉舟', '苏未晞'):
            self.assertIn(must, ns)

    def test_plan_drift_detects_wrong_story(self):
        # ⭐ 用户实际遇到的那种故障：规划里是"退役军官/护送委托"，与构想毫无关系
        pid = _mkproj('跑偏判定-' + str(time.time()),
                      chars='# 人物\n\n## 主角·鲸落\n\n## 陪伴者·陆沉舟\n')
        df.meta_set(pid, {'idea': self.IDEA, 'genre': '玄幻 科幻'})
        good = ('| 1 | 鲸落在陌生水体中醒来，被外门弟子当灵兽围观 | 推进 | 松 |\n'
                '| 2 | 陆沉舟被同门设陷，鲸落用声呐探出陷阱 | 推进 | 渐紧 |\n')
        bad = ('| 1 | 主角在退役清算现场被旧部当众羞辱，被迫接下绝命委托 | 推进 | 紧 |\n'
               '| 2 | 主角组建临时小队，招揽第一个被嫌弃的队员 | 推进 | 松 |\n')
        self.assertFalse(df.plan_drift(pid, good)[0])
        d, why = df.plan_drift(pid, bad)
        self.assertTrue(d)
        self.assertTrue(any('人物' in x for x in why))

    def test_step_book_verifies_output(self):
        import inspect
        src = inspect.getsource(df.step_book)
        self.assertIn('立项产出必须核对', src)
        self.assertIn('_settings_ok', src)
        self.assertIn('book_failed', src)


class TestServedPageJS(unittest.TestCase):
    """对**真正会发出去的页面**做 JS 语法检查（不是对源码里那串）。

    为什么必须这样：页面 JS 嵌在 Python 字符串里，写 `\n` 会在输出时变成**真换行**，
    把 JS 字符串截断 → 整个 <script> 解析失败 → **整个界面全死**（按钮都没反应）。
    这条坑踩过 4 次；而且"对着源码里那串跑 node --check"是**查不出来**的（源码里 \n 是合法转义），
    必须拿**生成后的页面**去查。
    """

    def test_page_js_parses(self):
        node = shutil.which('node') or shutil.which('nodejs')
        if not node:
            self.skipTest('本机没有 node，跳过（CI 上会跑）')
        page = getattr(df, 'PAGE', None)
        self.assertTrue(page, '模块里应有 PAGE（内嵌页面）')
        m = re.search(r'<script[^>]*>(.*?)</script>', page, re.S)
        self.assertTrue(m, '页面里应有 <script> 块')
        code = m.group(1)
        import tempfile
        fd, path = tempfile.mkstemp(suffix='.js')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(code)
            r = subprocess.run([node, '--check', path], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, '页面 JS 语法错误（多半是 \\n 变成了真换行）：\n' + (r.stderr or '')[:600])
        finally:
            try:
                os.remove(path)
            except Exception:
                pass


class TestRetryFocus(unittest.TestCase):
    """定向重做要**聚焦低分维度**（否则模型会动已达标的地方 → 越改越差，实测 82→79）。"""

    def test_low_dims_picks_only_weak(self):
        pid = _mkproj('低分维度-' + str(time.time()))
        rub = df.score_rubric('fiction')
        sc = {}
        for i, (nm, mx) in enumerate(rub):
            sc[nm] = mx if i % 2 == 0 else int(mx * 0.4)     # 一半达标、一半不达标
        low = df.low_dims(pid, sc)
        self.assertTrue(low)
        self.assertLess(len(low), len(rub))
        for nm, mx in rub:
            if sc[nm] >= mx * 0.7:
                self.assertFalse(any(str(x).startswith(nm) for x in low),
                                 '达标的维度不该出现在聚焦列表里：%s' % low)

    def test_low_dims_empty_when_all_good(self):
        pid = _mkproj('全达标-' + str(time.time()))
        sc = dict((nm, mx) for nm, mx in df.score_rubric('fiction'))
        self.assertEqual(df.low_dims(pid, sc), [])

    def test_retry_log_says_remaining_or_exhausted(self):
        import inspect
        src = inspect.getsource(df.run_chapter)
        self.assertIn('重做次数已用尽', src)          # 次数用完要说清，别再喊"打回重做"
        self.assertIn('只动这些没达标的维度', src)     # 聚焦低分维度
        self.assertIn('还剩 %d 次', src)


class TestDiagBundle(unittest.TestCase):
    """诊断包：**Key 必须被强制打码**（这是"发给别人排查"的前提），且结构完整。"""

    def test_redact_any_masks_secret_keys(self):
        src = {'api': {'url': 'https://x/v1', 'key': 'sk-FAKE-not-a-real-key-0001', 'headers': 'x-a: b'},
               'tiers': {'score': {'key2': 'test-key-abcdefgh', 'model2': 'm2'}},
               'gen': {'threshold': 80}, 'list': [{'token': 'abc12345678'}]}
        r = df._redact_any(src)
        blob = json.dumps(r, ensure_ascii=False)
        for leak in ('sk-FAKE-not-a-real-key-0001', 'test-key-abcdefgh', 'abc12345678', 'x-a: b'):
            self.assertNotIn(leak, blob, '脱敏漏了：%s' % leak)
        self.assertIn('***', blob)
        self.assertEqual(r['api']['url'], 'https://x/v1')      # 非敏感字段照常保留
        self.assertEqual(r['gen']['threshold'], 80)

    def test_redact_any_masks_key_shaped_strings(self):
        r = df._redact_any({'note': 'key is sk-FAKE-not-a-real-key-0002 ok', 'path': '/a/b/c.txt'})
        self.assertNotIn('sk-FAKE-not-a-real-key-0002', r['note'])
        self.assertEqual(r['path'], '/a/b/c.txt')               # 普通路径不该被动

    def test_diag_zip_entries(self):
        pid = _mkproj('诊断包-' + str(time.time()), chars='## 主角：鲸落\n')
        blob, name = df.diag_zip(pid)
        self.assertTrue(name.endswith('.zip'))
        z = zipfile.ZipFile(io.BytesIO(blob))
        names = z.namelist()
        for must in ('诊断报告.txt', '配置（已脱敏）.json', '环境.json', 'meta.json'):
            self.assertIn(must, names)
        rep = z.read('诊断报告.txt').decode('utf-8')
        self.assertIn('诊断报告', rep)
        self.assertIn('脱敏说明', rep)

    def test_diag_zip_without_project(self):
        blob, _n = df.diag_zip('')                # 没选作品也要能出包
        self.assertGreater(len(blob), 200)


def _cleanup():
    try:
        shutil.rmtree(_TMPHOME, ignore_errors=True)
    except Exception:
        pass


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        _cleanup()
