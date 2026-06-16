"""
릴스 렌더 공통 기본값.

CLI(`make_reel.py`)와 `BuildOptions`(`reel_builder.py`)에서 같은 상수를 쓰므로,
기본값을 바꿀 때는 이 파일만 수정하면 됩니다.
"""

# --- 해상도,영상 ---
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
DEFAULT_FADE_SEC = 0.4
DEFAULT_PAD_SEC = 0.35
DEFAULT_KEN_BURNS = 0.04

# --- 배경음 믹스 (0~1) ---
DEFAULT_MUSIC_VOLUME = 0.045

# --- 나레이션 자막 (--subtitle 켠 경우에만 표시) ---
# 1080 기준 pt. 실제 출력은 DEFAULT_ONSCREEN_FONT_SCALE 이 곱해짐.
DEFAULT_SUBTITLE_MAX_CHARS = 10
DEFAULT_SUBTITLE_FONT_SIZE = 100

# --- 하단 고정 푸터 (브랜드,문의, 기본 항상 표시) ---
# 나레이션 자막과 별개. "자막"이 안 커 보이면 대부분 이 블록 크기.
DEFAULT_FOOTER_FONT_SIZE = 78

# 화면에 그릴 때 글자 pt에 곱하는 배율 (1.0 = 설정값 그대로, 1.2면 20% 더 크게)
DEFAULT_ONSCREEN_FONT_SCALE = 1.22
# 푸터 바: 화면 아래에서 이 px만큼 위에 배치 (클수록 위로)
DEFAULT_FOOTER_BOTTOM_MARGIN = 96
# 푸터와 나레이션 자막 사이 간격
DEFAULT_SUBTITLE_FOOTER_GAP = 36
# 자막만 있을 때 화면 아래 여백
DEFAULT_SUBTITLE_BOTTOM_MARGIN = 100
