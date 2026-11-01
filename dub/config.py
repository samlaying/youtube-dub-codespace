"""Environment-driven settings; nothing secret is stored in the repository."""

import os


class ConfigError(SystemExit):
    pass


def get(name, default=None, required=False):
    value = os.environ.get(name) or default
    if required and not value:
        raise ConfigError(f"{name} is required but not set")
    return value


def siliconflow():
    return {
        "api_key": get("SILICONFLOW_API_KEY", required=True),
        "base_url": get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/"),
        "model": get("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V4.1-Flash"),
        "timeout": int(get("SILICONFLOW_TIMEOUT", "120")),
    }


def download():
    return {
        "cookies": get("YTDLP_COOKIES", ""),
        "format": get("YTDLP_FORMAT", "bv*[height<=1080]+ba/b[height<=1080]/b"),
        # Extra flags, e.g. "--js-runtimes node --extractor-args youtube:player_client=web_embedded"
        "extra_args": get("YTDLP_ARGS", ""),
    }


def demucs():
    return {"model": get("DEMUCS_MODEL", "htdemucs"), "jobs": get("DEMUCS_JOBS", "0")}


def whisperx():
    # CPU is the default here: the free Codespaces machines have no GPU.
    return {
        "model": get("WHISPERX_MODEL", "small"),
        "device": get("WHISPERX_DEVICE", "cpu"),
        "compute_type": get("WHISPERX_COMPUTE_TYPE", "int8"),
    }
