# youtube-dub-codespace

CPU half of the dubbing pipeline: turn a video URL into a translated subtitle
set plus an isolated background track, then package the result for the GPU half.

```
s1 download ──> s2 separate ──> s3 transcribe ──> s4 translate ──> bundle.zip
 yt-dlp+ffmpeg    Demucs          WhisperX         LLM            → youtube-dub-colab
```

Part of a three-repository setup:

| Repository | Role | Where it runs |
|---|---|---|
| `youtube-rss-api` | resolve channels/videos, RSS feeds | server with a domain |
| **`youtube-dub-codespace`** (this one) | download, separate, transcribe, translate | GitHub Codespaces |
| `youtube-dub-colab` | clone the voice, mix, lip-sync | Google Colab (T4) |

Codespaces has no GPU machine types, which is why every GPU-bound stage lives in
the Colab repository. WhisperX still works here with a small model in int8; it is
just slower than CUDA.

## Quick start

```bash
export SILICONFLOW_API_KEY=...          # never commit this
python3 -m dub init  --job jobs/demo --url "https://www.youtube.com/watch?v=..." --language en --target zh
python3 -m dub run   --job jobs/demo --stages s1,s2,s3,s4
python3 -m dub bundle --job jobs/demo
```

Upload `dist/demo.zip` to Colab and continue with `youtube-dub-colab`.

## Stages

| Stage | Tool | Output |
|---|---|---|
| `s1` download | `yt-dlp` + `ffmpeg` | `source.mp4`, `audio/original.wav` (16 kHz mono) |
| `s2` separate | Demucs `htdemucs --two-stems=vocals` | `separated/vocals.wav`, `separated/no_vocals.wav` |
| `s3` transcribe | WhisperX | `transcripts/source.srt` |
| `s4` translate | SiliconFlow chat completions | `translated/zh.srt`, `translated/zh.txt` |

Stages record their result in `manifest.json` and are skipped on re-run unless
`--force` is passed.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `SILICONFLOW_API_KEY` | — | required for `s4` |
| `SILICONFLOW_BASE_URL` | `https://api.siliconflow.cn/v1` | |
| `SILICONFLOW_MODEL` | `deepseek-ai/DeepSeek-V4.1-Flash` | |
| `TRANSLATE_BATCH` | `20` | cues per request |
| `YTDLP_COOKIES` | — | path to `cookies.txt` for sites that require login |
| `WHISPERX_MODEL` | `small` | `small` keeps CPU time sane; use `large-v2` only with a GPU |
| `WHISPERX_DEVICE` | `cpu` | |
| `WHISPERX_COMPUTE_TYPE` | `int8` | |
| `DEMUCS_MODEL` | `htdemucs` | |

## Translation keeps cue alignment

Subtitles are parsed into cues, translated in batches, and rebuilt with the
original timecodes. If the model returns a different number of cues the stage
fails instead of silently shifting every subtitle. Do not use
`grep -v '^[0-9]'` to strip SRT indices: it also removes dialogue that starts
with a digit and leaves the `-->` timing lines in the text.

## Site caveats

Douyin requires fresh browser cookies; without them `yt-dlp` fails with
`Fresh cookies (not necessarily logged in) are needed`. Export cookies from a
logged-in browser and point `YTDLP_COOKIES` at the file. YouTube and most other
hosts work without cookies.

## Security

- The API key is read from the environment only.
- `cookies.txt`, job folders and bundles are gitignored.
- Use this on material you own or are licensed to localize.
