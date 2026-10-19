# -*- coding: utf-8 -*-
"""单次顺序解码，同时抽取硬字幕与画布文字。

顺序读取（grab 跳帧）避免逐秒 seek 的开销。
  - 字幕：每 15 帧（2fps）检测白字黑边大字行，rec-only 识别。
  - 画布：每 30 帧（1fps）比较变化，变化超阈值才整帧 det+rec。
"""
import argparse
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR


def stamp(sec):
    sec = int(sec)
    return f'{sec // 3600:02}:{sec // 60 % 60:02}:{sec % 60:02}'


def norm(s):
    return re.sub(r'\W+', '', s)


def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def find_subtitle(frame):
    h = frame.shape[0]
    band = frame[int(h * .70):, :]
    mask = (np.max(band, axis=2) < 55).astype(np.uint8)
    d = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 2)))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(d, 8)
    cands = [(s[0], s[1], s[2], s[3]) for s in stats[1:]
             if s[3] >= 38 and s[2] >= 120 and s[3] <= 110]
    if not cands:
        return None
    x, y, ww, hh = max(cands, key=lambda v: v[2])
    return band[max(0, y - 6):y + hh + 6, max(0, x - 6):x + ww + 6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('video')
    ap.add_argument('output')
    ap.add_argument('--start', type=float, default=0)
    ap.add_argument('--end', type=float, default=0)
    ap.add_argument('--subs-fps', type=float, default=2)
    ap.add_argument('--canvas-interval', type=float, default=20)
    ap.add_argument('--force', type=float, default=25)
    ap.add_argument('--diff', type=float, default=2.0)
    ap.add_argument('--min-gap', type=float, default=15)
    ap.add_argument('--threads', type=int, default=6)
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'shots').mkdir(exist_ok=True)
    engine = RapidOCR(intra_op_num_threads=args.threads, inter_op_num_threads=1)

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total / fps
    start_f = int(args.start * fps)
    end_f = int(min(duration, args.end) * fps) if args.end else int(total)
    sub_every = max(1, int(round(fps / args.subs_fps)))
    can_every = max(1, int(round(fps * 1)))
    can_skip = max(1, int(round(args.canvas_interval)))

    if start_f:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)

    segs = []
    cur = None
    last_seen = None
    misses = 0
    snaps = []
    prev_gray = None
    last_canvas = -999
    raw_s = (out / 'subs_raw.jsonl').open('w', encoding='utf-8')
    raw_c = (out / 'canvas_raw.jsonl').open('w', encoding='utf-8')
    started = time.time()
    i = start_f
    k = 0
    while i < end_f:
        need = (i % sub_every == 0) or (i % can_every == 0)
        if need:
            ok, frame = cap.read()
            i += 1
        else:
            ok = cap.grab()
            i += 1
            if not ok:
                break
            k += 1
            continue
        if not ok:
            break
        t = i / fps

        # ---- 字幕 ----
        if (i - 1) % sub_every == 0:
            crop = find_subtitle(frame)
            text = ''
            if crop is not None and crop.size:
                res, _ = engine(crop, use_det=False, use_cls=False)
                text = ''.join(x for x, _ in (res or [])).strip()
            raw_s.write(json.dumps({'t': round(t, 2), 'text': text}, ensure_ascii=False) + '\n')
            if text:
                misses = 0
                if cur and sim(text, cur['text']) >= .90:
                    cur['end'] = round(t + 1 / args.subs_fps, 2)
                    if len(text) > len(cur['text']):
                        cur['text'] = text
                else:
                    if cur:
                        cur['end'] = round(t, 2)
                        segs.append(cur)
                    cur = {'start': round(t, 2), 'end': round(t + 1 / args.subs_fps, 2), 'text': text}
                last_seen = t
            else:
                misses += 1
                if cur and misses >= int(args.subs_fps * 1.2):
                    cur['end'] = round((last_seen or t) + 1 / args.subs_fps, 2)
                    segs.append(cur)
                    cur = None

        # ---- 画布 ----
        if (i - 1) % can_every == 0:
            h, w = frame.shape[:2]
            g = cv2.cvtColor(cv2.resize(frame[:int(h * .78)], (320, 180)), cv2.COLOR_BGR2GRAY)
            cdiff = 999.0 if prev_gray is None else float(np.mean(cv2.absdiff(g, prev_gray)))
            if (t - last_canvas) >= args.min_gap and (cdiff > args.diff or (t - last_canvas) >= args.force):
                res, _ = engine(frame)
                last_canvas = t
                prev_gray = g
                items = []
                for box, text_, score in (res or []):
                    ys = [p[1] for p in box]
                    xs = [p[0] for p in box]
                    if max(ys) - min(ys) >= 45:
                        continue
                    if np.mean(xs) > w * .86 and np.mean(ys) > h * .86:
                        continue
                    if score < .6:
                        continue
                    items.append({'text': str(text_), 'x': float(np.mean(xs)), 'y': float(np.mean(ys))})
                items.sort(key=lambda v: (round(v['y'] / 40), v['x']))
                text = '\n'.join(v['text'] for v in items)
                shot = ''
                if cdiff > 6 or not snaps:
                    shot = f'frame_{int(t):05d}.jpg'
                    ok2, buf = cv2.imencode('.jpg', frame)
                    if ok2:
                        buf.tofile(str(out / 'shots' / shot))
                if text:
                    snaps.append({'time': round(t, 2), 'text': text, 'change': round(cdiff, 2),
                                  'image': shot})
                raw_c.write(json.dumps({'t': round(t, 2), 'change': round(cdiff, 2),
                                        'text': text}, ensure_ascii=False) + '\n')

        k += 1
        if k % 300 == 0:
            raw_s.flush()
            raw_c.flush()
            print(json.dumps({'t': round(t, 1), 'segs': len(segs), 'snaps': len(snaps),
                              'elapsed': round(time.time() - started, 1)}), flush=True)

    if cur:
        segs.append(cur)
    cap.release()
    raw_s.close()
    raw_c.close()
    (out / 'captions.json').write_text(json.dumps(segs, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'hard_subtitles.txt').write_text(
        '\n'.join(f"[{stamp(s['start'])}] {s['text']}" for s in segs), encoding='utf-8')
    (out / 'canvas.json').write_text(json.dumps(snaps, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'segments': len(segs), 'snapshots': len(snaps),
                      'chars': sum(len(s['text']) for s in segs),
                      'elapsed': round(time.time() - started, 1)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
