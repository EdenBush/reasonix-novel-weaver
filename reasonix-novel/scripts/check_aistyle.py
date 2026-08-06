#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 统计指纹检测（软指纹，分布层面）
识别"分布均匀"型 AI 痕迹——单句检查抓不到，但统计会露馅：
1. 段落长度分布：人类长段短段交替（方差大），AI 均匀（方差小）
2. 对话比例：人类各章对话比例波动大，AI 稳定在 30-40%
3. 转折词密度：然而/但是/却/竟——AI 爱用转折制造张力
4. 直接情绪词密度：愤怒/悲伤/恐惧——AI 爱直接写出情绪
5. 高频动作短语："皱起眉头/握紧拳头"——AI 反复调用同一动作标签
6. 模糊词密度：仿佛/似乎/好像/宛如——AI 爱用模糊词加"文学感"

注意：这是"软指纹"，只给风险提示，不判死刑（人类也可能有一项偏高）。
用法:
  python check_aistyle.py <章节文件.md>          # 单章统计
  python check_aistyle.py --all <项目目录>       # 全书统计（含各章对话比例一致性）
"""

import argparse
import io
import re
import statistics
import sys
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 词典
TRANSITION_WORDS = ['然而', '但是', '可是', '却', '竟', '反倒', '反而', '不过', '然而事实上']
EMOTION_WORDS = ['愤怒', '悲伤', '恐惧', '痛苦', '绝望', '激动', '委屈', '欣喜', '慌乱', '愧疚',
                 '心碎', '窒息', '崩溃', '震惊', '不安', '愤怒到', '心如刀绞', '心头一紧', '眼里', '浑身']
FUZZY_WORDS = ['仿佛', '似乎', '好像', '宛如', '像是', '如同', '好比', '依稀', '隐约']
# 动作短语（4-6 字高频动作标签，检测重复调用）
ACTION_PATTERNS = ['皱起眉头', '握紧拳头', '深吸一口气', '低下头', '抬起头', '别过脸', '转过身',
                   '握了握', '张了张嘴', '抿了抿嘴', '叹了口气', '眨了眨眼', '攥紧', '垂下眼',
                   '攥了攥', '心头一颤', '瞳孔一缩', '嘴角勾起', '喉结动了动']


def extract_body(text: str) -> str:
    lines = text.split('\n')
    out, skip_block, skip_qc = [], False, False
    for raw in lines:
        line = raw.strip()
        if line.startswith('【本章质检摘要】'):
            skip_qc = True
            continue
        if skip_qc:
            if line == '---':
                skip_qc = False
            continue
        if any(line.startswith(b) for b in ('## 本章概要', '## 章节备注', '## 章节概要')):
            skip_block = True
            continue
        if skip_block:
            if line.startswith('#') or line == '---':
                skip_block = False
            if skip_block:
                continue
        if line.startswith('## '):
            continue
        if line == '---':
            continue
        out.append(line)
    return '\n'.join(out)


def count_word(text: str, word: str) -> int:
    return text.count(word)


def analyze_chapter(file_path: Path) -> dict:
    text = file_path.read_text(encoding='utf-8')
    body = extract_body(text)
    if not body.strip():
        return None

    # 1. 段落长度分布
    paras = [p.strip() for p in re.split(r'\n\s*\n', body) if p.strip()]
    para_lens = [len(re.sub(r'\s', '', p)) for p in paras]
    cv_para = (statistics.stdev(para_lens) / statistics.mean(para_lens)) if len(para_lens) > 3 and statistics.mean(para_lens) > 0 else 0

    # 2. 对话比例（引号内容占比）
    quotes = re.findall(r'["“]([^"”]{2,})["”]', body)
    quote_chars = sum(len(q) for q in quotes)
    body_chars = len(re.sub(r'\s', '', body))
    dialog_ratio = (quote_chars / body_chars) if body_chars > 0 else 0

    # 3-6. 词频（每千字）
    total = body_chars / 1000.0
    if total <= 0:
        total = 0.001
    trans_density = sum(count_word(body, w) for w in TRANSITION_WORDS) / total
    emotion_density = sum(count_word(body, w) for w in EMOTION_WORDS) / total
    fuzzy_density = sum(count_word(body, w) for w in FUZZY_WORDS) / total

    # 7. 动作短语重复
    action_hits = {}
    for pat in ACTION_PATTERNS:
        n = body.count(pat)
        if n >= 2:
            action_hits[pat] = n
    repeated_actions = sum(1 for n in action_hits.values() if n >= 3)

    return {
        'file': file_path.name,
        'para_cv': round(cv_para, 2),
        'para_n': len(para_lens),
        'dialog_ratio': round(dialog_ratio, 3),
        'trans_density': round(trans_density, 1),
        'emotion_density': round(emotion_density, 1),
        'fuzzy_density': round(fuzzy_density, 1),
        'action_hits': action_hits,
        'repeated_actions': repeated_actions,
    }


def flag_level(metric, value, thresholds):
    """根据 [低, 中, 高] 阈值返回风险等级"""
    if value >= thresholds[2]:
        return '高'
    if value >= thresholds[1]:
        return '中'
    return '低'


def print_chapter(r: dict, full: bool = False):
    print(f'\n===== {r["file"]} =====')
    print(f'段落长度变异系数 CV={r["para_cv"]}（{r["para_n"]} 段）'
          f' → {flag_level(None, r["para_cv"], [0.6, 0.8, 1.0])}'
          f' [CV 低=段长均匀(AI), 高=长短交替(人)]')
    print(f'对话占比 {r["dialog_ratio"]*100:.0f}%'
          f' → {flag_level(None, r["dialog_ratio"], [0.55, 0.7, 0.9])}'
          f' [过高=全功能性对话风险]')
    print(f'转折词密度 {r["trans_density"]}/千字'
          f' → {flag_level(None, r["trans_density"], [2.0, 3.5, 5.0])}'
          f' [高=爱用"然而/但是"制造张力]')
    print(f'直接情绪词密度 {r["emotion_density"]}/千字'
          f' → {flag_level(None, r["emotion_density"], [1.0, 2.0, 3.0])}'
          f' [高=情绪被直接说出而非演出]')
    print(f'模糊词密度 {r["fuzzy_density"]}/千字'
          f' → {flag_level(None, r["fuzzy_density"], [1.5, 2.5, 4.0])}'
          f' [高=仿佛/似乎堆砌]')
    if r['action_hits']:
        print(f'动作短语重复：{"、".join(f"{k}×{v}" for k, v in r["action_hits"].items())}'
              f' → {flag_level(None, r["repeated_actions"], [1, 2, 3])}'
              f' [重复≥3次=角色动作指纹]')
    else:
        print('动作短语重复：无')


def main():
    parser = argparse.ArgumentParser(description='AI 统计指纹检测（分布层面软指纹）')
    parser.add_argument('path', help='章节 .md 文件，或 --all 时的项目目录')
    parser.add_argument('--all', action='store_true', help='全书统计（含各章对话比例一致性）')
    args = parser.parse_args()

    if args.all:
        project = Path(args.path)
        files = sorted(project.glob('第*.md'), key=lambda p: p.name)
        if not files:
            print('[错误] 未找到章节文件'); sys.exit(1)
        results = []
        for f in files:
            r = analyze_chapter(f)
            if r:
                results.append(r)
                print_chapter(r)
        # 全书对话比例一致性
        if len(results) >= 3:
            ratios = [r['dialog_ratio'] for r in results]
            cv = statistics.stdev(ratios) / statistics.mean(ratios) if statistics.mean(ratios) > 0 else 0
            print(f'\n===== 全书对话比例一致性 =====')
            print(f'各章对话占比：{"、".join(f"{x*100:.0f}%" for x in ratios)}')
            print(f'变异系数 CV={cv:.2f} → {flag_level(None, cv, [0.15, 0.25, 0.4])}'
                  f' [CV 低=各章对话比例过匀(AI)，高=波动自然(人)]')
    else:
        f = Path(args.path)
        if not f.exists():
            print(f'[错误] 文件不存在：{args.path}'); sys.exit(1)
        r = analyze_chapter(f)
        if r:
            print_chapter(r)
        else:
            print('[提示] 无可统计的正文内容')


if __name__ == '__main__':
    main()
