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
| `YTDLP_ARGS` | — | extra yt-dlp flags, shell-quoted (see below) |
| `WHISPERX_MODEL` | `small` | `small` keeps CPU time sane; use `large-v2` only with a GPU |
| `WHISPERX_DEVICE` | `cpu` | |
| `WHISPERX_COMPUTE_TYPE` | `int8` | |
| `DEMUCS_MODEL` | `htdemucs` | |

## YouTube bot checks

YouTube increasingly answers `yt-dlp` with *Sign in to confirm you're not a bot*,
and with an unauthenticated client it may expose only storyboards and no media
streams. What worked when this was verified:

```bash
yt-dlp --js-runtimes node \
  --remote-components ejs:github \
  --cookies /path/to/yt-cookies.txt \
  --extractor-args "youtube:player_client=web" \
  --proxy http://127.0.0.1:7890 \
  -f 18 -o video.%(ext)s "https://www.youtube.com/watch?v=..."

python3 -m dub import-subs --job jobs/demo --srt source.en.srt
```

Notes from that run:

- `--js-runtimes node` matters: without a JavaScript runtime yt-dlp warns that
  extraction is deprecated and formats go missing.
- `--extractor-args "youtube:player_client=web_embedded"` pins the client that
  passed the challenge; the default client rotation hit the bot check far more often.
- `-f sb0` only satisfies format selection; subtitles download regardless.
- `--remote-components ejs:github` is what actually unlocks media formats: without it
  yt-dlp warns that the `n` challenge could not be solved and returns storyboards only.
  With it, and a logged-in cookie file, the progressive `18` (360p) format appears.
  Without a PO token YouTube does not offer higher resolutions to `yt-dlp`.
- Passing those flags to the pipeline:
  `export YTDLP_ARGS='--js-runtimes node --remote-components ejs:github --extractor-args youtube:player_client=web --proxy http://127.0.0.1:7890'`
  and `export YTDLP_FORMAT=18`.

## Using existing subtitles instead of ASR

`import-subs` adopts an SRT you already have (for example YouTube auto-captions)
as the `s3` output, so `s4` can run without WhisperX:

```bash
python3 -m dub import-subs --job jobs/demo --srt source.en.srt --limit 60
```

Auto-captions are rolling fragments where each cue repeats the previous one
("One of the" → "One of the" → "One of the most popular OCR"). `import-subs`
merges them into sentence-level cues and removes the overlap; `--no-merge` keeps
them verbatim.

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
