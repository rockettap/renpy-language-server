"""Tests for automatic image and audio asset scanning."""

from pathlib import Path

from renpy_language_server.assets import AssetIndex


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_scans_nested_images_and_converts_names(tmp_path: Path) -> None:
    _touch(tmp_path / "game" / "images" / "bg_room.png")
    _touch(tmp_path / "game" / "images" / "eileen" / "happy.png")
    index = AssetIndex()
    index.scan([tmp_path])

    assert sorted(asset.name for asset in index.images()) == [
        "bg room",
        "eileen happy",
    ]
    assert index.find_image("eileen happy") is not None


def test_ignores_unsupported_extensions_and_hidden_files(tmp_path: Path) -> None:
    _touch(tmp_path / "game" / "images" / "notes.txt")
    _touch(tmp_path / "game" / "images" / ".hidden" / "bg.png")
    index = AssetIndex()
    index.scan([tmp_path])

    assert index.images() == []


def test_duplicate_names_keep_one_asset(tmp_path: Path) -> None:
    _touch(tmp_path / "game" / "images" / "bg.jpg")
    _touch(tmp_path / "game" / "images" / "bg.png")
    index = AssetIndex()
    index.scan([tmp_path])

    assert [asset.name for asset in index.images()] == ["bg"]


def test_images_are_found_in_a_root_images_folder(tmp_path: Path) -> None:
    _touch(tmp_path / "images" / "logo.png")
    index = AssetIndex()
    index.scan([tmp_path])

    assert index.find_image("logo") is not None


def test_audio_assets_are_namespaced(tmp_path: Path) -> None:
    _touch(tmp_path / "game" / "audio" / "music" / "theme.ogg")
    index = AssetIndex()
    index.scan([tmp_path])

    assert index.find_audio("audio/music/theme.ogg") is not None
    assert index.find_audio("music/theme.ogg") is not None
    assert index.find_audio("theme.ogg") is None


def test_missing_folders_produce_an_empty_index(tmp_path: Path) -> None:
    index = AssetIndex()
    index.scan([tmp_path])

    assert index.images() == []
    assert index.audio() == []


def test_rescanning_replaces_previous_results(tmp_path: Path) -> None:
    image = tmp_path / "game" / "images" / "bg.png"
    _touch(image)
    index = AssetIndex()
    index.scan([tmp_path])
    assert index.find_image("bg") is not None

    image.unlink()
    index.scan([tmp_path])
    assert index.find_image("bg") is None
