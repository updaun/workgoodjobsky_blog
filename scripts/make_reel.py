#!/usr/bin/env python3
"""
비용 없이 이미지 + edge-tts 나레이션 + (선택) 자막,배경음악으로 릴스 MP4를 만듭니다.
기본은 자막 없음(슬라이드 + 보이스만).

필요: Python 3.10+, ffmpeg, 한글 폰트 권장(하단 고정 문구,자막에 사용).
숫자,해상도 기본값은 `scripts/reel_defaults.py` 에서 한 번에 바꿀 수 있습니다.

설치:
  pip install -r scripts/requirements-reel.txt
  sudo apt install ffmpeg

사용 예 (저장소 루트):

  # 슬라이드 + 나레이션만 (자막 없음, 기본)
  python scripts/make_reel.py create \\
    --script-file instagram_reels/260513_heygen.txt \\
    --scene-dir data/260513_순천만 \\
    --output output/reels/260513_slides.mp4

  # 자막 켜기
  python scripts/make_reel.py create ... --subtitle --font /path/to/NanumGothic.ttf

  # 자막,푸터만 빠르게 PNG 확인 (TTS,mp4 인코딩 없음)
  python scripts/make_reel.py preview-text -o output/preview_subtitle.png --font /path/to/font.ttf

  # 하단 고정 문구 위치: --footer-bottom-margin 140 (클수록 위로)

  python scripts/make_reel.py list-voices
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from reel_defaults import (
    DEFAULT_FADE_SEC,
    DEFAULT_FOOTER_BOTTOM_MARGIN,
    DEFAULT_FOOTER_FONT_SIZE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_KEN_BURNS,
    DEFAULT_MUSIC_VOLUME,
    DEFAULT_PAD_SEC,
    DEFAULT_SUBTITLE_BOTTOM_MARGIN,
    DEFAULT_SUBTITLE_FONT_SIZE,
    DEFAULT_SUBTITLE_FOOTER_GAP,
    DEFAULT_SUBTITLE_MAX_CHARS,
    DEFAULT_WIDTH,
)
from reel_brand import (
    DEFAULT_FOOTER_LINE1,
    DEFAULT_FOOTER_LINE2,
    format_brand_catalog,
    pick_brand_intro,
    pick_brand_outro,
)
from reel_builder import BuildOptions, render_reel, render_subtitle_preview_image  # noqa: E402
from reel_common import images_sorted_from_dir  # noqa: E402
from reel_progress import ProgressReporter  # noqa: E402
from reel_fonts import resolve_font  # noqa: E402
from reel_tts import DEFAULT_EDGE_VOICE, list_edge_voices_korean  # noqa: E402

_DEFAULT_PREVIEW_TEXT = (
    "전남 순천,여수,광양 현장에서 고소작업차 운전 및 조종을 맡을 때는 "
    "안전한 위치 제어와 작업자와의 호흡이 가장 중요합니다."
)


def _collect_scene_image_paths(ns: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    for s in ns.scene_images or []:
        paths.append(Path(s).expanduser().resolve())
    if paths:
        return paths
    if ns.scene_dir:
        return images_sorted_from_dir(Path(ns.scene_dir).expanduser().resolve())
    return []


def cmd_list_voices(_: argparse.Namespace) -> None:
    for v in list_edge_voices_korean():
        print(
            f"{v.get('ShortName', '')}\t{v.get('Gender', '')}\t{v.get('FriendlyName', '')}"
        )


def cmd_create(ns: argparse.Namespace) -> None:
    script: str | None = ns.script
    script_src = "--script (인라인)"
    if ns.script_file:
        sf = Path(ns.script_file).expanduser().resolve()
        script = sf.read_text(encoding="utf-8")
        script_src = str(sf)
        if ns.script:
            print(
                "참고: --script 와 --script-file 을 같이 쓰면 파일 내용이 우선합니다.",
                flush=True,
            )
    if not script or not script.strip():
        raise SystemExit("--script 또는 --script-file 이 필요합니다.")

    full = script.strip()
    brand_note = ""
    if not ns.no_brand:
        brand_note = " | TTS에는 기본 인,아웃트로가 앞뒤로 붙습니다(--no-brand 로 끄기)"
    print(f"TTS 대본: {script_src} ({len(full)}자){brand_note}", flush=True)
    print("--- 본문 전체 ---", flush=True)
    print(full, flush=True)
    print("--- 본문 끝 ---", flush=True)

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

    prog = ProgressReporter(enabled=not ns.no_progress)

    out = Path(ns.output).expanduser().resolve()
    brand_seed = out.stem
    if ns.intro is not None:
        brand_intro = ns.intro
    else:
        brand_intro = pick_brand_intro(brand_seed, index=ns.intro_variant)
    if ns.outro is not None:
        brand_outro = ns.outro
    else:
        brand_outro = pick_brand_outro(brand_seed, index=ns.outro_variant)

    if not ns.no_brand:
        print(f"🎙 인트로: {brand_intro}", flush=True)
        print(f"🎙 아웃트로: {brand_outro}", flush=True)

    opts = BuildOptions(
        width=ns.width,
        height=ns.height,
        fps=ns.fps,
        fade_sec=ns.fade,
        pad_sec=ns.pad,
        ken_burns=ns.ken_burns,
        music_path=music,
        music_volume=ns.music_volume,
        subtitle=ns.subtitle,
        font_path=font,
        subtitle_max_chars=ns.subtitle_chars,
        subtitle_font_size=ns.subtitle_font_size,
        tts_engine=ns.tts_engine,
        tts_voice=ns.tts_voice,
        tts_rate=ns.tts_rate,
        tts_lang=ns.tts_lang,
        tts_slow=ns.tts_slow,
        progress=prog,
        brand_wrap=not ns.no_brand,
        brand_intro=brand_intro,
        brand_outro=brand_outro,
        footer_overlay=not ns.no_footer,
        footer_line1=DEFAULT_FOOTER_LINE1 if ns.footer_line1 is None else ns.footer_line1,
        footer_line2=DEFAULT_FOOTER_LINE2 if ns.footer_line2 is None else ns.footer_line2,
        footer_font_size=ns.footer_font_size,
        footer_bottom_margin=ns.footer_bottom_margin,
        subtitle_footer_gap=ns.subtitle_footer_gap,
        subtitle_bottom_margin=ns.subtitle_bottom_margin,
    )

    work = Path(ns.work_dir).expanduser().resolve() if ns.work_dir else None

    result = render_reel(
        script=script,
        image_paths=scene_paths,
        default_image=bg_one,
        output=out,
        work_dir=work,
        opts=opts,
    )
    if ns.no_progress:
        print(f"완료: {result}", flush=True)


def cmd_list_brand_lines(_ns: argparse.Namespace) -> None:
    print(format_brand_catalog(), flush=True)


def cmd_preview_text(ns: argparse.Namespace) -> None:
    """TTS,영상 인코딩 없이 자막,푸터 합성만 PNG로 저장."""
    font = resolve_font(Path(ns.font).expanduser().resolve() if ns.font else None)
    out = Path(ns.output).expanduser().resolve()
    suf = out.suffix.lower()
    if suf and suf != ".png":
        raise SystemExit("preview-text 는 PNG 저장만 지원합니다. --output 파일명을 .png 로 지정하세요.")
    if not suf:
        out = out.with_suffix(".png")

    bg: Path | None = None
    if ns.background_image:
        bg = Path(ns.background_image).expanduser().resolve()
        if not bg.is_file():
            raise SystemExit(f"배경 이미지 없음: {bg}")

    img = render_subtitle_preview_image(
        width=ns.width,
        height=ns.height,
        font_path=font,
        sample_subtitle=ns.sample_text,
        subtitle_max_chars=ns.subtitle_chars,
        subtitle_font_size=ns.subtitle_font_size,
        show_subtitle=not ns.no_subtitle,
        footer_overlay=not ns.no_footer,
        footer_line1=DEFAULT_FOOTER_LINE1 if ns.footer_line1 is None else ns.footer_line1,
        footer_line2=DEFAULT_FOOTER_LINE2 if ns.footer_line2 is None else ns.footer_line2,
        footer_font_size=ns.footer_font_size,
        footer_bottom_margin=ns.footer_bottom_margin,
        subtitle_footer_gap=ns.subtitle_footer_gap,
        subtitle_bottom_margin=ns.subtitle_bottom_margin,
        background_image=bg,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), format="PNG")
    print(f"미리보기 저장: {out}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="이미지+edge-tts 릴스 로컬 렌더 (기본 자막 없음)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    lv = sub.add_parser("list-voices", help="edge-tts 한국어 보이스 목록")
    lv.set_defaults(func=cmd_list_voices)

    lb = sub.add_parser("list-brand-lines", help="릴스 인,아웃트로 후보 목록")
    lb.set_defaults(func=cmd_list_brand_lines)

    c = sub.add_parser("create", help="MP4 릴스 생성")
    c.add_argument("--script", help="나레이션 전체 텍스트 (--script-file 과 동시 지정 시 파일이 우선)")
    c.add_argument("--script-file", help="나레이션 텍스트 파일 (--script 과 동시 지정 시 이쪽이 우선)")
    c.add_argument("--background-image", help="배경 이미지 1장")
    c.add_argument(
        "--scene-dir",
        help="폴더 안 jpg/png (파일명 순). 나레이션 한 블록이면 슬라이드쇼, --- 로 나누면 씬별 TTS",
    )
    c.add_argument(
        "--scene-image",
        action="append",
        dest="scene_images",
        metavar="PATH",
        help="배경 이미지 (--scene-dir 보다 우선)",
    )
    c.add_argument(
        "--music",
        metavar="PATH",
        help="배경음 (mp3/wav 등). 나레이션보다 작게 믹스",
    )
    c.add_argument(
        "--music-volume",
        type=float,
        default=DEFAULT_MUSIC_VOLUME,
        help=f"배경음 볼륨 0~1 (기본 {DEFAULT_MUSIC_VOLUME}). 보이스 위주면 0.02~0.06 권장",
    )
    c.add_argument("--output", required=True, help="출력 mp4 경로")
    c.add_argument("--work-dir", help="중간 파일 폴더")
    c.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    c.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    c.add_argument("--fps", type=int, default=DEFAULT_FPS)
    c.add_argument("--fade", type=float, default=DEFAULT_FADE_SEC)
    c.add_argument("--pad", type=float, default=DEFAULT_PAD_SEC)
    c.add_argument("--ken-burns", type=float, default=DEFAULT_KEN_BURNS)
    c.add_argument(
        "--subtitle",
        action="store_true",
        help="화면 자막 켜기(슬라이드마다 나눔). --font 권장",
    )
    c.add_argument("--subtitle-chars", type=int, default=DEFAULT_SUBTITLE_MAX_CHARS)
    c.add_argument("--subtitle-font-size", type=int, default=DEFAULT_SUBTITLE_FONT_SIZE)
    c.add_argument(
        "--font",
        default=None,
        help="한글 폰트 .ttf/.otf/.ttc (하단 고정 문구,자막, 생략 시 자동 탐색)",
    )
    c.add_argument(
        "--tts-engine",
        choices=("edge", "gtts"),
        default="edge",
        help="TTS 엔진 (기본 edge)",
    )
    c.add_argument(
        "--tts-voice",
        default=DEFAULT_EDGE_VOICE,
        help=f"edge-tts 보이스 (기본 {DEFAULT_EDGE_VOICE})",
    )
    c.add_argument(
        "--tts-rate",
        default="+0%",
        help="edge-tts 속도 (예: +10%%, -5%%)",
    )
    c.add_argument("--tts-lang", default="ko", help="gTTS 언어 (tts-engine=gtts 일 때)")
    c.add_argument("--tts-slow", action="store_true", help="gTTS 느린 발음")
    c.add_argument(
        "--no-brand",
        action="store_true",
        help="TTS 앞뒤 브랜드 문구(기본 인,아웃트로) 넣지 않기",
    )
    c.add_argument(
        "--intro",
        metavar="TEXT",
        default=None,
        help="앞 문구 (생략 시 출력 파일명 기준 자동 선택, 목록: list-brand-lines)",
    )
    c.add_argument(
        "--intro-variant",
        type=int,
        default=None,
        metavar="N",
        help="인트로 후보 번호 (list-brand-lines 참고). --intro 보다 우선하지 않음",
    )
    c.add_argument(
        "--outro",
        metavar="TEXT",
        default=None,
        help="뒤 문구 (생략 시 출력 파일명 기준 자동 선택)",
    )
    c.add_argument(
        "--outro-variant",
        type=int,
        default=None,
        metavar="N",
        help="아웃트로 후보 번호",
    )
    c.add_argument(
        "--no-footer",
        action="store_true",
        help="하단 고정 문구(브랜드,문의) 끄기",
    )
    c.add_argument(
        "--footer-line1",
        metavar="TEXT",
        default=None,
        help=f"하단 첫 줄 (기본: {DEFAULT_FOOTER_LINE1})",
    )
    c.add_argument(
        "--footer-line2",
        metavar="TEXT",
        default=None,
        help=f"하단 둘째 줄 (기본: {DEFAULT_FOOTER_LINE2})",
    )
    c.add_argument(
        "--footer-font-size",
        type=int,
        default=DEFAULT_FOOTER_FONT_SIZE,
        help=f"하단 고정 문구 글자 크기 (기본 {DEFAULT_FOOTER_FONT_SIZE})",
    )
    c.add_argument(
        "--footer-bottom-margin",
        type=int,
        default=DEFAULT_FOOTER_BOTTOM_MARGIN,
        metavar="PX",
        help=f"푸터 바를 화면 아래에서 몇 px 위에 둘지 (클수록 위로, 기본 {DEFAULT_FOOTER_BOTTOM_MARGIN})",
    )
    c.add_argument(
        "--subtitle-footer-gap",
        type=int,
        default=DEFAULT_SUBTITLE_FOOTER_GAP,
        metavar="PX",
        help=f"푸터와 나레이션 자막 사이 간격 (--subtitle 일 때, 기본 {DEFAULT_SUBTITLE_FOOTER_GAP})",
    )
    c.add_argument(
        "--subtitle-bottom-margin",
        type=int,
        default=DEFAULT_SUBTITLE_BOTTOM_MARGIN,
        metavar="PX",
        help=f"자막만 있을 때 화면 아래 여백 (기본 {DEFAULT_SUBTITLE_BOTTOM_MARGIN})",
    )
    c.add_argument(
        "--no-progress",
        action="store_true",
        help="진행률 바(tqdm) 끄기",
    )
    c.set_defaults(func=cmd_create)

    pt = sub.add_parser(
        "preview-text",
        help="자막,푸터 레이아웃만 PNG로 빠르게 확인 (TTS,mp4 인코딩 없음)",
    )
    pt.add_argument("--output", "-o", required=True, help="출력 PNG 경로")
    pt.add_argument(
        "--sample-text",
        default=_DEFAULT_PREVIEW_TEXT,
        help="미리보기에 쓸 나레이션 샘플 문장",
    )
    pt.add_argument(
        "--background-image",
        metavar="PATH",
        help="배경 사진 (없으면 단색 배경)",
    )
    pt.add_argument(
        "--font",
        default=None,
        help="한글 폰트 (생략 시 자동 탐색, create 과 동일)",
    )
    pt.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    pt.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    pt.add_argument("--subtitle-chars", type=int, default=DEFAULT_SUBTITLE_MAX_CHARS)
    pt.add_argument(
        "--subtitle-font-size",
        type=int,
        default=DEFAULT_SUBTITLE_FONT_SIZE,
    )
    pt.add_argument(
        "--no-subtitle",
        action="store_true",
        help="나레이션 자막 블록만 끄고 푸터만 보기",
    )
    pt.add_argument(
        "--no-footer",
        action="store_true",
        help="하단 고정 문구 끄고 자막만 보기",
    )
    pt.add_argument(
        "--footer-line1",
        metavar="TEXT",
        default=None,
        help=f"하단 첫 줄 (기본: {DEFAULT_FOOTER_LINE1})",
    )
    pt.add_argument(
        "--footer-line2",
        metavar="TEXT",
        default=None,
        help=f"하단 둘째 줄 (기본: {DEFAULT_FOOTER_LINE2})",
    )
    pt.add_argument(
        "--footer-font-size",
        type=int,
        default=DEFAULT_FOOTER_FONT_SIZE,
        help=f"하단 고정 문구 글자 크기 (기본 {DEFAULT_FOOTER_FONT_SIZE})",
    )
    pt.add_argument(
        "--footer-bottom-margin",
        type=int,
        default=DEFAULT_FOOTER_BOTTOM_MARGIN,
        metavar="PX",
        help=f"푸터 바를 화면 아래에서 몇 px 위에 둘지 (기본 {DEFAULT_FOOTER_BOTTOM_MARGIN})",
    )
    pt.add_argument(
        "--subtitle-footer-gap",
        type=int,
        default=DEFAULT_SUBTITLE_FOOTER_GAP,
        metavar="PX",
        help=f"푸터와 나레이션 자막 사이 간격 (기본 {DEFAULT_SUBTITLE_FOOTER_GAP})",
    )
    pt.add_argument(
        "--subtitle-bottom-margin",
        type=int,
        default=DEFAULT_SUBTITLE_BOTTOM_MARGIN,
        metavar="PX",
        help=f"푸터 없을 때 자막 아래 여백 (기본 {DEFAULT_SUBTITLE_BOTTOM_MARGIN})",
    )
    pt.set_defaults(func=cmd_preview_text)

    return p


def main() -> None:
    parser = build_parser()
    ns = parser.parse_args()
    ns.func(ns)


if __name__ == "__main__":
    main()
