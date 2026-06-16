#!/usr/bin/env python3
"""
HeyGen API로 이미지(토킹 포토) + AI 보이스(TTS) 기반 세로형(릴스) 영상을 자동 생성합니다.

필수 환경 변수: HEYGENAI_API_KEY (또는 HEYGEN_API_KEY)

선택 환경 변수: HEYGEN_AVATAR_ID — HeyGen 토킹 포토 ID(talking_photo_id).
  create-reel 에서 --talking-photo-id 를 생략하면 이 값을 사용합니다.
  (`python scripts/heygen_reel.py list-talking-photos` 로 확인)

사용 예:
  pip install -r scripts/requirements-heygen.txt
  export HEYGENAI_API_KEY=...
  python scripts/heygen_reel.py list-voices --lang Korean
  python scripts/heygen_reel.py list-talking-photos
  python scripts/heygen_reel.py create-reel \\
    --face-image ./portrait.jpg \\
    --script-file ./script.txt \\
    --voice-id <voice_id> \\
    --background-image ./site.jpg

  # 여러 장 본인 사진을 배경 씬으로 (스크립트는 --- 로 구간 나눔, 구간 수 = 이미지 수)
  python scripts/heygen_reel.py create-reel \\
    --script-file ./reel.txt --voice-id <voice_id> \\
    --scene-dir ./data/260513_순천만

문서: https://docs.heygen.com/ (v2 업로드,포토 아바타,/v2/video/generate)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

API_BASE = "https://api.heygen.com"
UPLOAD_BASE = "https://upload.heygen.com"


def _api_key() -> str:
    key = os.environ.get("HEYGENAI_API_KEY") or os.environ.get("HEYGEN_API_KEY")
    if not key:
        print(
            "환경 변수 HEYGENAI_API_KEY(또는 HEYGEN_API_KEY)가 필요합니다.",
            file=sys.stderr,
        )
        sys.exit(1)
    return key.strip()


def _headers_json() -> dict[str, str]:
    return {"x-api-key": _api_key(), "Content-Type": "application/json"}


def _headers_upload(content_type: str) -> dict[str, str]:
    return {"X-API-KEY": _api_key(), "Content-Type": content_type}


def _raise_for_heygen(resp: requests.Response, ctx: str) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        body = resp.text[:2000]
        raise RuntimeError(f"{ctx} HTTP {resp.status_code}: {body}") from e


def upload_image(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        ct = "image/jpeg"
    elif suffix == ".png":
        ct = "image/png"
    else:
        raise ValueError("이미지는 .jpg, .jpeg, .png 만 지원합니다.")

    data = path.read_bytes()
    r = requests.post(
        f"{UPLOAD_BASE}/v1/asset",
        headers=_headers_upload(ct),
        data=data,
        timeout=120,
    )
    _raise_for_heygen(r, "Upload Asset")
    payload = r.json()
    if payload.get("code") != 100:
        raise RuntimeError(f"Upload Asset 실패: {payload}")
    return payload["data"]


def create_photo_avatar_group(name: str, image_key: str) -> dict[str, Any]:
    r = requests.post(
        f"{API_BASE}/v2/photo_avatar/avatar_group/create",
        headers=_headers_json(),
        json={"name": name, "image_key": image_key},
        timeout=60,
    )
    _raise_for_heygen(r, "Create Photo Avatar Group")
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"Create Photo Avatar Group: {body['error']}")
    return body["data"]


def train_status(group_id: str) -> str:
    r = requests.get(
        f"{API_BASE}/v2/photo_avatar/train/status/{group_id}",
        headers={"x-api-key": _api_key()},
        timeout=30,
    )
    _raise_for_heygen(r, "Train status")
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"Train status: {body['error']}")
    return str(body["data"]["status"])


def wait_train_ready(group_id: str, poll_sec: float, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        st = train_status(group_id)
        if st == "ready":
            return
        if st in ("failed", "moderation_rejected"):
            raise RuntimeError(f"포토 아바타 학습 실패 상태: {st}")
        time.sleep(poll_sec)
    raise TimeoutError("포토 아바타 학습 대기 시간 초과")


def list_talking_photos() -> list[dict[str, Any]]:
    r = requests.get(
        f"{API_BASE}/v2/avatars",
        headers={"x-api-key": _api_key()},
        timeout=60,
    )
    _raise_for_heygen(r, "List avatars")
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"List avatars: {body['error']}")
    return list(body["data"].get("talking_photos") or [])


def resolve_talking_photo_id(
    avatar_name: str, retries: int = 24, delay_sec: float = 5.0
) -> str:
    """학습 직후 목록 반영이 지연될 수 있어 잠시 재시도합니다."""
    for _ in range(retries):
        for tp in list_talking_photos():
            if tp.get("talking_photo_name") == avatar_name:
                return str(tp["talking_photo_id"])
        time.sleep(delay_sec)
    raise RuntimeError(
        f"talking_photo_name='{avatar_name}' 항목을 /v2/avatars 에서 찾지 못했습니다."
    )


def list_voices() -> list[dict[str, Any]]:
    r = requests.get(
        f"{API_BASE}/v2/voices",
        headers={"x-api-key": _api_key()},
        timeout=60,
    )
    _raise_for_heygen(r, "List voices")
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"List voices: {body['error']}")
    return list(body["data"].get("voices") or [])


def _images_sorted_from_dir(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise ValueError(f"폴더가 아닙니다: {directory}")
    out: list[Path] = []
    for p in directory.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            out.append(p)
    return sorted(out, key=lambda x: x.name.lower())


def _collect_scene_image_paths(ns: argparse.Namespace) -> list[Path]:
    """--scene-image 를 명시한 순서가 있으면 그것만, 없으면 --scene-dir 목록."""
    paths: list[Path] = []
    raw = getattr(ns, "scene_images", None) or []
    for s in raw:
        paths.append(Path(s).expanduser().resolve())
    if paths:
        return paths
    sd = getattr(ns, "scene_dir", None)
    if sd:
        return _images_sorted_from_dir(Path(sd).expanduser().resolve())
    return []


def _split_script_scenes(script: str, num_scenes: int) -> list[str]:
    """
    num_scenes == 1 이면 전체를 한 씬.
    그 외에는 빈 줄 위아래의 --- 구분선으로만 나눔(구간 수 == num_scenes 이어야 함).
    """
    text = script.strip()
    if num_scenes < 1:
        raise ValueError("num_scenes >= 1")
    if num_scenes == 1:
        return [text]
    parts = re.split(r"(?:\r?\n)\s*---\s*(?:\r?\n)", text)
    segs = [p.strip() for p in parts if p.strip()]
    if len(segs) != num_scenes:
        raise ValueError(
            f"배경 이미지가 {num_scenes}장일 때, 스크립트를 줄바꿈으로 둘러싼 '---' 로 "
            f"정확히 {num_scenes}개 구간으로 나눠 주세요. (현재 유효 구간: {len(segs)}개)"
        )
    return segs


def generate_reel_video(
    *,
    title: str,
    talking_photo_id: str,
    voice_id: str,
    scenes: list[tuple[str, dict[str, Any] | None]],
    width: int,
    height: int,
    caption: bool,
    locale: str | None,
) -> str:
    """
    scenes: (씬별 나레이션 텍스트, 배경 dict 또는 None 이면 단색)
    HeyGen video_inputs 는 최대 50개.
    """
    if not scenes:
        raise ValueError("씬이 비었습니다.")
    if len(scenes) > 50:
        raise ValueError("HeyGen video_inputs 는 최대 50개입니다.")

    video_inputs: list[dict[str, Any]] = []
    for script, background in scenes:
        voice_block: dict[str, Any] = {
            "type": "text",
            "voice_id": voice_id,
            "input_text": script,
            "speed": 1.0,
        }
        if locale:
            voice_block["locale"] = locale
        scene: dict[str, Any] = {
            "character": {
                "type": "talking_photo",
                "talking_photo_id": talking_photo_id,
                "scale": 1.0,
                "talking_style": "stable",
                # 일부 계정/포토는 Avatar III(unlimited) 미지원 → IV 요청
                "use_avatar_iv_model": True,
            },
            "voice": voice_block,
        }
        if background:
            scene["background"] = background
        else:
            scene["background"] = {"type": "color", "value": "#0f172a"}
        video_inputs.append(scene)

    payload = {
        "title": title,
        "caption": caption,
        "dimension": {"width": width, "height": height},
        "video_inputs": video_inputs,
    }
    r = requests.post(
        f"{API_BASE}/v2/video/generate",
        headers=_headers_json(),
        json=payload,
        timeout=120,
    )
    _raise_for_heygen(r, "Video generate")
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"Video generate: {body['error']}")
    return str(body["data"]["video_id"])


def video_status(video_id: str) -> dict[str, Any]:
    r = requests.get(
        f"{API_BASE}/v1/video_status.get",
        headers={"x-api-key": _api_key()},
        params={"video_id": video_id},
        timeout=30,
    )
    _raise_for_heygen(r, "Video status")
    return r.json()


def wait_video_done(video_id: str, poll_sec: float, timeout_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        raw = video_status(video_id)
        if raw.get("code") != 100:
            raise RuntimeError(f"Video status API 오류: {raw}")
        data = raw["data"]
        st = data.get("status")
        if st == "completed":
            return data
        if st == "failed":
            raise RuntimeError(f"영상 렌더 실패: {data.get('error')}")
        time.sleep(poll_sec)
    raise TimeoutError("영상 렌더 대기 시간 초과")


def cmd_list_voices(ns: argparse.Namespace) -> None:
    voices = list_voices()
    lang_sub = (ns.lang or "").lower()
    rows = []
    for v in voices:
        lang = str(v.get("language") or "")
        if lang_sub and lang_sub not in lang.lower():
            continue
        rows.append(v)
    for v in rows:
        print(
            f"{v.get('voice_id')}\t{v.get('language')}\t{v.get('gender')}\t{v.get('name')}"
        )


def cmd_list_talking_photos(_: argparse.Namespace) -> None:
    for tp in list_talking_photos():
        print(
            f"{tp.get('talking_photo_id')}\t{tp.get('talking_photo_name')}"
        )


def cmd_create_reel(ns: argparse.Namespace) -> None:
    script = ns.script
    if ns.script_file:
        script = Path(ns.script_file).read_text(encoding="utf-8")
    if not script or not script.strip():
        raise SystemExit("--script 또는 --script-file 에 내용이 필요합니다.")

    env_avatar = (os.environ.get("HEYGEN_AVATAR_ID") or "").strip()

    if ns.face_image:
        face_path = Path(ns.face_image)
        up = upload_image(face_path)
        image_key = up.get("image_key")
        if not image_key:
            raise RuntimeError(f"업로드 응답에 image_key 없음: {up}")
        avatar_name = ns.avatar_name or f"reel_{int(time.time())}"
        group = create_photo_avatar_group(avatar_name, str(image_key))
        group_id = str(group.get("group_id") or group.get("id"))
        print(f"포토 아바타 그룹 생성: group_id={group_id} (학습 대기 중…)", flush=True)
        wait_train_ready(group_id, ns.poll_train, ns.timeout_train)
        talking_photo_id = resolve_talking_photo_id(avatar_name)
        print(f"talking_photo_id={talking_photo_id}", flush=True)
    elif ns.talking_photo_id:
        talking_photo_id = ns.talking_photo_id.strip()
    elif env_avatar:
        talking_photo_id = env_avatar
        print(f"HEYGEN_AVATAR_ID 사용: talking_photo_id={talking_photo_id}", flush=True)
    else:
        raise SystemExit(
            "토킹 포토가 필요합니다: --face-image 로 새로 만들거나, "
            "--talking-photo-id 또는 환경 변수 HEYGEN_AVATAR_ID 를 설정하세요."
        )

    scene_paths = _collect_scene_image_paths(ns)
    if scene_paths and ns.background_image:
        raise SystemExit(
            "--background-image 와 --scene-dir / --scene-image 는 함께 쓸 수 없습니다. "
            "여러 장이면 scene 쪽만 사용하세요."
        )

    if scene_paths:
        print(f"배경 이미지 {len(scene_paths)}장 업로드,씬 구성 중…", flush=True)
        try:
            segments = _split_script_scenes(script, len(scene_paths))
        except ValueError as e:
            raise SystemExit(str(e)) from e
        scenes: list[tuple[str, dict[str, Any] | None]] = []
        for img_path, seg in zip(scene_paths, segments):
            bg = upload_image(img_path)
            url = bg.get("url")
            if not url:
                raise RuntimeError(f"배경 업로드 응답에 url 없음: {bg} {img_path}")
            scenes.append((seg, {"type": "image", "url": str(url)}))
    else:
        background: dict[str, Any] | None = None
        if ns.background_image:
            bg_path = Path(ns.background_image)
            bg = upload_image(bg_path)
            url = bg.get("url")
            if not url:
                raise RuntimeError(f"배경 업로드 응답에 url 없음: {bg}")
            background = {"type": "image", "url": str(url)}
        try:
            one = _split_script_scenes(script, 1)[0]
        except ValueError as e:
            raise SystemExit(str(e)) from e
        scenes = [(one, background)]

    video_id = generate_reel_video(
        title=ns.title,
        talking_photo_id=talking_photo_id,
        voice_id=ns.voice_id,
        scenes=scenes,
        width=ns.width,
        height=ns.height,
        caption=ns.caption,
        locale=ns.locale,
    )
    print(f"video_id={video_id} (렌더 대기 중…)", flush=True)
    if ns.no_wait_video:
        return
    done = wait_video_done(video_id, ns.poll_video, ns.timeout_video)
    print("완료:", json.dumps(done, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HeyGen 릴스 자동화 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_v = sub.add_parser("list-voices", help="사용 가능한 AI 보이스 목록")
    p_v.add_argument("--lang", help="언어 이름 부분 문자열 필터 (예: Korean)")
    p_v.set_defaults(func=cmd_list_voices)

    p_tp = sub.add_parser("list-talking-photos", help="계정의 토킹 포토 목록")
    p_tp.set_defaults(func=cmd_list_talking_photos)

    p_c = sub.add_parser("create-reel", help="이미지+TTS로 세로 영상 생성")
    p_c.add_argument("--title", default="일잘하는스카이 릴스", help="HeyGen 영상 제목")
    p_c.add_argument(
        "--face-image",
        help="말하게 할 인물 사진(jpg/png). 없으면 --talking-photo-id 필요",
    )
    p_c.add_argument(
        "--talking-photo-id",
        help="이미 등록된 토킹 포토 ID (/v2/avatars). 생략 시 HEYGEN_AVATAR_ID 사용",
    )
    p_c.add_argument(
        "--avatar-name",
        help="포토 아바타 생성 시 이름(목록에서 매칭). 기본: reel_<timestamp>",
    )
    p_c.add_argument(
        "--background-image",
        help="배경 정지 이미지 1장(단일 씬). 여러 장은 --scene-dir 또는 --scene-image",
    )
    p_c.add_argument(
        "--scene-dir",
        help="폴더 안 jpg/jpeg/png 를 파일명 순으로 배경 씬에 사용(스크립트는 --- 로 같은 개수 구간)",
    )
    p_c.add_argument(
        "--scene-image",
        action="append",
        dest="scene_images",
        metavar="PATH",
        help="배경 이미지 경로. 여러 번 주면 그 순서대로 씬( --scene-dir 보다 우선 )",
    )
    p_c.add_argument("--script", help="나레이션 텍스트")
    p_c.add_argument("--script-file", help="나레이션 텍스트 파일 경로")
    p_c.add_argument("--voice-id", required=True, help="HeyGen voice_id")
    p_c.add_argument(
        "--locale",
        help="다국어 보이스용 로케일(예: ko-KR). List All Locales API 참고",
    )
    p_c.add_argument("--width", type=int, default=1080)
    p_c.add_argument("--height", type=int, default=1920)
    p_c.add_argument("--caption", action="store_true", help="자막 생성")
    p_c.add_argument("--poll-train", type=float, default=5.0)
    p_c.add_argument("--timeout-train", type=float, default=600.0)
    p_c.add_argument("--poll-video", type=float, default=5.0)
    p_c.add_argument("--timeout-video", type=float, default=1800.0)
    p_c.add_argument(
        "--no-wait-video",
        action="store_true",
        help="video_id만 받고 종료(상태는 대시보드에서 확인)",
    )
    p_c.set_defaults(func=cmd_create_reel)

    return p


def main() -> None:
    parser = build_parser()
    ns = parser.parse_args()
    ns.func(ns)


if __name__ == "__main__":
    main()
