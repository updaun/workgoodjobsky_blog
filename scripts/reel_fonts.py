"""한글 자막 폰트 탐색·검증·(필요 시) 다운로드."""

from __future__ import annotations

import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_FONT = _REPO_ROOT / "assets" / "fonts" / "NotoSansKR-Bold.otf"
NOTO_DOWNLOAD_URL = (
    "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/Korean/NotoSansCJK-Bold.otf"
)

# 한글 미지원 폰트(자막 깨짐 원인) — 후보에서 제외
_EXCLUDE_NAMES = ("dejavu", "liberation", "ubuntu", "droid", "freefont")

_SYSTEM_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansKR-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansKR-Bold.otf",
    "/mnt/c/Windows/Fonts/malgun.ttf",
    "/mnt/c/Windows/Fonts/malgunbd.ttf",
]


def _load_font(path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """ttc 는 index 0 으로 로드."""
    try:
        return ImageFont.truetype(str(path), size, index=0)
    except OSError:
        return ImageFont.truetype(str(path), size)


def _renders_hangul(font_path: Path, size: int = 32) -> bool:
    try:
        font = _load_font(font_path, size)
        probe = "일잘하는스카이 현장"
        img = Image.new("RGB", (800, 120), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), probe, font=font)
        width = bbox[2] - bbox[0]
        if width < 40:
            return False
        # tofu(□) 비율: 픽셀 분산이 너무 작으면 깨진 것으로 간주
        draw.text((10, 10), probe, font=font, fill=(0, 0, 0))
        gray = img.convert("L")
        hist = gray.histogram()
        black_px = sum(hist[:40])
        return black_px > 200
    except OSError:
        return False


def _iter_candidates(explicit: Path | None) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []

    def add(p: Path) -> None:
        r = p.expanduser().resolve()
        if r.is_file() and r not in seen:
            seen.add(r)
            out.append(r)

    if explicit:
        add(explicit)
    if BUNDLED_FONT.is_file():
        add(BUNDLED_FONT)
    for c in _SYSTEM_CANDIDATES:
        add(Path(c))
    fonts_dir = _REPO_ROOT / "assets" / "fonts"
    if fonts_dir.is_dir():
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            for p in sorted(fonts_dir.glob(ext)):
                add(p)
    return out


def download_bundled_font(dest: Path | None = None, *, quiet: bool = False) -> Path:
    target = dest or BUNDLED_FONT
    target.parent.mkdir(parents=True, exist_ok=True)
    if not quiet:
        print(f"한글 폰트 다운로드 중 → {target}", flush=True)
    urllib.request.urlretrieve(NOTO_DOWNLOAD_URL, target)
    return target


def resolve_font(explicit: Path | None, *, allow_download: bool = True) -> Path:
    for cand in _iter_candidates(explicit):
        name = cand.name.lower()
        if any(x in name for x in _EXCLUDE_NAMES):
            continue
        if _renders_hangul(cand):
            return cand

    if allow_download and not BUNDLED_FONT.is_file():
        try:
            download_bundled_font(BUNDLED_FONT)
            if _renders_hangul(BUNDLED_FONT):
                return BUNDLED_FONT
        except OSError as e:
            raise FileNotFoundError(
                "한글 자막 폰트를 찾거나 받지 못했습니다. "
                "sudo apt install fonts-nanum 또는 --font 경로를 지정하세요."
            ) from e

    raise FileNotFoundError(
        "한글 자막용 폰트를 찾지 못했습니다.\n"
        "  • sudo apt install fonts-nanum\n"
        "  • 또는 --font /path/to/NanumGothic.ttf\n"
        f"  • 또는 자동 설치: {BUNDLED_FONT}"
    )
