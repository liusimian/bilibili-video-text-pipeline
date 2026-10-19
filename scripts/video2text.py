# -*- coding: utf-8 -*-
r"""一条命令：B 站视频 -> 口播全文 + 画布文字 + 摘要输入稿。

用法（用 OCR 环境的 python 运行）：
  python video2text.py BV1NtJi6bEe3
  python video2text.py https://www.bilibili.com/video/BV1NtJi6bEe3/ --out E:\Desktop\DS\视频\BV1NtJi6bEe3
  python video2text.py BV1NtJi6bEe3 --limit 180      # 只跑前 3 分钟，用于验证

产物（默认在脚本目录\<BV号>\）：
  video.mp4            原片（可 --delete-video 删除）
  口播全文.txt          硬字幕逐段
  画布文字.md           画布 OCR 去重文本
  摘要输入.md           ★ 只读这一个文件即可写总结（约 2-3 万字）
  统计.json
  cookies.txt          匿名 cookie（无登录信息，可删）

成本要点：OCR 全部在本机完成，不产生 token；写总结时只读「摘要输入.md」一份。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
FFMPEG = Path(r'E:\Desktop\GPT\视频\.venv-ocr\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe')
YTDLP = Path(r'E:\Desktop\GPT\视频\yt-dlp\yt_dlp\__main__.py')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0')


def stamp(sec):
    sec = int(sec)
    return f'{sec // 3600:02}:{sec // 60 % 60:02}:{sec % 60:02}'


def norm(s):
    return re.sub(r'\W+', '', s)


def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def http_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://www.bilibili.com/'})
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())


def resolve(url_or_bv):
    m = re.search(r'BV[0-9A-Za-z]{10}', url_or_bv)
    if m:
        return m.group(0)
    if url_or_bv.startswith('http'):
        req = urllib.request.Request(url_or_bv, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            m = re.search(r'BV[0-9A-Za-z]{10}', r.geturl())
            if m:
                return m.group(0)
    raise SystemExit('无法从输入中解析出 BV 号')


def write_anon_cookies(path):
    d = http_json('https://api.bilibili.com/x/frontend/finger/spi')['data']
    rows = [
        '# Netscape HTTP Cookie File',
        '\t'.join(['.bilibili.com', 'TRUE', '/', 'FALSE', '0', 'buvid3', d['b_3']]),
        '\t'.join(['.bilibili.com', 'TRUE', '/', 'FALSE', '0', 'buvid4', d['b_4']]),
        '\t'.join(['.bilibili.com', 'TRUE', '/', 'FALSE', '0', 'b_nut', str(int(time.time()))]),
        '\t'.join(['.bilibili.com', 'TRUE', '/', 'FALSE', '0', '_uuid', str(uuid.uuid4()).upper() + 'infoc']),
    ]
    path.write_text('\n'.join(rows) + '\n', encoding='utf-8')


def video_meta(bv):
    d = http_json(f'https://api.bilibili.com/x/web-interface/view?bvid={bv}')
    if d.get('code') != 0:
        return {}
    v = d['data']
    return {
        'bvid': bv,
        'title': v.get('title', ''),
        'owner': v.get('owner', {}).get('name', ''),
        'duration': v.get('duration', 0),
        'pubdate': time.strftime('%Y-%m-%d', time.localtime(v.get('pubdate', 0))),
        'stat': {k: v.get('stat', {}).get(k) for k in ('view', 'like', 'coin', 'favorite', 'share')},
        'desc': v.get('desc', ''),
    }


def download(bv, out, cookies, limit=0):
    target = out / 'video.mp4'
    if target.exists() and target.stat().st_size > 1024 * 1024:
        print('[download] exists, skip')
        return target
    cmd = [PY, str(YTDLP), '--cookies', str(cookies), '--ffmpeg-location', str(FFMPEG),
           '-f', '30080+30280', '--merge-output-format', 'mp4',
           '-o', str(out / 'video.%(ext)s'), '--no-warnings', '-N', '8']
    if limit:
        cmd += ['--download-sections', f'*0-{limit}']
    cmd.append(f'https://www.bilibili.com/video/{bv}/')
    print('[download]', bv, 'limit=', limit)
    subprocess.run(cmd, check=True)
    return target


def run_half(video, out, start, end, threads):
    cmd = [PY, str(HERE / 'extract3.py'), str(video), str(out),
           '--start', str(start), '--threads', str(threads),
           '--canvas-interval', '20', '--force', '30', '--diff', '2.5', '--min-gap', '15']
    if end:
        cmd += ['--end', str(end)]
    subprocess.run(cmd, check=True)


def merge(out):
    caps = []
    for h in ('half1', 'half2'):
        f = out / h / 'captions.json'
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

    snaps = []
    for h in ('half1', 'half2'):
        f = out / h / 'canvas.json'
        if f.exists():
            snaps += json.loads(f.read_text(encoding='utf-8'))
    snaps.sort(key=lambda x: x['time'])
    dedup = []
    for s in snaps:
        if dedup and sim(s['text'], dedup[-1]['text']) >= .97:
            continue
        dedup.append(s)

    (out / '口播全文.txt').write_text(
        '\n'.join(f"[{stamp(x['start'])}] {x['text']}" for x in merged), encoding='utf-8')

    lines, seen = [], []
    for s in dedup:
        for line in s['text'].split('\n'):
            line = line.strip(' 　|')
            if len(line) < 2:
                continue
            if any(sim(line, x) >= .84 for x in seen[-800:]):
                continue
            seen.append(line)
            lines.append((s['time'], line))
    (out / '画布文字.md').write_text(
        '# 画面画布文字（OCR，按首次出现时间，近似去重）\n\n'
        + '\n'.join(f'[{stamp(t)}] {x}' for t, x in lines), encoding='utf-8')

    return merged, lines


def build_digest(out, meta, merged, lines, block=300):
    """把口播与画布按 5 分钟分块，合成一份可直接写总结的输入稿。"""
    end = max([c['end'] for c in merged] + [0] + [t for t, _ in lines])
    buf = []
    buf.append(f"# {meta.get('title', '')}")
    buf.append(f"- BV：{meta.get('bvid', '')}｜UP主：{meta.get('owner', '')}｜时长：{stamp(meta.get('duration', end))}｜发布：{meta.get('pubdate', '')}")
    if meta.get('stat'):
        s = meta['stat']
        buf.append(f"- 播放 {s.get('view')}｜点赞 {s.get('like')}｜投币 {s.get('coin')}｜收藏 {s.get('favorite')}｜分享 {s.get('share')}")
    buf.append('- 说明：口播为画面硬字幕 OCR（可能有少量错字）；"画布新增"为该时段首次出现的画面文字，已去重。')
    nblocks = int((end + block - 1) // block) or 1
    for i in range(nblocks):
        a, b = i * block, min((i + 1) * block, end + 1)
        seg = [c for c in merged if a <= c['start'] < b]
        newlines = [(t, x) for t, x in lines if a <= t < b]
        buf.append(f"\n## {stamp(a)} — {stamp(b)}")
        if seg:
            buf.append('口播：')
            buf.extend(x['text'] for x in seg)
        if newlines:
            buf.append('画布新增：')
            buf.extend(f'- {x}' for _, x in newlines)
    (out / '摘要输入.md').write_text('\n'.join(buf), encoding='utf-8')
    return len('\n'.join(buf))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('target')
    ap.add_argument('--out', default='')
    ap.add_argument('--limit', type=float, default=0)
    ap.add_argument('--threads', type=int, default=6)
    ap.add_argument('--delete-video', action='store_true')
    ap.add_argument('--digest-only', action='store_true')
    args = ap.parse_args()

    bv = resolve(args.target)
    out = Path(args.out) if args.out else HERE / bv
    out.mkdir(parents=True, exist_ok=True)
    print('[out]', out)

    meta = video_meta(bv)
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print('[meta]', meta.get('title'), meta.get('duration'), 's')

    if not args.digest_only:
        cookies = out / 'cookies.txt'
        if not cookies.exists():
            write_anon_cookies(cookies)
        video = download(bv, out, cookies, args.limit)
        dur = float(args.limit or meta.get('duration') or 0)
        half = dur / 2
        procs = []
        for idx, (s, e) in enumerate(((0, half), (half, dur))):
            procs.append(subprocess.Popen(
                [PY, str(HERE / 'extract3.py'), str(video), str(out / f'half{idx + 1}'),
                 '--start', str(s), '--threads', str(args.threads),
                 '--canvas-interval', '20', '--force', '30', '--diff', '2.5', '--min-gap', '15']
                + (['--end', str(e)] if e else [])))
        for p in procs:
            p.wait()
            if p.returncode != 0:
                raise SystemExit(f'OCR failed: {p.returncode}')

    merged, lines = merge(out)
    size = build_digest(out, meta, merged, lines)
    stat = {
        'bvid': bv, 'title': meta.get('title', ''), 'duration': meta.get('duration'),
        'subtitle_segments': len(merged),
        'subtitle_chars': sum(len(x['text']) for x in merged),
        'canvas_lines': len(lines),
        'canvas_chars': sum(len(x) for _, x in lines),
        'digest_chars': size,
    }
    (out / '统计.json').write_text(json.dumps(stat, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.delete_video and not args.limit:
        for f in out.glob('video*'):
            f.unlink(missing_ok=True)
    print(json.dumps(stat, ensure_ascii=False, indent=2))
    print('[done] 只读这一个文件写总结：', out / '摘要输入.md')


if __name__ == '__main__':
    main()
