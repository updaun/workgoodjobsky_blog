"""릴스 스크립트,이미지 경로 공통 유틸 (HeyGen / 로컬 렌더 공용)."""

from __future__ import annotations

import re
from pathlib import Path


def images_sorted_from_dir(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise ValueError(f"폴더가 아닙니다: {directory}")
    out: list[Path] = []
    for p in directory.iterdir():
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            out.append(p)
    return sorted(out, key=lambda x: x.name.lower())


def script_segments_explicit(script: str) -> list[str]:
    """--- 구분선으로 나눈 구간. 구분선 없으면 전체 1구간."""
    text = script.strip()
    if not text:
        return []
    parts = re.split(r"(?:\r?\n)\s*---\s*(?:\r?\n)", text)
    segs = [p.strip() for p in parts if p.strip()]
    return segs if segs else [text]


def split_script_scenes(script: str, num_scenes: int) -> list[str]:
    """
    num_scenes == 1 이면 전체를 한 씬.
    그 외에는 빈 줄 위아래의 --- 구분선으로만 나눔(구간 수 == num_scenes).
    """
    text = script.strip()
    if num_scenes < 1:
        raise ValueError("num_scenes >= 1")
    if num_scenes == 1:
        return [text]
    parts = re.split(r"(?:\r?\n)\s*---\s*(?:\r?\n)", text)
    segs = [p.strip() for p in parts if p.strip()]
    if len(segs) != num_scenes:
        raise ValueError(
            f"배경 이미지가 {num_scenes}장일 때, 스크립트를 줄바꿈으로 둘러싼 '---' 로 "
            f"정확히 {num_scenes}개 구간으로 나눠 주세요. (현재 유효 구간: {len(segs)}개)"
        )
    return segs
