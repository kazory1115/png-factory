from io import BytesIO
from collections import deque
import os
import sys

import numpy as np
from PIL import Image


# pymatting enables Numba's on-disk cache while rembg is imported. In a
# PyInstaller bundle Numba timestamps sys.executable as its cache source, which
# crashes when Windows has moved or quarantined the one-file executable after
# launch. PNG Factory does not use rembg's optional alpha-matting path, so JIT
# compilation is unnecessary in the frozen application.
if getattr(sys, "frozen", False):
    os.environ["NUMBA_DISABLE_JIT"] = "1"


try:
    from rembg import remove as rembg_remove
except (ImportError, OSError, SystemExit) as exc:
    rembg_remove = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


def remove_background(input_bytes: bytes) -> bytes:
    if rembg_remove is None:
        detail = f"{type(IMPORT_ERROR).__name__}: {IMPORT_ERROR}"
        if isinstance(IMPORT_ERROR, ModuleNotFoundError) and IMPORT_ERROR.name:
            detail = f"Missing module {IMPORT_ERROR.name!r}. {detail}"
        raise RuntimeError(
            "AI 去背元件載入失敗。請下載最新版本後再試。\n\n"
            f"技術資訊：{detail}"
        ) from IMPORT_ERROR

    output_bytes = rembg_remove(input_bytes)
    return refine_cutout(input_bytes, output_bytes)


def refine_cutout(input_bytes: bytes, output_bytes: bytes) -> bytes:
    with Image.open(BytesIO(input_bytes)) as source_image:
        source_rgba = source_image.convert("RGBA")

    with Image.open(BytesIO(output_bytes)) as cutout_image:
        cutout_rgba = cutout_image.convert("RGBA")

    if source_rgba.size != cutout_rgba.size:
        return output_bytes

    background_rgb = estimate_background_color(source_rgba)
    base_alpha = np.asarray(cutout_rgba, dtype=np.uint8)[..., 3].astype(np.float32) / 255.0

    if is_flat_background(source_rgba, background_rgb):
        background_alpha = build_background_alpha(source_rgba, background_rgb)
        combined_alpha = np.minimum(base_alpha, background_alpha)
    else:
        combined_alpha = base_alpha

    corrected_image = rebuild_foreground(source_rgba, combined_alpha, background_rgb)

    buffer = BytesIO()
    corrected_image.save(buffer, format="PNG")
    return buffer.getvalue()


def estimate_background_color(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    height, width, _ = rgb.shape
    sample_h = max(1, height // 12)
    sample_w = max(1, width // 12)

    corners = np.concatenate(
        [
            rgb[:sample_h, :sample_w].reshape(-1, 3),
            rgb[:sample_h, width - sample_w :].reshape(-1, 3),
            rgb[height - sample_h :, :sample_w].reshape(-1, 3),
            rgb[height - sample_h :, width - sample_w :].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(corners, axis=0)


def is_flat_background(image: Image.Image, background_rgb: np.ndarray) -> bool:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    height, width, _ = rgb.shape
    sample_h = max(1, height // 12)
    sample_w = max(1, width // 12)

    corners = np.concatenate(
        [
            rgb[:sample_h, :sample_w].reshape(-1, 3),
            rgb[:sample_h, width - sample_w :].reshape(-1, 3),
            rgb[height - sample_h :, :sample_w].reshape(-1, 3),
            rgb[height - sample_h :, width - sample_w :].reshape(-1, 3),
        ],
        axis=0,
    )
    distances = np.linalg.norm(corners - background_rgb, axis=1)
    return float(np.percentile(distances, 95)) < 22.0


def build_background_alpha(source_rgba: Image.Image, background_rgb: np.ndarray) -> np.ndarray:
    source_rgb = np.asarray(source_rgba.convert("RGB"), dtype=np.float32)
    distance = np.linalg.norm(source_rgb - background_rgb.reshape((1, 1, 3)), axis=2)

    hard_threshold = 18.0
    soft_threshold = 52.0

    background_seed = distance <= hard_threshold
    connected_background = flood_fill_background(background_seed)
    fringe_mask = dilate_mask(connected_background, iterations=4) & (distance <= soft_threshold)

    alpha = np.ones_like(distance, dtype=np.float32)
    alpha[connected_background] = 0.0
    alpha[fringe_mask] = np.clip(
        (distance[fringe_mask] - hard_threshold) / (soft_threshold - hard_threshold),
        0.0,
        1.0,
    )
    return alpha


def flood_fill_background(seed_mask: np.ndarray) -> np.ndarray:
    height, width = seed_mask.shape
    visited = np.zeros_like(seed_mask, dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    for x in range(width):
        if seed_mask[0, x] and not visited[0, x]:
            visited[0, x] = True
            queue.append((0, x))
        if seed_mask[height - 1, x] and not visited[height - 1, x]:
            visited[height - 1, x] = True
            queue.append((height - 1, x))

    for y in range(height):
        if seed_mask[y, 0] and not visited[y, 0]:
            visited[y, 0] = True
            queue.append((y, 0))
        if seed_mask[y, width - 1] and not visited[y, width - 1]:
            visited[y, width - 1] = True
            queue.append((y, width - 1))

    while queue:
        y, x = queue.popleft()
        if y > 0 and seed_mask[y - 1, x] and not visited[y - 1, x]:
            visited[y - 1, x] = True
            queue.append((y - 1, x))
        if y + 1 < height and seed_mask[y + 1, x] and not visited[y + 1, x]:
            visited[y + 1, x] = True
            queue.append((y + 1, x))
        if x > 0 and seed_mask[y, x - 1] and not visited[y, x - 1]:
            visited[y, x - 1] = True
            queue.append((y, x - 1))
        if x + 1 < width and seed_mask[y, x + 1] and not visited[y, x + 1]:
            visited[y, x + 1] = True
            queue.append((y, x + 1))

    return visited


def dilate_mask(mask: np.ndarray, iterations: int) -> np.ndarray:
    dilated = mask.copy()
    for _ in range(iterations):
        expanded = dilated.copy()
        expanded[1:, :] |= dilated[:-1, :]
        expanded[:-1, :] |= dilated[1:, :]
        expanded[:, 1:] |= dilated[:, :-1]
        expanded[:, :-1] |= dilated[:, 1:]
        expanded[1:, 1:] |= dilated[:-1, :-1]
        expanded[:-1, :-1] |= dilated[1:, 1:]
        expanded[1:, :-1] |= dilated[:-1, 1:]
        expanded[:-1, 1:] |= dilated[1:, :-1]
        dilated = expanded
    return dilated


def rebuild_foreground(
    source_rgba: Image.Image, alpha: np.ndarray, background_rgb: np.ndarray
) -> Image.Image:
    source_rgb = np.asarray(source_rgba.convert("RGB"), dtype=np.float32)
    alpha_channel = np.clip(alpha[..., None], 0.0, 1.0)
    safe_alpha = np.clip(alpha_channel, 0.05, 1.0)
    background = background_rgb.reshape((1, 1, 3))

    recovered_rgb = (source_rgb - ((1.0 - alpha_channel) * background)) / safe_alpha
    recovered_rgb = np.clip(recovered_rgb, 0, 255)

    solid_mask = alpha_channel >= 0.995
    output_rgb = np.where(solid_mask, source_rgb, recovered_rgb)

    result = np.dstack((output_rgb.astype(np.uint8), (alpha * 255.0).astype(np.uint8)))
    return Image.fromarray(result, mode="RGBA")
