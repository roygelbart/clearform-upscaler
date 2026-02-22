from __future__ import annotations

import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

FSRCNN_X4_URL = "https://raw.githubusercontent.com/Saafke/FSRCNN_Tensorflow/master/models/FSRCNN_x4.pb"


class UpscaleAdapter:
    name = "base"

    def upscale(self, image: Image.Image, scale: float) -> Image.Image:
        raise NotImplementedError


@dataclass
class PillowAdapter(UpscaleAdapter):
    name: str = "pillow"

    def upscale(self, image: Image.Image, scale: float) -> Image.Image:
        width = max(1, int(image.width * scale))
        height = max(1, int(image.height * scale))
        return image.resize((width, height), Image.Resampling.LANCZOS)


@dataclass
class AIFSRCNNAdapter(UpscaleAdapter):
    model_path: str
    name: str = "ai"

    def __post_init__(self) -> None:
        self.model_path = self._ensure_model(self.model_path)
        self.sr = cv2.dnn_superres.DnnSuperResImpl_create()
        self.sr.readModel(self.model_path)
        self.sr.setModel("fsrcnn", 4)

    @staticmethod
    def _ensure_model(path: str) -> str:
        path = path or str(Path(__file__).resolve().parent.parent / "models" / "FSRCNN_x4.pb")
        p = Path(path)
        if p.exists():
            return str(p)

        p.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading FSRCNN x4 model to %s", p)
        urllib.request.urlretrieve(FSRCNN_X4_URL, str(p))
        return str(p)

    def upscale(self, image: Image.Image, scale: float) -> Image.Image:
        # AI pass at fixed 4x, then optional final resize to requested scale.
        rgb = np.array(image.convert("RGB"))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        upscaled_bgr = self.sr.upsample(bgr)
        upscaled_rgb = cv2.cvtColor(upscaled_bgr, cv2.COLOR_BGR2RGB)
        out = Image.fromarray(upscaled_rgb)

        desired_w = max(1, int(image.width * scale))
        desired_h = max(1, int(image.height * scale))
        if out.width != desired_w or out.height != desired_h:
            out = out.resize((desired_w, desired_h), Image.Resampling.LANCZOS)
        return out


@dataclass
class TopazAdapter(UpscaleAdapter):
    cli_path: str
    name: str = "topaz"

    def is_available(self) -> bool:
        return bool(self.cli_path) and os.path.exists(self.cli_path)

    def upscale(self, image: Image.Image, scale: float) -> Image.Image:
        raise RuntimeError(
            "Topaz adapter is configured but CLI integration is not enabled. "
            "Set UPSCALE_ADAPTER=ai or UPSCALE_ADAPTER=pillow for unattended runs."
        )


def get_adapter(adapter_name: str, topaz_cli_path: str, ai_model_path: str) -> UpscaleAdapter:
    normalized = (adapter_name or "").strip().lower()
    if normalized == "topaz":
        topaz = TopazAdapter(cli_path=topaz_cli_path)
        if not topaz.is_available():
            logger.warning("Topaz CLI not available; falling back to AI adapter.")
            return AIFSRCNNAdapter(model_path=ai_model_path)
        return topaz
    if normalized in {"ai", "fsrcnn", "opencv"}:
        return AIFSRCNNAdapter(model_path=ai_model_path)
    return PillowAdapter()
