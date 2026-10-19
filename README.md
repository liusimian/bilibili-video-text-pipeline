# 视频文字流水线：B 站视频 → 口播/画布全文 → 详细总结

[![topics](https://img.shields.io/badge/topics-bilibili%20%7C%20ocr%20%7C%20rapidocr%20%7C%20subtitles%20%7C%20video--to--text-blue)](#标签)
[![python](https://img.shields.io/badge/python-3.12-3776AB)](#环境)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

把一条 B 站视频（画面是纯文字画布 + 口播硬字幕）自动拆成：

1. **口播全文**（逐段带时间戳）
2. **画布文字**（画面里出现的所有文字，按首次出现时间去重）
3. **摘要输入稿**（口播与画布按 5 分钟对齐，**写总结时只需要读这一个文件**）
4. 由大模型据此写成的一篇**详细总结**（样例见 `samples/`）

全程 OCR 在本机完成，**不调用云端模型、不消耗 token**；只有最后"写总结"这一步需要模型。

---

## 标签

`bilibili` `ocr` `rapidocr` `hard-subtitle` `video-to-text` `whisper-alternative`
`screen-text` `canvas-ocr` `chinese` `power-shell` `cost-optimization` `llm-context`

GitHub Topics 已同步：`bilibili`、`ocr`、`rapidocr`、`video-to-text`、`subtitles`、`chinese`、`cost-optimization`。

---

## 目录

| 路径 | 说明 | 标记 |
|---|---|---|
| `scripts/video2text.py` | **主入口**：BV 号 → 下载 → OCR → 合并 → 摘要输入稿 | `entrypoint` `automation` |
| `scripts/extract3.py` | 单次顺序解码，同时抽硬字幕（rec-only）与画布（det+rec） | `core` `ocr` |
| `scripts/merge3.py` | 合并两半结果、去重、生成全文 | `merge` |
| `scripts/批量处理.ps1` | 批量跑多个 BV | `batch` |
| `docs/总结模板.md` | 固定总结骨架，保证多期一致 | `prompt` `template` |
| `docs/技巧与成本.md` | 踩坑记录、参数依据、成本模型 | `notes` `benchmark` |
| `samples/BV1NtJi6bEe3/` | 完整样例：45 分钟视频的全部产物 | `sample` |

样例内容：《2032年会开放社保一次性补缴 中国社保制度的过去\现在和未来》（BV1NtJi6bEe3，UP主 捭阖哗_穷鬼主义，45:04）。

---

## 快速开始（Windows）

### 1. 环境

```powershell
# Python 3.12 虚拟环境
python -m venv .venv
.\.venv\Scripts\pip install rapidocr_onnxruntime opencv-python numpy imageio-ffmpeg
```

还需要 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 源码（或用 `pip install yt-dlp` 后改写调用）。

### 2. 改路径

`scripts/video2text.py` 顶部三行是硬编码路径，改成你机器上的：

```python
FFMPEG = Path(r'...\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe')
YTDLP  = Path(r'...\yt-dlp\yt_dlp\__main__.py')
PY     = sys.executable
```

### 3. 跑

```powershell
python scripts\video2text.py BV1NtJi6bEe3
# 产物在 scripts 同级目录的 BV1NtJi6bEe3\ 下
```

批量：

```powershell
.\scripts\批量处理.ps1 -Bv BV1NtJi6bEe3,BV1hZax63Efj
```

### 4. 写总结

只读 `摘要输入.md`（约 2—3 万字），按 `docs/总结模板.md` 一次写成。**不要**再把 `口播全文.txt`、`画布文字.md` 读一遍。

---

## 原理（三句话）

- **字幕**：硬字幕是"白字 + 黑描边"的大字。用暗色掩码（`max(RGB) < 55`）+ 水平膨胀 + 连通域，选出 `高≥38px、宽≥120px` 的行，**只跑识别不跑检测**（rec-only），每帧 0.03—0.08 秒。
- **画布**：整帧 det+rec，按"画面变化 + 最小间隔"触发（默认 15 秒一次，最多 20 秒补一次），剔除字幕框与右下角水印。
- **解码**：顺序 `grab()` 跳帧，比逐秒 `seek` 快一个数量级；视频切成两半、两个进程并行。

---

## 成本对比（同一台机器、同一个视频）

| | 手工探索（首次） | 用本流水线 |
|---|---|---|
| 输入 token | ≈1800 万（反复试错 + 反复读长日志） | ≈2 万（只读摘要输入稿） |
| 输出 token | ≈10.7 万 | ≈1.4 万 |
| 折算成本 | ≈¥20 | ≈¥0.1—0.3 |
| 机时 | 45 分钟（含调试） | 20—25 分钟（纯 CPU，不花 token） |

> 贵的是试错，不是视频。把重活交给脚本、把总结读入压缩成一份稿，是省钱的唯一办法。

---

## 限制

- 只适用于**硬字幕**（烧在画面里）的视频；有平台 CC 字幕时应优先直接取字幕（`yt-dlp --list-subs`），更准更省。
- 画布检测依赖浅色背景 + 深色文字；深色主题、复杂表格、快速运镜的召回率会下降。
- 1080p 匿名即可下载；需要登录/大会员的清晰度不支持（本流水线不读取你的浏览器 Cookie）。
- OCR 有错字，数字与专有名词建议在总结阶段标注"待核"。
- 仓库**不含视频文件**（154 MB，超过 GitHub 单文件限制）；需要原片请用 BV 号自行下载。

---

## License

MIT。样例文本仅用于演示提取效果，版权归原作者。
