"""Automatic image and audio assets from the project folders."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AssetKind = Literal["image", "audio"]

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".avif"})
AUDIO_SUFFIXES = frozenset({".ogg", ".opus", ".mp3", ".wav", ".mp2"})
MAX_ASSETS = 20_000


@dataclass(frozen=True)
class Asset:
    """One file that Ren'Py treats as an image or audio resource."""

    kind: AssetKind
    name: str
    path: Path


class AssetIndex:
    """A cached map of asset names to files."""

    def __init__(self) -> None:
        self._images: dict[str, Asset] = {}
        self._audio: dict[str, Asset] = {}

    def scan(self, roots: list[Path]) -> None:
        """Replace the index with assets found under ``roots``."""
        images: dict[str, Asset] = {}
        audio: dict[str, Asset] = {}

        for root in _unique_dirs(roots):
            if len(images) + len(audio) >= MAX_ASSETS:
                break
            for directory in (root / "game" / "images", root / "images"):
                if directory.is_dir():
                    _scan_directory(directory, "image", IMAGE_SUFFIXES, images)
            for directory in (root / "game" / "audio", root / "audio"):
                if directory.is_dir():
                    _scan_directory(directory, "audio", AUDIO_SUFFIXES, audio)

        self._images = images
        self._audio = audio

    def images(self) -> list[Asset]:
        return list(self._images.values())

    def audio(self) -> list[Asset]:
        return list(self._audio.values())

    def find_image(self, name: str) -> Asset | None:
        return self._images.get(name)

    def find_audio(self, name: str) -> Asset | None:
        direct = self._audio.get(name)
        if direct is not None:
            return direct
        if not name.startswith("audio/"):
            return self._audio.get(f"audio/{name}")
        return None


def _unique_dirs(roots: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def _scan_directory(
    directory: Path,
    kind: AssetKind,
    suffixes: frozenset[str],
    target: dict[str, Asset],
) -> None:
    for path in sorted(directory.rglob("*")):
        if len(target) >= MAX_ASSETS:
            return
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        try:
            relative = path.relative_to(directory)
        except ValueError:
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        if kind == "image":
            name = _image_name(relative)
        else:
            name = f"audio/{relative.as_posix()}"
        target.setdefault(name, Asset(kind=kind, name=name, path=path))


def _image_name(relative: Path) -> str:
    parts = list(relative.with_suffix("").parts)
    return " ".join(part.replace("_", " ") for part in parts)
