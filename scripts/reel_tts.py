"""TTS: edge-tts(기본) / gTTS(선택)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reel_progress import ProgressReporter

DEFAULT_EDGE_VOICE = "ko-KR-InJoonNeural"


def list_edge_voices_korean() -> list[dict[str, str]]:
    import edge_tts

    voices = asyncio.run(edge_tts.list_voices())
    return [
        v
        for v in voices
        if str(v.get("Locale", "")).lower().startswith("ko")
    ]


async def _edge_save(
    text: str,
    out_path: Path,
    *,
    voice: str,
    rate: str,
) -> None:
    import edge_tts

    out_path.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out_path))


def synthesize_edge(
    text: str,
    out_path: Path,
    *,
    voice: str = DEFAULT_EDGE_VOICE,
    rate: str = "+0%",
) -> None:
    asyncio.run(_edge_save(text, out_path, voice=voice, rate=rate))


def synthesize_gtts(
    text: str,
    out_path: Path,
    *,
    lang: str,
    slow: bool,
) -> None:
    from gtts import gTTS

    out_path.parent.mkdir(parents=True, exist_ok=True)
    gTTS(text=text, lang=lang, slow=slow).save(str(out_path))


def synthesize(
    text: str,
    out_path: Path,
    *,
    engine: str,
    edge_voice: str,
    edge_rate: str,
    gtts_lang: str,
    gtts_slow: bool,
) -> None:
    if engine == "edge":
        synthesize_edge(text, out_path, voice=edge_voice, rate=edge_rate)
    elif engine == "gtts":
        synthesize_gtts(text, out_path, lang=gtts_lang, slow=gtts_slow)
    else:
        raise ValueError(f"지원하지 않는 TTS 엔진: {engine}")


def synthesize_scenes(
    segments: list[str],
    work_dir: Path,
    *,
    engine: str,
    edge_voice: str,
    edge_rate: str,
    gtts_lang: str,
    gtts_slow: bool,
    progress: ProgressReporter | None = None,
) -> list[Path]:
    paths: list[Path] = []
    n = len(segments)
    for i, text in enumerate(segments):
        if progress:
            progress.begin_stage(0, f"씬 {i + 1}/{n}")
        out = work_dir / f"scene_{i:02d}.mp3"
        synthesize(
            text,
            out,
            engine=engine,
            edge_voice=edge_voice,
            edge_rate=edge_rate,
            gtts_lang=gtts_lang,
            gtts_slow=gtts_slow,
        )
        paths.append(out)
        if progress:
            progress.stage_fraction(0, (i + 1) / n, f"씬 {i + 1}/{n}")
    if progress:
        progress.finish_stage(0)
    return paths
