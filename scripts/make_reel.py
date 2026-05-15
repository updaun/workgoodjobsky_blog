#!/usr/bin/env python3
"""
비용 없이 이미지 + gTTS 나레이션 + 자막 + (선택) 배경음악으로 릴스 MP4를 만듭니다.

필요: Python 3.10+, ffmpeg (시스템), 한글 폰트(자막, 없으면 --font)

설치:
  pip install -r scripts/requirements-reel.txt
  sudo apt install ffmpeg   # Ubuntu / WSL

사용 예 (저장소 루트):

  # 단일 사진 + 나레이션
  python scripts/make_reel.py create \\
    --script-file instagram_reels/260513_heygen.txt \\
    --background-image data/260513_순천만/photo.jpg \\
    --music assets/music/ambient.mp3 \\
    --output output/reels/260513.mp4

  # 여러 장 (파일명 순). 스크립트는 --- 로 구간 나눔 (HeyGen 과 동일)
  python scripts/make_reel.py create \\
    --script-file ./multi_scene.txt \\
    --scene-dir data/260513_순천만 \\
    --music assets/music/ambient.mp3 \\
    --output output/reels/260513_multi.mp4

배경음악: 저작권 없는 트랙만 사용하세요 (Pixabay, YouTube Audio Library 등).
  `assets/music/` 에 mp3 를 두고 --music 으로 지정합니다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ 패키지 없이 실행되도록
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from reel_builder import BuildOptions, render_reel  # noqa: E402
from reel_common import images_sorted_from_dir  # noqa: E402


def _collect_scene_image_paths(ns: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    for s in ns.scene_images or []:
        paths.append(Path(s).expanduser().resolve())
    if paths:
        return paths
    if ns.scene_dir:
        return images_sorted_from_dir(Path(ns.scene_dir).expanduser().resolve())
    return []


def cmd_create(ns: argparse.Namespace) -> None:
    script = ns.script
    if ns.script_file:
        script = Path(ns.script_file).read_text(encoding="utf-8")
    if not script or not script.strip():
        raise SystemExit("--script 또는 --script-file 이 필요합니다.")

    scene_paths = _collect_scene_image_paths(ns)
    if scene_paths and ns.background_image:
        raise SystemExit(
            "--background-image 와 --scene-dir / --scene-image 는 함께 쓸 수 없습니다."
        )

    bg_one: Path | None = None
    if ns.background_image:
        bg_one = Path(ns.background_image).expanduser().resolve()

    music: Path | None = None
    if ns.music:
        music = Path(ns.music).expanduser().resolve()
        if not music.is_file():
            raise SystemExit(f"배경음악 파일 없음: {music}")

    font: Path | None = None
    if ns.font:
        font = Path(ns.font).expanduser().resolve()

    opts = BuildOptions(
        width=ns.width,
        height=ns.height,
        fps=ns.fps,
        fade_sec=ns.fade,
        pad_sec=ns.pad,
        ken_burns=ns.ken_burns,
        music_path=music,
        music_volume=ns.music_volume,
        subtitle=not ns.no_subtitle,
        font_path=font,
        subtitle_max_chars=ns.subtitle_chars,
        tts_lang=ns.tts_lang,
        tts_slow=ns.tts_slow,
    )

    out = Path(ns.output).expanduser().resolve()
    work = Path(ns.work_dir).expanduser().resolve() if ns.work_dir else None

    print("TTS·영상 합성 중… (씬 수에 따라 수 분 걸릴 수 있습니다)", flush=True)
    result = render_reel(
        script=script,
        image_paths=scene_paths,
        default_image=bg_one,
        output=out,
        work_dir=work,
        opts=opts,
    )
    print(f"완료: {result}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="이미지+gTTS+자막 릴스 로컬 렌더 (HeyGen 대체)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="MP4 릴스 생성")
    c.add_argument("--script", help="나레이션 전체 텍스트")
    c.add_argument("--script-file", help="나레이션 텍스트 파일")
    c.add_argument(
        "--background-image",
        help="배경 이미지 1장 (단일 씬). 여러 장은 --scene-dir",
    )
    c.add_argument(
        "--scene-dir",
        help="폴더 안 jpg/png 를 파일명 순으로 사용. 스크립트는 --- 로 구간 수 맞추기",
    )
    c.add_argument(
        "--scene-image",
        action="append",
        dest="scene_images",
        metavar="PATH",
        help="배경 이미지 경로 (여러 번, --scene-dir 보다 우선)",
    )
    c.add_argument(
        "--music",
        help="저작권 없는 배경음악 mp3 (나레이션보다 작게 믹스)",
    )
    c.add_argument("--music-volume", type=float, default=0.12, help="배경음 볼륨 0~1")
    c.add_argument("--output", required=True, help="출력 mp4 경로")
    c.add_argument(
        "--work-dir",
        help="중간 파일(TTS mp3 등) 저장 폴더. 기본: 출력 옆 .work_<이름>",
    )
    c.add_argument("--width", type=int, default=1080)
    c.add_argument("--height", type=int, default=1920)
    c.add_argument("--fps", type=int, default=30)
    c.add_argument("--fade", type=float, default=0.4, help="씬 전환 페이드(초)")
    c.add_argument("--pad", type=float, default=0.35, help="씬 끝 여유(초)")
    c.add_argument(
        "--ken-burns",
        type=float,
        default=0.04,
        help="줌 인 강도 (0 이면 끔)",
    )
    c.add_argument("--no-subtitle", action="store_true", help="화면 자막 끄기")
    c.add_argument("--subtitle-chars", type=int, default=16, help="자막 한 줄 최대 글자 수")
    c.add_argument("--font", help="자막 폰트 .ttf/.ttc 경로")
    c.add_argument("--tts-lang", default="ko", help="gTTS 언어 코드 (기본 ko)")
    c.add_argument("--tts-slow", action="store_true", help="gTTS 느린 발음")
    c.set_defaults(func=cmd_create)
    return p


def main() -> None:
    parser = build_parser()
    ns = parser.parse_args()
    ns.func(ns)


if __name__ == "__main__":
    main()
