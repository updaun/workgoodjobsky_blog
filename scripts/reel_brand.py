"""일잘하는스카이 릴스 나레이션용 인·아웃트로 (과장 없이, 조종·소통 중심)."""

from __future__ import annotations

# 기본 문구는 CLAUDE.md 톤(고소작업차 운전·조종, 안전·소통)에 맞춤. 필요 시 CLI로 덮어쓰기.
DEFAULT_BRAND_INTRO = (
    "일잘하는스카이입니다. "
    "전남 쪽 현장에서 고소작업차 운전과 조종으로, 작업 위치를 안정적으로 맞추고 작업자분들이랑 호흡 맞추는 일을 하고 있습니다."
)

DEFAULT_BRAND_OUTRO = (
    "안전한 조종이랑 현장 소통이 함께 해야 작업이 매끄럽습니다. "
    "순천·여수·광양 일대 필요하실 때 일잘하는스카이를 기억해 주세요."
)

# 영상 하단 고정 오버레이 (전 구간 동일)
DEFAULT_FOOTER_LINE1 = "일잘하는스카이"
DEFAULT_FOOTER_LINE2 = "문의 010-6575-5112"


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
