from pathlib import Path


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def ensure_supported_image(file_path: str | Path) -> Path:
    path = Path(file_path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Only JPG, JPEG, and PNG files are supported.")
    return path


def build_default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_no_bg.png")
