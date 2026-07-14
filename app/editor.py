from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image


@dataclass
class CutoutEditor:
    """Non-destructive alpha-mask editor used by the Tkinter canvas."""

    source: Image.Image
    cutout: Image.Image
    max_history: int = 20
    alpha: Image.Image = field(init=False)
    guidance: np.ndarray = field(init=False)
    _history: list[tuple[Image.Image, np.ndarray]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.source = self.source.convert("RGBA")
        self.cutout = self.cutout.convert("RGBA")
        if self.source.size != self.cutout.size:
            raise ValueError("原始圖片與去背結果尺寸不同。")
        self.alpha = self.cutout.getchannel("A").copy()
        self.guidance = np.zeros((self.source.height, self.source.width), dtype=np.int8)

    @property
    def size(self) -> tuple[int, int]:
        return self.source.size

    def begin_stroke(self) -> None:
        self._history.append((self.alpha.copy(), self.guidance.copy()))
        if len(self._history) > self.max_history:
            del self._history[0]

    def paint(
        self,
        x: float,
        y: float,
        radius: float,
        mode: str,
        hardness: float = 0.75,
    ) -> None:
        if mode not in {"erase", "restore"}:
            raise ValueError(f"Unknown brush mode: {mode}")
        hardness = float(np.clip(hardness, 0.05, 1.0))
        width, height = self.alpha.size
        left = max(0, int(np.floor(x - radius)))
        top = max(0, int(np.floor(y - radius)))
        right = min(width, int(np.ceil(x + radius)) + 1)
        bottom = min(height, int(np.ceil(y + radius)) + 1)
        if left >= right or top >= bottom:
            return

        yy, xx = np.ogrid[top:bottom, left:right]
        distance = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
        inner_radius = radius * hardness
        feather_width = max(radius - inner_radius, 0.001)
        strength = np.clip((radius - distance) / feather_width, 0.0, 1.0)

        region = np.asarray(
            self.alpha.crop((left, top, right, bottom)), dtype=np.float32
        ).copy()
        if mode == "erase":
            region *= 1.0 - strength
        else:
            region += (255.0 - region) * strength
        patch = Image.fromarray(np.clip(region, 0, 255).astype(np.uint8), mode="L")
        self.alpha.paste(patch, (left, top))

        guidance_region = self.guidance[top:bottom, left:right]
        guidance_region[distance <= radius] = -1 if mode == "erase" else 1

    def undo(self) -> bool:
        if not self._history:
            return False
        self.alpha, self.guidance = self._history.pop()
        return True

    def reset(self) -> None:
        self.begin_stroke()
        self.alpha = self.cutout.getchannel("A").copy()
        self.guidance.fill(0)

    def has_guidance(self) -> bool:
        return bool(np.any(self.guidance))

    def smart_refine(self, iterations: int = 5) -> None:
        """Re-segment the image using the edited mask and user strokes as constraints."""
        if not self.has_guidance():
            raise ValueError("請先用擦除或還原筆刷標記需要修正的區域。")
        try:
            import cv2
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "缺少智慧精修元件。請重新安裝 requirements.txt。"
            ) from exc

        source_rgb = np.asarray(self.source.convert("RGB"), dtype=np.uint8)
        source_bgr = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2BGR)
        current_alpha = np.asarray(self.alpha, dtype=np.uint8)

        mask = np.full(current_alpha.shape, cv2.GC_PR_BGD, dtype=np.uint8)
        mask[current_alpha >= 128] = cv2.GC_PR_FGD
        mask[self.guidance < 0] = cv2.GC_BGD
        mask[self.guidance > 0] = cv2.GC_FGD

        has_foreground = np.any((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD))
        has_background = np.any((mask == cv2.GC_BGD) | (mask == cv2.GC_PR_BGD))
        if not has_foreground or not has_background:
            raise ValueError("目前標記不足，請同時保留主體與背景區域。")

        self.begin_stroke()
        background_model = np.zeros((1, 65), dtype=np.float64)
        foreground_model = np.zeros((1, 65), dtype=np.float64)
        try:
            cv2.grabCut(
                source_bgr,
                mask,
                None,
                background_model,
                foreground_model,
                iterations,
                cv2.GC_INIT_WITH_MASK,
            )
        except cv2.error as exc:
            self._history.pop()
            raise RuntimeError("智慧精修無法判斷此圖片，請增加主體與背景標記。") from exc

        foreground = np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
        ).astype(np.uint8)
        refined = cv2.GaussianBlur(foreground, (0, 0), sigmaX=0.8)
        refined[self.guidance < 0] = 0
        refined[self.guidance > 0] = 255
        self.alpha = Image.fromarray(refined, mode="L")

    def render(self) -> Image.Image:
        result = self.source.copy()
        source_alpha = np.asarray(self.source.getchannel("A"), dtype=np.uint8)
        edited_alpha = np.asarray(self.alpha, dtype=np.uint8)
        result.putalpha(Image.fromarray(np.minimum(source_alpha, edited_alpha)))
        return result
