from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image


def adaptive_edge_alpha(
    source_rgb: np.ndarray,
    foreground: np.ndarray,
    prior_alpha: np.ndarray,
) -> np.ndarray:
    """Build an edge-aware alpha matte from a binary segmentation.

    Strong image edges receive a narrow, crisp transition. Low-contrast edges
    retain more of the model's previous soft alpha so hair, blur and translucent
    details are not forced into a uniformly hard contour.
    """
    import cv2

    binary = (foreground >= 128).astype(np.uint8)
    if not np.any(binary) or np.all(binary):
        return binary * 255

    rgb = np.asarray(source_rgb, dtype=np.uint8)
    prior = np.asarray(prior_alpha, dtype=np.float32) / 255.0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0

    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(grad_x, grad_y)
    scale = max(float(np.percentile(gradient, 95)), 0.04)
    edge_strength = np.clip(gradient / scale, 0.0, 1.0)

    inside = cv2.distanceTransform(binary, cv2.DIST_L2, 3)
    outside = cv2.distanceTransform(1 - binary, cv2.DIST_L2, 3)
    signed_distance = inside - outside

    # Crisp image edges use a sub-pixel transition; ambiguous edges may feather
    # across at most a few pixels, never across the whole mask.
    feather_width = 2.2 - (1.4 * edge_strength)
    distance_alpha = np.clip(
        0.5 + signed_distance / (2.0 * feather_width), 0.0, 1.0
    )

    # A grayscale guided filter transfers visible image structures to the mask.
    radius = 2
    epsilon = 0.01
    mean_i = cv2.boxFilter(gray, cv2.CV_32F, (radius * 2 + 1,) * 2)
    mean_p = cv2.boxFilter(distance_alpha, cv2.CV_32F, (radius * 2 + 1,) * 2)
    corr_i = cv2.boxFilter(gray * gray, cv2.CV_32F, (radius * 2 + 1,) * 2)
    corr_ip = cv2.boxFilter(
        gray * distance_alpha, cv2.CV_32F, (radius * 2 + 1,) * 2
    )
    variance_i = corr_i - mean_i * mean_i
    covariance_ip = corr_ip - mean_i * mean_p
    coefficient_a = covariance_ip / (variance_i + epsilon)
    coefficient_b = mean_p - coefficient_a * mean_i
    mean_a = cv2.boxFilter(coefficient_a, cv2.CV_32F, (radius * 2 + 1,) * 2)
    mean_b = cv2.boxFilter(coefficient_b, cv2.CV_32F, (radius * 2 + 1,) * 2)
    guided_alpha = np.clip(mean_a * gray + mean_b, 0.0, 1.0)

    boundary_band = np.abs(signed_distance) <= 2.5
    prior_is_soft = ((prior > 0.02) & (prior < 0.98)).astype(np.float32)
    prior_is_soft = cv2.GaussianBlur(prior_is_soft, (0, 0), sigmaX=1.2)
    soft_weight = np.clip((1.0 - edge_strength) * prior_is_soft * 0.65, 0.0, 0.65)
    edge_alpha = guided_alpha * (1.0 - soft_weight) + prior * soft_weight
    edge_alpha[edge_alpha < 0.08] = 0.0
    edge_alpha[edge_alpha > 0.92] = 1.0

    result = binary.astype(np.float32)
    result[boundary_band] = edge_alpha[boundary_band]
    result[signed_distance >= 2.5] = 1.0
    result[signed_distance <= -2.5] = 0.0
    return np.clip(np.rint(result * 255.0), 0, 255).astype(np.uint8)


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

    def clone(self) -> "CutoutEditor":
        """Return an independent snapshot suitable for background processing."""
        duplicate = CutoutEditor(self.source.copy(), self.cutout.copy(), self.max_history)
        duplicate.alpha = self.alpha.copy()
        duplicate.guidance = self.guidance.copy()
        duplicate._history = [
            (alpha.copy(), guidance.copy()) for alpha, guidance in self._history
        ]
        return duplicate

    def smart_refine(self, iterations: int = 5, max_working_dimension: int = 1400) -> None:
        """Re-segment the image using the manually edited mask as a new model prior."""
        if not self.has_guidance():
            raise ValueError("請先用擦除或還原筆刷標記需要修正的區域。")
        try:
            import cv2
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "缺少智慧精修元件。請重新安裝 requirements.txt。"
            ) from exc

        if iterations < 1:
            raise ValueError("智慧精修迭代次數必須大於零。")
        if max_working_dimension < 64:
            raise ValueError("智慧精修工作尺寸過小。")

        source_rgb = np.asarray(self.source.convert("RGB"), dtype=np.uint8)
        source_bgr = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2BGR)
        prior_alpha = np.asarray(self.alpha, dtype=np.uint8)
        current_alpha = prior_alpha

        original_height, original_width = current_alpha.shape
        scale = min(1.0, max_working_dimension / max(original_width, original_height))
        if scale < 1.0:
            working_size = (
                max(1, round(original_width * scale)),
                max(1, round(original_height * scale)),
            )
            source_bgr = cv2.resize(source_bgr, working_size, interpolation=cv2.INTER_AREA)
            current_alpha = cv2.resize(
                current_alpha, working_size, interpolation=cv2.INTER_AREA
            )

        mask = np.full(current_alpha.shape, cv2.GC_PR_BGD, dtype=np.uint8)
        mask[current_alpha >= 128] = cv2.GC_PR_FGD

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
        if scale < 1.0:
            foreground = cv2.resize(
                foreground,
                (original_width, original_height),
                interpolation=cv2.INTER_NEAREST,
            )
        refined = adaptive_edge_alpha(source_rgb, foreground, prior_alpha)
        self.alpha = Image.fromarray(refined, mode="L")
        self.guidance.fill(0)

    def render(self) -> Image.Image:
        result = self.source.copy()
        source_alpha = np.asarray(self.source.getchannel("A"), dtype=np.uint8)
        edited_alpha = np.asarray(self.alpha, dtype=np.uint8)
        result.putalpha(Image.fromarray(np.minimum(source_alpha, edited_alpha)))
        return result
