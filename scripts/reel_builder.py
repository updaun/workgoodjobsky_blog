"""
이미지 + gTTS 나레이션 + 자막 + 배경음악으로 세로형 릴스 MP4를 만듭니다.
moviepy로 영상·음성을 합성하고, ffmpeg로 자막을 굽습니다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from gtts import gTTS
from moviepy.audio.AudioClip import AudioArrayClip
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    concatenate_audioclips,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

# moviepy 1.x + Pillow 10+
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]

from reel_common import split_script_scenes


@dataclass
class SceneSpec:
    text: str
    image: Path | None
    audio_path: Path
    duration: float


@dataclass
class BuildOptions:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    fade_sec: float = 0.4
    pad_sec: float = 0.35
    ken_burns: float = 0.04
    music_path: Path | None = None
    music_volume: float = 0.12
    subtitle: bool = True
    font_path: Path | None = None
    subtitle_max_chars: int = 16
    tts_lang: str = "ko"
    tts_slow: bool = False


FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def resolve_font(explicit: Path | None) -> Path:
    if explicit:
        p = explicit.expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"폰트 파일 없음: {p}")
        return p
    for cand in FONT_CANDIDATES:
        if Path(cand).is_file():
            return Path(cand)
    raise FileNotFoundError(
        "한글 자막용 폰트를 찾지 못했습니다. --font 로 .ttf/.ttc 경로를 지정하세요."
    )


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


def synthesize_tts(text: str, out_mp3: Path, *, lang: str, slow: bool) -> None:
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    gTTS(text=text, lang=lang, slow=slow).save(str(out_mp3))


def audio_duration_sec(path: Path) -> float:
    clip = AudioFileClip(str(path))
    try:
        return float(clip.duration)
    finally:
        clip.close()


def cover_fit_image(path: Path, width: int, height: int) -> np.ndarray:
    """세로 프레임을 꽉 채우도록 크롭·리사이즈."""
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
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return [text]
    lines: list[str] = []
    buf = ""
    for token in re.split(r"(\s+)", text):
        if not token.strip():
            continue
        candidate = (buf + " " + token).strip() if buf else token
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                lines.append(buf)
            buf = token
    if buf:
        lines.append(buf)
    return lines[:3]


def render_subtitle_png(
    lines: list[str],
    *,
    width: int,
    font_path: Path,
    font_size: int = 52,
) -> np.ndarray:
    """하단 자막 바를 RGBA numpy 로 반환."""
    line_h = int(font_size * 1.35)
    bar_h = line_h * len(lines) + 48
    img = Image.new("RGBA", (width, bar_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, bar_h), fill=(0, 0, 0, 170))
    font = ImageFont.truetype(str(font_path), font_size)
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


def make_scene_clip(
    frame: np.ndarray,
    duration: float,
    *,
    fps: int,
    ken_burns: float,
    subtitle_lines: list[str] | None,
    font_path: Path | None,
    width: int,
    height: int,
):
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
    if subtitle_lines and font_path:
        sub_img = render_subtitle_png(
            subtitle_lines, width=width, font_path=font_path
        )
        sub_h = sub_img.shape[0]
        sub_clip = (
            ImageClip(sub_img, ismask=False)
            .set_duration(duration)
            .set_position(("center", height - sub_h - 80))
        )
        layers.append(sub_clip)

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


def build_scenes(
    segments: list[str],
    image_paths: list[Path | None],
    work_dir: Path,
    opts: BuildOptions,
) -> list[SceneSpec]:
    work_dir.mkdir(parents=True, exist_ok=True)
    scenes: list[SceneSpec] = []
    for i, text in enumerate(segments):
        audio_path = work_dir / f"scene_{i:02d}.mp3"
        synthesize_tts(text, audio_path, lang=opts.tts_lang, slow=opts.tts_slow)
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
    """영상(무음) + 나레이션 음성 파일 경로 반환."""
    require_ffmpeg()
    font_path = resolve_font(opts.font_path) if opts.subtitle else None
    fallback = default_image
    if not fallback and scenes and scenes[0].image:
        fallback = scenes[0].image

    clips = []
    voice_tracks: list[AudioFileClip] = []

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
        v = make_scene_clip(
            frame,
            scene.duration,
            fps=opts.fps,
            ken_burns=opts.ken_burns,
            subtitle_lines=sub_lines,
            font_path=font_path,
            width=opts.width,
            height=opts.height,
        )
        a_video = _padded_voice_clip(scene.audio_path, opts.pad_sec)
        v = v.set_audio(a_video)
        if clips and opts.fade_sec > 0:
            v = v.crossfadein(opts.fade_sec)
        clips.append(v)
        voice_tracks.append(_padded_voice_clip(scene.audio_path, opts.pad_sec))

    pad = -opts.fade_sec if len(clips) > 1 and opts.fade_sec > 0 else 0
    final_v = concatenate_videoclips(clips, method="compose", padding=pad)

    video_path = work_dir / "video_noaudio.mp4"
    voice_path = work_dir / "voice.mp3"

    final_v.write_videofile(
        str(video_path),
        fps=opts.fps,
        codec="libx264",
        audio=False,
        preset="medium",
        threads=4,
        logger=None,
    )

    voice = concatenate_audioclips(voice_tracks).set_fps(44100)
    voice.write_audiofile(str(voice_path), logger=None)
    voice.close()

    for c in clips:
        c.close()
    final_v.close()

    return video_path, voice_path


def mix_voice_and_music(
    voice_path: Path,
    music_path: Path | None,
    music_volume: float,
    out_path: Path,
) -> Path:
    voice = AudioFileClip(str(voice_path))
    if not music_path:
        voice.write_audiofile(str(out_path), logger=None)
        voice.close()
        return out_path

    music = AudioFileClip(str(music_path)).volumex(music_volume)
    if music.duration < voice.duration:
        from moviepy.editor import concatenate_audioclips

        loops = int(voice.duration / music.duration) + 1
        music = concatenate_audioclips([music] * loops)
    music = music.subclip(0, voice.duration)
    mixed = CompositeAudioClip([music, voice])
    mixed.write_audiofile(str(out_path), logger=None)
    mixed.close()
    music.close()
    voice.close()
    return out_path


def mux_final(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    *,
    fps: int,
) -> Path:
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
    num = max(len(image_paths), 1)
    segments = split_script_scenes(script, num)

    if image_paths:
        if len(image_paths) != len(segments):
            raise ValueError(
                f"이미지 {len(image_paths)}장과 스크립트 구간 {len(segments)}개가 맞지 않습니다."
            )
        imgs: list[Path | None] = list(image_paths)
    else:
        if not default_image:
            raise ValueError("이미지가 없습니다. --background-image 또는 --scene-dir 이 필요합니다.")
        imgs = [default_image] * len(segments)

    wd = work_dir or (output.parent / f".work_{output.stem}")
    wd.mkdir(parents=True, exist_ok=True)

    scenes = build_scenes(segments, imgs, wd, opts)
    video_path, voice_path = compose_video(
        scenes,
        opts,
        default_image=default_image or (imgs[0] if imgs else None),
        work_dir=wd,
    )

    audio_mixed = wd / "audio_mixed.mp3"
    mix_voice_and_music(voice_path, opts.music_path, opts.music_volume, audio_mixed)
    return mux_final(video_path, audio_mixed, output, fps=opts.fps)
