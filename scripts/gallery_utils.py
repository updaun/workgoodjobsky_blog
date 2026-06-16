#!/usr/bin/env python3
"""data/ 현장 사진 폴더 파싱,정리,갤러리 manifest 생성."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}

KAKAO_PATTERN = re.compile(
    r"KakaoTalk_\d{8}_\d+(?:_\d+)?(?:\.(?:jpg|jpeg|png|webp))?",
    re.IGNORECASE,
)
FOLDER_PATTERN = re.compile(r"^(\d{6})_(.+)$")


@dataclass
class GalleryImage:
    filename: str
    key: str
    url: str = ""


@dataclass
class GalleryAlbum:
    id: str
    date: str
    region: str
    title: str
    description: str
    images: list[GalleryImage] = field(default_factory=list)


@dataclass
class GalleryManifest:
    updated_at: str
    public_base_url: str
    albums: list[GalleryAlbum] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    return project_root() / "data"


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def iter_album_dirs(data_dir: Path) -> Iterable[Path]:
    if not data_dir.is_dir():
        return
    for path in sorted(data_dir.iterdir()):
        if path.is_dir() and not path.name.startswith("."):
            yield path


def iter_album_images(album_dir: Path) -> list[Path]:
    files = [p for p in album_dir.iterdir() if is_image(p)]
    return sorted(files, key=lambda p: (p.name.lower(), p.stat().st_mtime))


def parse_folder_name(folder_name: str) -> tuple[str, str, str]:
    """260520_광양중마동 → (id, ISO date, region)."""
    match = FOLDER_PATTERN.match(folder_name)
    if not match:
        return folder_name, "", folder_name

    yymmdd, region = match.group(1), match.group(2).strip()
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    iso_date = f"20{yy:02d}-{mm:02d}-{dd:02d}"
    return folder_name, iso_date, region


def clean_reference_text(text: str) -> str:
    cleaned = KAKAO_PATTERN.sub("", text)
    cleaned = cleaned.replace("\r\n", "\n")
    return cleaned.strip()


def parse_reference(reference_path: Path) -> tuple[str, str]:
    if not reference_path.is_file():
        return "", ""

    raw = reference_path.read_text(encoding="utf-8")
    cleaned = clean_reference_text(raw)
    if not cleaned:
        return "", ""

    lines = [re.sub(r"\s+", " ", line.strip(" /")) for line in cleaned.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return "", ""

    title = lines[0]
    description = " ".join(lines[1:]).strip()
    return title, description


def padded_filename(index: int, total: int, suffix: str) -> str:
    width = max(2, len(str(total)))
    return f"{index:0{width}d}{suffix.lower()}"


def organize_album(album_dir: Path, dry_run: bool = False) -> list[tuple[Path, Path]]:
    """카카오톡 등 임의 파일명을 01.jpg 형식으로 정리."""
    images = iter_album_images(album_dir)
    if not images:
        return []

    moves: list[tuple[Path, Path]] = []
    total = len(images)
    targets = [
        album_dir / padded_filename(i, total, img.suffix)
        for i, img in enumerate(images, start=1)
    ]

    # 이미 목표 이름과 같으면 스킵
    if all(src == dst for src, dst in zip(images, targets)):
        return []

    temp_paths = [album_dir / f".rename_tmp_{i}{img.suffix.lower()}" for i, img in enumerate(images, start=1)]

    for src, tmp in zip(images, temp_paths):
        if src == tmp:
            continue
        moves.append((src, tmp))

    for tmp, dst in zip(temp_paths, targets):
        moves.append((tmp, dst))

    if dry_run:
        preview: list[tuple[Path, Path]] = []
        for src, dst in zip(images, targets):
            if src != dst:
                preview.append((src, dst))
        return preview

    # 1단계: 임시 이름으로 이동
    for src, tmp in zip(images, temp_paths):
        if src != tmp and src.exists():
            src.rename(tmp)

    # 2단계: 최종 이름으로 이동
    for tmp, dst in zip(temp_paths, targets):
        if tmp.exists():
            if dst.exists() and dst != tmp:
                dst.unlink()
            tmp.rename(dst)

    return [(src, dst) for src, dst in zip(images, targets) if src != dst]


def build_album(
    album_dir: Path,
    key_prefix: str,
    public_base_url: str = "",
) -> GalleryAlbum:
    album_id, iso_date, region = parse_folder_name(album_dir.name)
    title, description = parse_reference(album_dir / "reference.md")
    if not title:
        title = region

    prefix = key_prefix.strip("/")
    base = public_base_url.rstrip("/")

    images: list[GalleryImage] = []
    for img in iter_album_images(album_dir):
        key = f"{prefix}/{album_id}/{img.name}" if prefix else f"{album_id}/{img.name}"
        url = f"{base}/{key}" if base else ""
        images.append(GalleryImage(filename=img.name, key=key, url=url))

    return GalleryAlbum(
        id=album_id,
        date=iso_date,
        region=region,
        title=title,
        description=description,
        images=images,
    )


def build_manifest(
    data_dir: Path,
    key_prefix: str = "gallery",
    public_base_url: str = "",
) -> GalleryManifest:
    albums = [
        build_album(album_dir, key_prefix=key_prefix, public_base_url=public_base_url)
        for album_dir in iter_album_dirs(data_dir)
        if iter_album_images(album_dir)
    ]
    albums.sort(key=lambda a: (a.date, a.id), reverse=True)

    return GalleryManifest(
        updated_at=datetime.now(timezone.utc).isoformat(),
        public_base_url=public_base_url.rstrip("/"),
        albums=albums,
    )


def write_manifest(manifest: GalleryManifest, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def organize_all(data_dir: Path, dry_run: bool = False) -> dict[str, list[tuple[str, str]]]:
    summary: dict[str, list[tuple[str, str]]] = {}
    for album_dir in iter_album_dirs(data_dir):
        moves = organize_album(album_dir, dry_run=dry_run)
        if moves:
            summary[album_dir.name] = [(src.name, dst.name) for src, dst in moves]
    return summary
