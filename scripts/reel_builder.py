"""
이미지 + edge-tts 나레이션 + (선택) 자막,배경음악으로 세로형 릴스 MP4를 만듭니다.
기본은 자막 없음(슬라이드 + 보이스만 권장).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from moviepy.audio.AudioClip import AudioArrayClip
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw

# moviepy 1.x + Pillow 10+
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]

from reel_brand import (
    DEFAULT_BRAND_INTRO,
    DEFAULT_BRAND_OUTRO,
    DEFAULT_FOOTER_LINE1,
    DEFAULT_FOOTER_LINE2,
    apply_brand_to_segments,
)
from reel_defaults import (
    DEFAULT_FADE_SEC,
    DEFAULT_FOOTER_BOTTOM_MARGIN,
    DEFAULT_FOOTER_FONT_SIZE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_KEN_BURNS,
    DEFAULT_MUSIC_VOLUME,
    DEFAULT_ONSCREEN_FONT_SCALE,
    DEFAULT_PAD_SEC,
    DEFAULT_SUBTITLE_BOTTOM_MARGIN,
    DEFAULT_SUBTITLE_FONT_SIZE,
    DEFAULT_SUBTITLE_FOOTER_GAP,
    DEFAULT_SUBTITLE_MAX_CHARS,
    DEFAULT_WIDTH,
)
from reel_common import script_segments_explicit, split_script_scenes
from reel_fonts import _load_font, resolve_font
from reel_progress import ProgressReporter
from reel_tts import synthesize, synthesize_scenes


@dataclass
class SceneSpec:
    text: str
    image: Path | None
    audio_path: Path
    duration: float


@dataclass
class BuildOptions:
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    fade_sec: float = DEFAULT_FADE_SEC
    pad_sec: float = DEFAULT_PAD_SEC
    ken_burns: float = DEFAULT_KEN_BURNS
    music_path: Path | None = None
    music_volume: float = DEFAULT_MUSIC_VOLUME
    subtitle: bool = False
    font_path: Path | None = None
    subtitle_max_chars: int = DEFAULT_SUBTITLE_MAX_CHARS
    subtitle_font_size: int = DEFAULT_SUBTITLE_FONT_SIZE
    # TTS
    tts_engine: str = "edge"
    tts_voice: str = "ko-KR-SunHiNeural"
    tts_rate: str = "+0%"
    tts_lang: str = "ko"
    tts_slow: bool = False
    progress: ProgressReporter | None = None
    brand_wrap: bool = True
    brand_intro: str = DEFAULT_BRAND_INTRO
    brand_outro: str = DEFAULT_BRAND_OUTRO
    footer_overlay: bool = True
    footer_line1: str = DEFAULT_FOOTER_LINE1
    footer_line2: str = DEFAULT_FOOTER_LINE2
    footer_font_size: int = DEFAULT_FOOTER_FONT_SIZE
    # 세로 위치(px): footer_bottom_margin 이 클수록 푸터가 화면 위로 올라감
    footer_bottom_margin: int = DEFAULT_FOOTER_BOTTOM_MARGIN
    subtitle_footer_gap: int = DEFAULT_SUBTITLE_FOOTER_GAP
    subtitle_bottom_margin: int = DEFAULT_SUBTITLE_BOTTOM_MARGIN


def require_ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).is_file():
            return bundled
    except ImportError:
        pass
    raise RuntimeError(
        "ffmpeg 가 필요합니다. Ubuntu/WSL: sudo apt install ffmpeg "
        "또는 pip install imageio-ffmpeg"
    )


def audio_duration_sec(path: Path) -> float:
    clip = AudioFileClip(str(path))
    try:
        return float(clip.duration)
    finally:
        clip.close()


def cover_fit_image(path: Path, width: int, height: int) -> np.ndarray:
    with Image.open(path) as im:
        im = im.convert("RGB")
        src_w, src_h = im.size
        scale = max(width / src_w, height / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - width) // 2
        top = (new_h - height) // 2
        im = im.crop((left, top, left + width, top + height))
        return np.array(im)


def _wrap_subtitle(text: str, max_chars: int) -> list[str]:
    """한국어 중심 줄바꿈(공백 없어도 글자 수 기준)."""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    lines: list[str] = []
    rest = text
    while rest and len(lines) < 3:
        if len(rest) <= max_chars:
            lines.append(rest)
            break
        chunk = rest[: max_chars + 1]
        # 공백,쉼표,마침표 근처에서 끊기
        break_at = -1
        for sep in (" ", ",", ".", "。", "!", "?"):
            pos = chunk.rfind(sep, 0, max_chars)
            if pos > max_chars // 3:
                break_at = pos
                break
        if break_at > 0:
            lines.append(rest[:break_at].strip())
            rest = rest[break_at:].strip()
        else:
            lines.append(rest[:max_chars])
            rest = rest[max_chars:]
    return lines


def render_subtitle_png(
    lines: list[str],
    *,
    width: int,
    font_path: Path,
    font_size: int = DEFAULT_SUBTITLE_FONT_SIZE,
) -> np.ndarray:
    line_h = int(font_size * 1.35)
    bar_h = line_h * len(lines) + 48
    img = Image.new("RGBA", (width, bar_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, bar_h), fill=(0, 0, 0, 170))
    font = _load_font(font_path, font_size)
    y = 20
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (width - tw) // 2
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h
    return np.array(img)


def render_footer_png(
    lines: list[str],
    *,
    width: int,
    font_path: Path,
    font_size: int = DEFAULT_FOOTER_FONT_SIZE,
) -> np.ndarray:
    """하단 고정 연락,브랜드 바."""
    line_h = int(font_size * 1.28)
    bar_h = line_h * len(lines) + 36
    img = Image.new("RGBA", (width, bar_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, bar_h), fill=(0, 0, 0, 200))
    font = _load_font(font_path, font_size)
    y = 14
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (width - tw) // 2
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h
    return np.array(img)


def scaled_onscreen_font_sizes(
    width: int, *, font_size: int, footer_font_size: int
) -> tuple[int, int]:
    """create / preview 공통: 1080 기준 pt에 화면 배율을 곱한 실제 그리기 크기."""
    _w = max(1, width)
    _mul = (_w / 1080.0) * DEFAULT_ONSCREEN_FONT_SCALE
    sub_px = max(28, int(round(font_size * _mul)))
    foot_px = max(24, int(round(footer_font_size * _mul)))
    return sub_px, foot_px


def render_subtitle_preview_image(
    *,
    width: int,
    height: int,
    font_path: Path,
    sample_subtitle: str,
    subtitle_max_chars: int,
    subtitle_font_size: int,
    show_subtitle: bool,
    footer_overlay: bool,
    footer_line1: str,
    footer_line2: str,
    footer_font_size: int,
    footer_bottom_margin: int,
    subtitle_footer_gap: int,
    subtitle_bottom_margin: int,
    background_image: Path | None = None,
) -> Image.Image:
    """
    TTS,인코딩 없이 자막,푸터만 PNG로 빠르게 확인 (실제 렌더와 동일 배치,스케일).
    """
    if background_image and background_image.is_file():
        frame_rgb = cover_fit_image(background_image, width, height)
    else:
        frame_rgb = np.full((height, width, 3), 48, dtype=np.uint8)
    base = Image.fromarray(frame_rgb).convert("RGBA")

    sub_px, foot_px = scaled_onscreen_font_sizes(
        width, font_size=subtitle_font_size, footer_font_size=footer_font_size
    )

    foot_lines: list[str] = []
    foot_img_np: np.ndarray | None = None
    if footer_overlay:
        for line in (footer_line1, footer_line2):
            s = (line or "").strip()
            if s:
                foot_lines.append(s)
        if foot_lines:
            foot_img_np = render_footer_png(
                foot_lines,
                width=width,
                font_path=font_path,
                font_size=foot_px,
            )
    foot_h = int(foot_img_np.shape[0]) if foot_img_np is not None else 0

    subtitle_lines: list[str] | None = None
    if show_subtitle and sample_subtitle.strip():
        subtitle_lines = _wrap_subtitle(sample_subtitle.strip(), subtitle_max_chars)

    if subtitle_lines:
        sub_img = render_subtitle_png(
            subtitle_lines,
            width=width,
            font_path=font_path,
            font_size=sub_px,
        )
        sub_h = sub_img.shape[0]
        if foot_h:
            foot_top = height - foot_h - footer_bottom_margin
            sub_y = foot_top - subtitle_footer_gap - sub_h
        else:
            sub_y = height - sub_h - subtitle_bottom_margin
        sub_pil = Image.fromarray(sub_img).convert("RGBA")
        base.paste(sub_pil, (0, sub_y), sub_pil)

    if foot_img_np is not None:
        fh = foot_img_np.shape[0]
        fy = height - fh - footer_bottom_margin
        foot_pil = Image.fromarray(foot_img_np).convert("RGBA")
        base.paste(foot_pil, (0, fy), foot_pil)

    return base.convert("RGB")


def make_scene_clip(
    frame: np.ndarray,
    duration: float,
    *,
    fps: int,
    ken_burns: float,
    subtitle_lines: list[str] | None,
    font_path: Path | None,
    font_size: int,
    width: int,
    height: int,
    footer_lines: list[str] | None = None,
    footer_font_path: Path | None = None,
    footer_font_size: int = DEFAULT_FOOTER_FONT_SIZE,
    footer_bottom_margin: int = DEFAULT_FOOTER_BOTTOM_MARGIN,
    subtitle_footer_gap: int = DEFAULT_SUBTITLE_FOOTER_GAP,
    subtitle_bottom_margin: int = DEFAULT_SUBTITLE_BOTTOM_MARGIN,
):
    sub_px, foot_px = scaled_onscreen_font_sizes(
        width, font_size=font_size, footer_font_size=footer_font_size
    )

    base = ImageClip(frame).set_duration(duration)
    h, w = frame.shape[0], frame.shape[1]

    if ken_burns > 0:

        def zoom(t: float) -> float:
            return 1.0 + ken_burns * (t / max(duration, 0.001))

        zoomed = base.resize(zoom).set_position("center")
        clip = CompositeVideoClip([zoomed], size=(w, h)).set_duration(duration)
    else:
        clip = base

    layers = [clip]

    foot_clean: list[str] = []
    foot_img_np: np.ndarray | None = None
    if footer_lines and footer_font_path:
        foot_clean = [x.strip() for x in footer_lines if x and str(x).strip()]
        if foot_clean:
            foot_img_np = render_footer_png(
                foot_clean,
                width=width,
                font_path=footer_font_path,
                font_size=foot_px,
            )
    foot_h = int(foot_img_np.shape[0]) if foot_img_np is not None else 0

    if subtitle_lines and font_path:
        sub_img = render_subtitle_png(
            subtitle_lines,
            width=width,
            font_path=font_path,
            font_size=sub_px,
        )
        sub_h = sub_img.shape[0]
        if foot_h:
            foot_top = height - foot_h - footer_bottom_margin
            sub_y = foot_top - subtitle_footer_gap - sub_h
        else:
            sub_y = height - sub_h - subtitle_bottom_margin
        sub_clip = (
            ImageClip(sub_img, ismask=False)
            .set_duration(duration)
            .set_position(("center", sub_y))
        )
        layers.append(sub_clip)

    if foot_img_np is not None:
        fh = foot_img_np.shape[0]
        foot_clip = (
            ImageClip(foot_img_np, ismask=False)
            .set_duration(duration)
            .set_position(("center", height - fh - footer_bottom_margin))
        )
        layers.append(foot_clip)

    if len(layers) > 1:
        clip = CompositeVideoClip(layers, size=(width, height)).set_duration(duration)
    else:
        clip = clip.set_duration(duration)

    return clip.set_fps(fps)


def _padded_voice_clip(audio_path: Path, pad_sec: float) -> AudioFileClip:
    voice = AudioFileClip(str(audio_path))
    if pad_sec <= 0:
        return voice
    fps = int(voice.fps or 44100)
    n_samples = int(pad_sec * fps)
    silence = AudioArrayClip(
        np.zeros((n_samples, 1), dtype=np.float32), fps=fps
    ).set_duration(pad_sec)
    return concatenate_audioclips([voice, silence])


def _atomic_chunks(text: str) -> list[str]:
    """문장(.?!…) 단위, 긴 문장은 쉼표(,,、) 뒤에서 한 번 더 나눈다."""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。…])\s*", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= 52:
            out.append(p)
            continue
        subs = re.split(r"(?<=[,，、])\s*", p)
        subs = [s.strip() for s in subs if s.strip()]
        out.extend(subs if len(subs) > 1 else [p])
    return out


def _merge_chunks_to_n(chunks: list[str], n: int) -> list[str]:
    """구절이 n개보다 많으면 짧은 인접 구절부터 합쳐 n개로 만든다."""
    cur = list(chunks)
    while len(cur) > n:
        best_i = 0
        best_score = 10**9
        for i in range(len(cur) - 1):
            score = len(cur[i]) + len(cur[i + 1])
            if score < best_score:
                best_score = score
                best_i = i
        cur[best_i : best_i + 2] = [cur[best_i] + " " + cur[best_i + 1]]
    return cur


def _split_longest_for_more_bins(cur: list[str]) -> None:
    """가장 긴 한 덩어리를 공백,중간에서 둘로 나눠 길이를 줄인다."""
    idx = max(range(len(cur)), key=lambda i: len(cur[i]))
    s = cur[idx]
    if len(s) < 6:
        return
    mid = len(s) // 2
    cut = s.rfind(" ", 1, mid + 12)
    if cut <= 0:
        cut = mid
    a, b = s[:cut].strip(), s[cut:].strip()
    if not a or not b:
        cut = mid
        a, b = s[:cut].strip(), s[cut:].strip()
    if a and b:
        cur[idx : idx + 1] = [a, b]


def split_narration_for_slides(text: str, n: int) -> list[str]:
    """
    한 덩어리 나레이션을 슬라이드 n장에 맞게 나눈다.
    문장,쉼표 경계를 우선하고, 구절이 많으면 짧은 것끼리 합친다.
    """
    if n < 1:
        raise ValueError("n >= 1")
    if n == 1:
        return [re.sub(r"\s+", " ", text.strip())]
    chunks = _atomic_chunks(text)
    if not chunks:
        return [""] * n

    cur = list(chunks)
    if len(cur) >= n:
        parts = _merge_chunks_to_n(cur, n)
    else:
        while len(cur) < n:
            _split_longest_for_more_bins(cur)
            if len(cur) >= n:
                break
            if len(cur) == 1 and len(cur[0]) < 4:
                break
        parts = cur[:n] if len(cur) >= n else cur + [""] * (n - len(cur))
        parts = parts[:n]

    if len(parts) != n:
        parts = (parts + [""] * n)[:n]
    return [p.strip() for p in parts]


def build_slideshow_scenes(
    text: str,
    image_paths: list[Path],
    work_dir: Path,
    opts: BuildOptions,
) -> list[SceneSpec]:
    """나레이션 1개 + 사진 N장 → 사진만 순서대로 전환."""
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / "narration.mp3"
    if opts.progress:
        opts.progress.begin_stage(0, f"나레이션 1개 , 사진 {len(image_paths)}장")
    synthesize(
        text,
        audio_path,
        engine=opts.tts_engine,
        edge_voice=opts.tts_voice,
        edge_rate=opts.tts_rate,
        gtts_lang=opts.tts_lang,
        gtts_slow=opts.tts_slow,
    )
    if opts.progress:
        opts.progress.finish_stage(0)

    voice = _padded_voice_clip(audio_path, opts.pad_sec)
    total = float(voice.duration)
    voice.close()

    n = len(image_paths)
    fade = opts.fade_sec if n > 1 else 0.0
    # crossfade padding 으로 짧아지는 만큼 슬라이드 길이 보정
    slide_dur = (total + (n - 1) * fade) / n if n else total

    if opts.subtitle:
        captions = split_narration_for_slides(text, n)
    else:
        captions = [text] * n

    return [
        SceneSpec(
            text=captions[i],
            image=image_paths[i],
            audio_path=audio_path,
            duration=slide_dur,
        )
        for i in range(n)
    ]


def build_scenes(
    segments: list[str],
    image_paths: list[Path | None],
    work_dir: Path,
    opts: BuildOptions,
) -> list[SceneSpec]:
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_paths = synthesize_scenes(
        segments,
        work_dir,
        engine=opts.tts_engine,
        edge_voice=opts.tts_voice,
        edge_rate=opts.tts_rate,
        gtts_lang=opts.tts_lang,
        gtts_slow=opts.tts_slow,
        progress=opts.progress,
    )

    scenes: list[SceneSpec] = []
    for i, (text, audio_path) in enumerate(zip(segments, audio_paths)):
        voice = _padded_voice_clip(audio_path, opts.pad_sec)
        dur = float(voice.duration)
        voice.close()
        img = image_paths[i] if i < len(image_paths) else None
        scenes.append(
            SceneSpec(text=text, image=img, audio_path=audio_path, duration=dur)
        )
    return scenes


def compose_video(
    scenes: list[SceneSpec],
    opts: BuildOptions,
    *,
    default_image: Path | None,
    work_dir: Path,
) -> tuple[Path, Path]:
    prog = opts.progress
    if prog:
        prog.begin_stage(1, "클립 조립")

    require_ffmpeg()
    need_font = opts.subtitle or opts.footer_overlay
    font_path = resolve_font(opts.font_path) if need_font else None
    if font_path and prog:
        prog.stage_fraction(1, 0.1, f"폰트 {font_path.name}")

    fallback = default_image
    if not fallback and scenes and scenes[0].image:
        fallback = scenes[0].image

    clips = []
    voice_tracks: list[AudioFileClip] = []
    n = len(scenes)
    shared_audio = (
        n > 1 and len({s.audio_path.resolve() for s in scenes}) == 1
    )

    for i, scene in enumerate(scenes):
        img_path = scene.image or fallback
        if not img_path or not img_path.is_file():
            raise FileNotFoundError(
                f"씬 {i + 1} 배경 이미지가 없습니다. --background-image 또는 --scene-dir 을 확인하세요."
            )
        frame = cover_fit_image(img_path, opts.width, opts.height)
        sub_lines = (
            _wrap_subtitle(scene.text, opts.subtitle_max_chars) if opts.subtitle else None
        )
        foot_lines = None
        if opts.footer_overlay:
            foot_lines = [opts.footer_line1, opts.footer_line2]
        v = make_scene_clip(
            frame,
            scene.duration,
            fps=opts.fps,
            ken_burns=opts.ken_burns,
            subtitle_lines=sub_lines,
            font_path=font_path,
            font_size=opts.subtitle_font_size,
            width=opts.width,
            height=opts.height,
            footer_lines=foot_lines,
            footer_font_path=font_path if opts.footer_overlay else None,
            footer_font_size=opts.footer_font_size,
            footer_bottom_margin=opts.footer_bottom_margin,
            subtitle_footer_gap=opts.subtitle_footer_gap,
            subtitle_bottom_margin=opts.subtitle_bottom_margin,
        )
        if not shared_audio:
            a_video = _padded_voice_clip(scene.audio_path, opts.pad_sec)
            v = v.set_audio(a_video)
            voice_tracks.append(a_video)
        if clips and opts.fade_sec > 0:
            v = v.crossfadein(opts.fade_sec)
        clips.append(v)
        if prog:
            label = f"슬라이드 {i + 1}/{n}" if shared_audio else f"씬 {i + 1}/{n}"
            prog.stage_fraction(1, (i + 1) / n, label)

    if prog:
        prog.finish_stage(1)

    pad = -opts.fade_sec if len(clips) > 1 and opts.fade_sec > 0 else 0
    final_v = concatenate_videoclips(clips, method="compose", padding=pad)

    video_path = work_dir / "video_noaudio.mp4"
    voice_path = work_dir / "voice.mp3"

    if prog:
        prog.begin_stage(2, "인코딩")

    mp_logger = prog.moviepy_logger() if prog else None

    final_v.write_videofile(
        str(video_path),
        fps=opts.fps,
        codec="libx264",
        audio=False,
        preset="medium",
        threads=4,
        logger=mp_logger,
    )

    if prog:
        prog.finish_stage(2, "영상 저장됨")
        prog.begin_stage(3, "나레이션 트랙")

    if shared_audio:
        narration = _padded_voice_clip(scenes[0].audio_path, opts.pad_sec)
        if narration.duration > final_v.duration:
            narration = narration.subclip(0, final_v.duration)
        narration.write_audiofile(str(voice_path), logger=mp_logger)
        narration.close()
        if prog:
            prog.finish_stage(3, "슬라이드쇼 1트랙")
    else:
        if prog:
            prog.stage_fraction(3, 0.2, "트랙 합치기")
        voice = concatenate_audioclips(voice_tracks).set_fps(44100)
        voice.write_audiofile(str(voice_path), logger=mp_logger)
        voice.close()
        if prog:
            prog.finish_stage(3)

    for c in clips:
        c.close()
    final_v.close()

    return video_path, voice_path


def mix_voice_and_music(
    voice_path: Path,
    music_path: Path | None,
    music_volume: float,
    out_path: Path,
    *,
    progress: ProgressReporter | None = None,
) -> Path:
    if progress:
        progress.stage_fraction(3, 0.55, "음성 믹스")

    voice = AudioFileClip(str(voice_path))
    afps = int(voice.fps or 44100)
    voice = voice.set_fps(afps)
    mp_logger = progress.moviepy_logger() if progress else None

    if not music_path:
        voice.write_audiofile(str(out_path), logger=mp_logger)
        voice.close()
        if progress:
            progress.finish_stage(3, "나레이션만")
        return out_path

    music = AudioFileClip(str(music_path)).volumex(music_volume).set_fps(afps)
    if music.duration < voice.duration:
        loops = int(voice.duration / music.duration) + 1
        music = concatenate_audioclips([music] * loops).set_fps(afps)
    music = music.subclip(0, voice.duration)
    mixed = CompositeAudioClip([music, voice]).set_duration(voice.duration).set_fps(
        afps
    )
    mixed.write_audiofile(str(out_path), logger=mp_logger)
    mixed.close()
    music.close()
    voice.close()
    if progress:
        progress.finish_stage(3, "BGM 믹스")
    return out_path


def mux_final(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    *,
    fps: int,
    progress: ProgressReporter | None = None,
) -> Path:
    if progress:
        progress.begin_stage(4, "ffmpeg 합성")

    require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        require_ffmpeg(),
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        "-r",
        str(fps),
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    if progress:
        progress.finish_stage(4)
    return output_path


def render_reel(
    *,
    script: str,
    image_paths: list[Path],
    default_image: Path | None,
    output: Path,
    work_dir: Path | None,
    opts: BuildOptions,
) -> Path:
    prog = opts.progress or ProgressReporter(enabled=True)
    opts.progress = prog

    explicit = script_segments_explicit(script)
    n_img = len(image_paths)

    if n_img > 1 and len(explicit) == 1:
        segments = explicit
        imgs: list[Path | None] = list(image_paths)
        slideshow = True
        print(
            f"슬라이드쇼 모드: 나레이션 1개 + 사진 {n_img}장 순환",
            flush=True,
        )
    elif n_img > 1:
        segments = split_script_scenes(script, n_img)
        imgs = list(image_paths)
        slideshow = False
        if len(segments) != n_img:
            raise ValueError(
                f"이미지 {n_img}장일 때 스크립트는 '---' 로 {n_img}구간이어야 합니다 "
                f"(현재 {len(explicit)}구간). 한 나레이션에 사진만 바꾸려면 --- 없이 한 블록으로 두세요."
            )
    elif default_image:
        segments = split_script_scenes(script, 1)
        imgs = [default_image] * len(segments)
        slideshow = False
    else:
        raise ValueError("이미지가 없습니다. --background-image 또는 --scene-dir 이 필요합니다.")

    segments_wrapped = apply_brand_to_segments(
        segments,
        enabled=opts.brand_wrap,
        intro=opts.brand_intro,
        outro=opts.brand_outro,
    )

    wd = work_dir or (output.parent / f".work_{output.stem}")
    wd.mkdir(parents=True, exist_ok=True)

    try:
        if slideshow:
            scenes = build_slideshow_scenes(segments_wrapped[0], image_paths, wd, opts)
        else:
            scenes = build_scenes(segments_wrapped, imgs, wd, opts)
        video_path, voice_path = compose_video(
            scenes,
            opts,
            default_image=default_image or (imgs[0] if imgs else None),
            work_dir=wd,
        )

        audio_mixed = wd / "audio_mixed.mp3"
        mix_voice_and_music(
            voice_path,
            opts.music_path,
            opts.music_volume,
            audio_mixed,
            progress=prog,
        )
        result = mux_final(
            video_path, audio_mixed, output, fps=opts.fps, progress=prog
        )
        prog.close(f"완료 → {result.name}")
        return result
    except Exception:
        prog.close("오류")
        raise
