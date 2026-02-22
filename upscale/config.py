from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    app_secret: str
    max_upload_mb: int
    max_files: int
    min_scale: float
    min_target_mb: float
    max_target_mb: float
    max_image_pixels: int
    max_output_pixels: int
    max_size_passes: int
    upscale_adapter: str
    topaz_cli_path: str
    ai_model_path: str
    notify_on_done: bool
    notify_channel: str
    notify_target: str
    telegram_bot_token: str
    telegram_chat_id: str
    work_dir: str
    log_level: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            app_secret=_env_str("APP_SECRET", "dev-secret-change-me"),
            max_upload_mb=_env_int("MAX_UPLOAD_MB", 3000),
            max_files=_env_int("MAX_FILES", 200),
            min_scale=_env_float("MIN_SCALE", 4.0),
            min_target_mb=_env_float("MIN_TARGET_MB", 20.0),
            max_target_mb=_env_float("MAX_TARGET_MB", 100.0),
            max_image_pixels=_env_int("MAX_IMAGE_PIXELS", 12000 * 12000),
            max_output_pixels=_env_int("MAX_OUTPUT_PIXELS", 20000 * 20000),
            max_size_passes=_env_int("MAX_SIZE_PASSES", 6),
            upscale_adapter=_env_str("UPSCALE_ADAPTER", "pillow"),
            topaz_cli_path=_env_str("TOPAZ_CLI_PATH", ""),
            ai_model_path=_env_str("AI_MODEL_PATH", ""),
            notify_on_done=_env_bool("NOTIFY_ON_DONE", True),
            notify_channel=_env_str("NOTIFY_CHANNEL", "telegram"),
            notify_target=_env_str("NOTIFY_TARGET", "7532770885"),
            telegram_bot_token=_env_str("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=_env_str("TELEGRAM_CHAT_ID", ""),
            work_dir=_env_str("WORK_DIR", ""),
            log_level=_env_str("LOG_LEVEL", "INFO"),
        )
