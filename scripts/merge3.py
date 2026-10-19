# -*- coding: utf-8 -*-
"""合并 half1 / half2 的字幕与画布结果，产出最终文本。"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(r'E:\Desktop\DS\视频')


def stamp(sec):
    sec = int(sec)
    return f'{sec // 3600:02}:{sec // 60 % 60:02}:{sec % 60:02}'


def norm(s):
    return re.sub(r'\W+', '', s)


def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def main():
    caps = []
    for h in ('half1', 'half2'):
        f = ROOT / h / 'captions.json'
        if f.exists():
            caps += json.loads(f.read_text(encoding='utf-8'))
    caps.sort(key=lambda x: x['start'])

    merged = []
    for c in caps:
        text = (c.get('text') or '').strip()
        if not text:
            continue
        if merged and c['start'] - merged[-1]['end'] <= 1.5 and sim(text, merged[-1]['text']) >= .88:
            merged[-1]['end'] = max(merged[-1]['end'], c['end'])
            if len(text) > len(merged[-1]['text']):
                merged[-1]['text'] = text
        else:
            merged.append({'start': c['start'], 'end': c['end'], 'text': text})
    merged.sort(key=lambda x: x['start'])

    (ROOT / '口播全文.txt').write_text(
        '\n'.join(f"[{stamp(x['start'])}] {x['text']}" for x in merged), encoding='utf-8')

    snaps = []
    for h in ('half1', 'half2'):
        f = ROOT / h / 'canvas.json'
        if f.exists():
            snaps += json.loads(f.read_text(encoding='utf-8'))
    snaps.sort(key=lambda x: x['time'])

    dedup = []
    for s in snaps:
        if dedup and sim(s['text'], dedup[-1]['text']) >= .97:
            continue
        dedup.append(s)
    (ROOT / '画布快照.json').write_text(json.dumps(dedup, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = []
    seen = []
    for s in dedup:
        for line in s['text'].split('\n'):
            line = line.strip(' 　|')
            if len(line) < 2:
                continue
            if any(sim(line, x) >= .84 for x in seen[-800:]):
                continue
            seen.append(line)
            lines.append(f"[{stamp(s['time'])}] {line}")
    (ROOT / '画布文字.md').write_text(
        '# 画面画布文字（OCR 原始结果，按首次出现时间排序，近似去重）\n\n' + '\n'.join(lines),
        encoding='utf-8')

    timeline = [(x['start'], '口播', x['text']) for x in merged]
    for s in dedup:
        timeline.append((s['time'], '画布', s['text']))
    timeline.sort(key=lambda x: x[0])
    (ROOT / '时间线.md').write_text(
        '# 时间线（口播字幕 + 画布快照）\n\n'
        + '\n\n'.join(f"### [{stamp(t)}] {k}\n{v}" for t, k, v in timeline), encoding='utf-8')

    stat = {
        'subtitle_segments': len(merged),
        'subtitle_chars': sum(len(x['text']) for x in merged),
        'canvas_snapshots_raw': len(snaps),
        'canvas_snapshots_dedup': len(dedup),
        'canvas_lines': len(lines),
        'canvas_chars': sum(len(x) for x in lines),
    }
    (ROOT / '统计.json').write_text(json.dumps(stat, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(stat, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
