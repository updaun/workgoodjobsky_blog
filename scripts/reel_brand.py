"""일잘하는스카이 릴스 나레이션용 인·아웃트로 (고객 관점·과장 없음)."""

from __future__ import annotations

# AGENTS.md 마케팅 하네스(이득·소통·마무리) 기준. 필요 시 CLI --intro / --outro 로 덮어쓰기.
DEFAULT_BRAND_INTRO = (
    "일잘하는스카이입니다. "
    "일을 잘한다는 건, 현장에서 소통이 잘 되는 거라고 생각합니다. "
    "전남에서 고소작업차 조종으로, 노련하고 매끄럽게 작업을 완수합니다."
)

DEFAULT_BRAND_OUTRO = (
    "소통이 맞아야 대기도 줄고, 마무리도 편합니다. "
    "순천·여수·광양 일대 고소작업차 필요하시면, 일을 잘하는 일잘하는스카이로 연락 주세요."
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
