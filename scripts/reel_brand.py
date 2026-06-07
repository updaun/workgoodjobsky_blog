"""일잘하는스카이 릴스 나레이션용 인·아웃트로 (고객 관점·과장 없음)."""

from __future__ import annotations

# AGENTS.md 마케팅 하네스(이득·소통·마무리) 기준.
# make_reel.py 는 출력 파일명 기준으로 아래 목록에서 자동 선택(매 영상 다른 인트로).
# 고정 문구: --intro / --outro 또는 --intro-variant N

BRAND_INTRO_VARIANTS: tuple[str, ...] = (
    "일잘하는스카이입니다. 오늘 현장 영상입니다.",
    "위치 맞춤부터 끝까지, 일잘하는스카이입니다.",
    "현장 소통부터 맞춥니다. 일잘하는스카이입니다.",
    "고소작업차 조종, 일잘하는스카이입니다.",
    "맡기시면 편합니다. 일잘하는스카이입니다.",
    "말 한마디가 작업 속도를 만듭니다. 일잘하는스카이입니다.",
    "고소작업대, 조종이 편해야 합니다. 일잘하는스카이입니다.",
    "오늘도 현장 맞춰 드립니다. 일잘하는스카이입니다.",
)

BRAND_OUTRO_VARIANTS: tuple[str, ...] = (
    "고소작업차 필요하시면 일잘하는스카이로 편하게 연락 주세요.",
    "순천·여수·광양, 전남 현장 맞춰 드립니다.",
    "끝까지 맞춰 드리는 조종, 일잘하는스카이입니다.",
    "현장 소통 잘 되는 조종으로 문의 주세요.",
    "전남스카이·인접 권역, 편하게 연락 주세요.",
    "오늘도 매끄럽게 마무리. 다음 현장도 일잘하는스카이입니다.",
)

# 하위 호환
DEFAULT_BRAND_INTRO = BRAND_INTRO_VARIANTS[0]
DEFAULT_BRAND_OUTRO = BRAND_OUTRO_VARIANTS[0]

# 영상 하단 고정 오버레이 (전 구간 동일)
DEFAULT_FOOTER_LINE1 = "일잘하는스카이"
DEFAULT_FOOTER_LINE2 = "문의 010-6575-5112"


def _pick_variant(variants: tuple[str, ...], seed: str | None, index: int | None) -> str:
    if index is not None:
        if not 0 <= index < len(variants):
            raise IndexError(f"variant index는 0~{len(variants) - 1} 입니다 (받음: {index})")
        return variants[index]
    if not seed:
        return variants[0]
    idx = sum(ord(c) for c in seed) % len(variants)
    return variants[idx]


def pick_brand_intro(seed: str | None = None, *, index: int | None = None) -> str:
    return _pick_variant(BRAND_INTRO_VARIANTS, seed, index)


def pick_brand_outro(seed: str | None = None, *, index: int | None = None) -> str:
    return _pick_variant(BRAND_OUTRO_VARIANTS, seed, index)


def format_brand_catalog() -> str:
    lines = ["=== 인트로 (--intro-variant N) ==="]
    for i, text in enumerate(BRAND_INTRO_VARIANTS):
        lines.append(f"  [{i}] {text}")
    lines.append("")
    lines.append("=== 아웃트로 (--outro-variant N) ===")
    for i, text in enumerate(BRAND_OUTRO_VARIANTS):
        lines.append(f"  [{i}] {text}")
    lines.append("")
    lines.append("미지정 시 --output 파일명으로 자동 선택됩니다.")
    return "\n".join(lines)


def apply_brand_to_segments(
    segments: list[str],
    *,
    enabled: bool,
    intro: str,
    outro: str,
) -> list[str]:
    """
    TTS용으로만 구간 리스트 앞뒤에 브랜드 문구를 붙인다.
    구간이 1개면 한 덩어리로 합침, 여러 개면 첫 구간 앞·마지막 구간 뒤에만 붙임.
    """
    if not enabled:
        return list(segments)
    intro_t = intro.strip()
    outro_t = outro.strip()
    if not intro_t and not outro_t:
        return list(segments)
    if not segments:
        return segments
    parts = [s.strip() for s in segments]
    if len(parts) == 1:
        body = parts[0]
        chunks = [x for x in (intro_t, body, outro_t) if x]
        return [" ".join(chunks)]
    out = list(parts)
    if intro_t:
        out[0] = f"{intro_t} {out[0]}".strip()
    if outro_t:
        out[-1] = f"{out[-1]} {outro_t}".strip()
    return out
