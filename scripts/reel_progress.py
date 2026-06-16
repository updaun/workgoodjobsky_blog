"""릴스 렌더 단계별 진행률,경과 시간 표시."""

from __future__ import annotations

import sys
import time
from typing import Callable

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore[misc, assignment]


def format_elapsed(seconds: float) -> str:
    s = int(max(0, seconds))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class ProgressReporter:
    """전체 파이프라인 진행률 (0~100)."""

    _STAGES: tuple[tuple[str, float], ...] = (
        ("TTS 음성 생성", 0.14),
        ("영상 클립 구성", 0.18),
        ("영상 인코딩", 0.44),
        ("음성 믹스", 0.14),
        ("최종 MP4 합성", 0.10),
    )

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled and tqdm is not None
        self._t0 = time.monotonic()
        self._done = 0.0
        self._bar: tqdm | None = None
        self._stage_idx = -1
        if self.enabled:
            self._bar = tqdm(
                total=100,
                unit="%",
                bar_format="{desc} |{bar}| {n:.0f}% [{elapsed} 경과]",
                file=sys.stderr,
                dynamic_ncols=True,
            )
            self._bar.set_description("준비")

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def _refresh_desc(self, detail: str = "") -> None:
        if not self._bar:
            return
        base = ""
        if 0 <= self._stage_idx < len(self._STAGES):
            base = self._STAGES[self._stage_idx][0]
        desc = f"{base} — {detail}" if detail else base
        suffix = f" {format_elapsed(self.elapsed)}"
        self._bar.set_description((desc + suffix)[:80])

    def begin_stage(self, stage_index: int, detail: str = "") -> None:
        self._stage_idx = stage_index
        if not self.enabled:
            if tqdm is None:
                name = self._STAGES[stage_index][0] if stage_index < len(self._STAGES) else "작업"
                print(f"[{stage_index + 1}/{len(self._STAGES)}] {name}… ({format_elapsed(self.elapsed)})", flush=True)
            return
        self._refresh_desc(detail)

    def stage_fraction(self, stage_index: int, fraction: float, detail: str = "") -> None:
        """현재 단계 내 부분 진행 (fraction 0~1)."""
        if stage_index < 0 or stage_index >= len(self._STAGES):
            return
        _, weight = self._STAGES[stage_index]
        target = sum(w for _, w in self._STAGES[:stage_index]) + weight * min(1.0, max(0.0, fraction))
        target_pct = target * 100
        if self._bar:
            delta = target_pct - self._done
            if delta > 0:
                self._bar.update(delta)
            self._done = target_pct
            self._refresh_desc(detail)
        elif fraction >= 1.0 and int(target * 10) % 10 == 0:
            pass

    def finish_stage(self, stage_index: int, detail: str = "완료") -> None:
        self.stage_fraction(stage_index, 1.0, detail)

    def moviepy_logger(self) -> Callable[..., object] | None:
        """moviepy write_* 용 proglog 로거."""
        if not self.enabled:
            return None
        try:
            from proglog import ProgressBarLogger
        except ImportError:
            return None

        stage = 2  # 영상 인코딩
        outer = self

        class _Logger(ProgressBarLogger):  # type: ignore[misc]
            def bars_callback(self, bar, attr, value, old_value=None):
                bar_name = bar if isinstance(bar, str) else getattr(bar, "name", "")
                if bar_name == "t" and attr == "index":
                    total = (self.bars.get(bar_name) or {}).get("total") or 1
                    outer.stage_fraction(
                        stage, value / total, f"프레임 {int(value)}/{int(total)}"
                    )

        return _Logger()

    def close(self, message: str = "완료") -> None:
        if self._bar:
            if self._done < 100:
                self._bar.update(100 - self._done)
            self._bar.set_description(f"{message} ({format_elapsed(self.elapsed)})")
            self._bar.close()
        elif message:
            print(f"{message} — 총 {format_elapsed(self.elapsed)}", flush=True)
