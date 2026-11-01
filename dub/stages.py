"""CPU stages: download, separation, transcription, translation, bundling.

These run in Codespaces. The GPU half (voice synthesis, mixing, lip-sync) lives
in the youtube-dub-colab repository and consumes the zip built here.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import config, srt


def run(cmd, cwd=None, env=None, capture=False):
    printable = " ".join(str(part) for part in cmd)
    print(f"  $ {printable}", flush=True)
    result = subprocess.run(
        [str(part) for part in cmd], cwd=cwd, env=env, text=True, capture_output=capture
    )
    if result.returncode != 0:
        if capture:
            sys.stderr.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
        raise SystemExit(f"command failed ({result.returncode}): {printable}")
    return result


def require_tool(name):
    if shutil.which(name) is None:
        raise SystemExit(f"{name} not found on PATH; see README")


# ---------------------------------------------------------------- s1 download


def s1_download(job):
    require_tool("ffmpeg")
    require_tool("yt-dlp")
    if not job.url:
        raise SystemExit("job has no source url; pass --url to init")

    settings = config.download()
    # Download under its own basename: subtitle sidecars use source.* and must not
    # be mistaken for the video by the glob below.
    cmd = ["yt-dlp", "-o", str(job.root / "video.%(ext)s"), "--no-playlist", "-f", settings["format"]]
    if settings["cookies"]:
        cmd += ["--cookies", settings["cookies"]]
    if settings.get("extra_args"):
        cmd += shlex.split(settings["extra_args"])
    cmd.append(job.url)
    run(cmd)

    video_exts = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv", ".ts"}
    candidates = sorted(
        path for path in job.root.glob("video.*")
        if path.suffix.lower() in video_exts and path.is_file()
    )
    if not candidates:
        raise SystemExit("yt-dlp produced no video file")
    os.replace(candidates[0], job.video)

    job.original_audio.parent.mkdir(parents=True, exist_ok=True)
    run(
        ["ffmpeg", "-y", "-i", job.video, "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", job.original_audio],
        capture=True,
    )
    return {"video": str(job.video), "audio": str(job.original_audio)}


# ---------------------------------------------------------------- s2 separate


def s2_separate(job):
    job.require("s1", "original audio")
    settings = config.demucs()
    out_dir = job.root / "separated"
    cmd = ["python3", "-m", "demucs", str(job.original_audio),
           "-n", settings["model"], "--two-stems=vocals", "-o", str(out_dir)]
    if settings["jobs"] != "0":
        cmd += ["-j", settings["jobs"]]
    run(cmd)

    stem_dir = out_dir / settings["model"] / job.original_audio.stem
    vocals, background = stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"
    if not vocals.exists():
        raise SystemExit(f"demucs output missing: {vocals}")
    shutil.copy2(vocals, job.vocals)
    shutil.copy2(background, job.background)
    return {"vocals": str(job.vocals), "background": str(job.background)}


# -------------------------------------------------------------- s3 transcribe


def s3_transcribe(job):
    job.require("s2", "vocal stem")
    settings = config.whisperx()
    require_tool("whisperx")

    out_dir = job.root / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    run(
        ["whisperx", str(job.vocals),
         "--model", settings["model"],
         "--language", job.language,
         "--device", settings["device"],
         "--compute_type", settings["compute_type"],
         "--output_format", "srt",
         "--output_dir", str(out_dir)]
    )

    produced = out_dir / f"{job.vocals.stem}.srt"
    if not produced.exists():
        matches = sorted(out_dir.glob("*.srt"))
        if not matches:
            raise SystemExit("whisperx produced no srt")
        produced = matches[0]
    os.replace(produced, job.source_srt)
    return {"srt": str(job.source_srt), "cues": len(srt.read(job.source_srt))}


# --------------------------------------------------------------- s4 translate


def _chat(messages, settings, temperature=0.2, max_tokens=4096):
    payload = {
        "model": settings["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{settings['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {settings['api_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"translation API error {exc.code}: {exc.read().decode('utf-8', 'ignore')[:400]}")
    return body["choices"][0]["message"]["content"]


def _strip_fence(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _translate_batch(cues, settings, source_name, target_name):
    numbered = "\n".join(f"{i + 1}. {cue['text']}" for i, cue in enumerate(cues))
    system = (
        "You translate subtitles. Keep exactly one output per input cue, in the same order. "
        "Never merge, split, drop or reorder cues. Preserve names, numbers and product names. "
        "Return only a JSON array of strings with no commentary."
    )
    user = (
        f"Translate these {len(cues)} subtitle cues from {source_name} to {target_name}.\n"
        f"Return a JSON array of exactly {len(cues)} strings.\n\n{numbered}"
    )
    raw = _strip_fence(_chat([{"role": "system", "content": system},
                              {"role": "user", "content": user}], settings))
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) == len(cues):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass

    retry = (
        f"Translate each cue from {source_name} to {target_name}. Output exactly {len(cues)} lines, "
        f"each starting with '<n>|' where n is the cue number. No other text.\n\n{numbered}"
    )
    raw = _strip_fence(_chat([{"role": "system", "content": system},
                              {"role": "user", "content": retry}], settings))
    out = {}
    for line in raw.splitlines():
        if "|" not in line:
            continue
        key, value = line.split("|", 1)
        key = key.strip().rstrip(".")
        if key.isdigit():
            out[int(key)] = value.strip()
    if len(out) != len(cues):
        raise SystemExit(f"translation returned {len(out)} of {len(cues)} cues; refusing to desync subtitles")
    return [out[i + 1] for i in range(len(cues))]


def s4_translate(job):
    job.require("s3", "transcript")
    settings = config.siliconflow()
    cues = srt.read(job.source_srt)
    if not cues:
        raise SystemExit(f"no cues parsed from {job.source_srt}")

    languages = {"en": "English", "zh": "Simplified Chinese", "ja": "Japanese"}
    source_name = languages.get(job.language, job.language)
    target_name = languages.get(job.target_language, job.target_language)
    batch_size = int(os.environ.get("TRANSLATE_BATCH", "20"))

    translated = []
    for start in range(0, len(cues), batch_size):
        batch = cues[start:start + batch_size]
        print(f"  translating cues {start + 1}-{start + len(batch)} of {len(cues)}", flush=True)
        translated.extend(_translate_batch(batch, settings, source_name, target_name))

    result = srt.with_translations(cues, translated)
    srt.write(job.translated_srt, result)
    job.translated_text.write_text(srt.plain_text(result), encoding="utf-8")
    return {"srt": str(job.translated_srt), "text": str(job.translated_text),
            "cues": len(result), "model": settings["model"]}


# ------------------------------------------------------------------- bundle


# vocals.wav is intentionally excluded: the GPU half needs the background stem to
# mix against and the translated text to speak, not the isolated voice.
BUNDLE_FILES = (
    "manifest.json",
    "source.mp4",
    "separated/no_vocals.wav",
    "transcripts/source.srt",
    "translated/zh.srt",
    "translated/zh.txt",
)


def bundle(job, destination=None):
    """Zip what the Colab repo needs, so the job can move between machines."""
    job.require("s4", "translation")
    target = Path(destination) if destination else job.root.parent.parent / "dist" / f"{job.root.name}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)

    missing = [name for name in BUNDLE_FILES if not (job.root / name).exists()]
    if missing:
        raise SystemExit(f"cannot bundle, missing: {', '.join(missing)}")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in BUNDLE_FILES:
            archive.write(job.root / name, arcname=f"{job.root.name}/{name}")
    size = target.stat().st_size / 1024 / 1024
    return {"bundle": str(target), "size_mb": round(size, 1)}


REGISTRY = {
    "s1": s1_download,
    "s2": s2_separate,
    "s3": s3_transcribe,
    "s4": s4_translate,
}
