#!/usr/bin/env python3
"""
일잘하는스카이 현장 사진 → Cloudflare R2 업로드.

data/YYMMDD_지역/ 폴더의 사진을 정리한 뒤 R2에 올리고,
웹 갤러리용 manifest.json 을 생성합니다.

사용 예:
  python scripts/upload_to_r2.py                   # 정리 + 업로드 + manifest (기본)
  python scripts/upload_to_r2.py organize          # 카카오톡 파일명 → 01.jpg 정리
  python scripts/upload_to_r2.py upload --dry-run  # 업로드 대상 확인
  python scripts/upload_to_r2.py sync              # 위와 동일 (명시적)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from env_loader import get_env_loader
from gallery_utils import (
    IMAGE_EXTENSIONS,
    build_manifest,
    default_data_dir,
    is_image,
    organize_all,
    write_manifest,
)


@dataclass
class UploadResult:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def get_content_type(file_path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(file_path))
    return content_type or "application/octet-stream"


def make_r2_client(account_id: str, access_key_id: str, secret_access_key: str):
    endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def remote_hash(client, bucket: str, key: str) -> Optional[str]:
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        # HeadObject 권한이 없는 토큰은 중복 검사 생략 후 업로드 시도
        if code in {"403", "AccessDenied", "Forbidden"}:
            return None
        raise
    metadata = response.get("Metadata", {})
    return metadata.get("sha256")


def format_client_error(e: ClientError) -> str:
    err = e.response.get("Error", {})
    code = err.get("Code", "Unknown")
    message = err.get("Message", str(e))
    return f"{code}: {message}"


def verify_r2_access(client, bucket: str, key_prefix: str) -> Optional[str]:
    """업로드 전 R2 연결,권한 확인. 문제 있으면 안내 메시지 반환."""
    test_key = f"{key_prefix.strip('/')}/.connection_test"
    try:
        client.put_object(
            Bucket=bucket,
            Key=test_key,
            Body=b"ok",
            ContentType="text/plain",
        )
        client.delete_object(Bucket=bucket, Key=test_key)
        return None
    except ClientError as e:
        detail = format_client_error(e)
        return (
            f"R2 접근 실패 ({detail})\n\n"
            f"버킷 '{bucket}' 에 쓰기 권한이 없거나 설정이 맞지 않습니다.\n"
            "Cloudflare 대시보드에서 아래를 확인해 주세요.\n\n"
            "1. R2 → 버킷 '{bucket}' 이 이 계정(CF_R2_ACCOUNT_ID)에 있는지\n"
            "2. R2 → Manage R2 API Tokens → 새 토큰 생성\n"
            "   - 권한: Object Read & Write\n"
            "   - 범위: 해당 버킷(또는 전체 R2)\n"
            "3. .env 의 CF_R2_ACCOUNT_ID / ACCESS_KEY / SECRET / BUCKET 갱신\n"
            "4. (선택) Public bucket URL → CF_R2_PUBLIC_URL\n\n"
            "다른 블로그용 토큰,버킷을 그대로 썼다면, 일잘하는스카이용 버킷/토큰인지 확인하세요."
        )


def upload_one(
    client,
    bucket: str,
    local_file: Path,
    key: str,
    cache_control: str,
    overwrite: bool,
    dry_run: bool,
) -> str:
    local_hash = sha256_file(local_file)

    if dry_run:
        return "uploaded"

    if not overwrite:
        server_hash = remote_hash(client, bucket, key)
        if server_hash and server_hash == local_hash:
            return "skipped"

    content_type = get_content_type(local_file)
    with local_file.open("rb") as f:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=f,
            ContentType=content_type,
            CacheControl=cache_control,
            Metadata={"sha256": local_hash},
        )
    return "uploaded"


def iter_gallery_uploads(data_dir: Path, key_prefix: str) -> Iterable[tuple[Path, str]]:
    prefix = key_prefix.strip("/")
    for album_dir in sorted(data_dir.iterdir()):
        if not album_dir.is_dir() or album_dir.name.startswith("."):
            continue
        for image in sorted(album_dir.iterdir(), key=lambda p: p.name.lower()):
            if not is_image(image):
                continue
            key = f"{prefix}/{album_dir.name}/{image.name}" if prefix else f"{album_dir.name}/{image.name}"
            yield image, key


def load_r2_config(args: argparse.Namespace) -> tuple[dict[str, str], Optional[int]]:
    env = get_env_loader()
    config = {
        "account_id": env.get("CF_R2_ACCOUNT_ID", ""),
        "access_key_id": env.get("CF_R2_ACCESS_KEY_ID", ""),
        "secret_access_key": env.get("CF_R2_SECRET_ACCESS_KEY", ""),
        "bucket": args.bucket or env.get("CF_R2_BUCKET", ""),
        "public_base_url": getattr(args, "public_url", "") or env.get("CF_R2_PUBLIC_URL", ""),
    }

    missing = [k for k, v in {
        "CF_R2_ACCOUNT_ID": config["account_id"],
        "CF_R2_ACCESS_KEY_ID": config["access_key_id"],
        "CF_R2_SECRET_ACCESS_KEY": config["secret_access_key"],
        "CF_R2_BUCKET": config["bucket"],
    }.items() if not v]

    if missing:
        print("❌ R2 업로드 필수 환경변수가 없습니다:")
        for key in missing:
            print(f"  - {key}")
        print("\n💡 .env.example의 R2 설정 항목을 참고해 .env를 채워주세요.")
        return config, 1

    return config, None


def cmd_organize(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    if not data_dir.is_dir():
        print(f"❌ data 디렉토리를 찾을 수 없습니다: {data_dir}")
        return 1

    summary = organize_all(data_dir, dry_run=args.dry_run)
    if not summary:
        print("✅ 정리할 파일이 없습니다. (이미 01.jpg 형식이거나 사진 없음)")
        return 0

    mode = "dry-run" if args.dry_run else "완료"
    print(f"📁 파일명 정리 {mode}: {len(summary)}개 앨범")
    for album_id, moves in summary.items():
        print(f"\n  [{album_id}]")
        for src, dst in moves:
            print(f"    {src} → {dst}")

    if args.dry_run:
        print("\n💡 실제 적용: python scripts/upload_to_r2.py organize")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    config, err = load_r2_config(args)
    if err:
        return err

    client = make_r2_client(
        config["account_id"],
        config["access_key_id"],
        config["secret_access_key"],
    )
    print(f"🔍 R2 연결 확인: bucket={config['bucket']}")
    message = verify_r2_access(client, config["bucket"], args.key_prefix)
    if message:
        print(f"❌ {message}")
        return 1

    print("✅ R2 연결 및 업로드 권한 정상")
    if not config["public_base_url"]:
        print("⚠️ CF_R2_PUBLIC_URL 이 비어 있습니다. manifest URL 생성 시 필요합니다.")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    config, err = load_r2_config(args)
    if err:
        return err

    data_dir = Path(args.data_dir).resolve()
    if not data_dir.is_dir():
        print(f"❌ data 디렉토리를 찾을 수 없습니다: {data_dir}")
        return 1

    uploads = list(iter_gallery_uploads(data_dir, args.key_prefix))
    if not uploads:
        print(f"⚠️ 업로드할 이미지가 없습니다: {data_dir}")
        return 0

    client = make_r2_client(
        config["account_id"],
        config["access_key_id"],
        config["secret_access_key"],
    )

    if not args.dry_run and not getattr(args, "skip_verify", False):
        print("🔍 R2 연결 확인 중...")
        message = verify_r2_access(client, config["bucket"], args.key_prefix)
        if message:
            print(f"❌ {message}")
            return 1
        print("✅ R2 연결 OK")

    result = UploadResult()

    print(f"🚀 업로드 시작: {len(uploads)}개 파일")
    print(f"   버킷: {config['bucket']}")
    print(f"   source: {data_dir}")
    print(f"   prefix: {args.key_prefix}")
    if args.dry_run:
        print("   모드: dry-run")

    for idx, (local_file, key) in enumerate(uploads, start=1):
        try:
            status = upload_one(
                client=client,
                bucket=config["bucket"],
                local_file=local_file,
                key=key,
                cache_control=args.cache_control,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
            if status == "uploaded":
                result.uploaded += 1
                icon = "⬆️"
            else:
                result.skipped += 1
                icon = "⏭️"
            print(f"[{idx}/{len(uploads)}] {icon} {key}")
        except ClientError as e:
            result.failed += 1
            print(f"[{idx}/{len(uploads)}] ❌ {key} - {format_client_error(e)}")
        except Exception as e:
            result.failed += 1
            print(f"[{idx}/{len(uploads)}] ❌ {key} - {e}")

    print("\n📊 업로드 결과")
    print(f"  uploaded: {result.uploaded}")
    print(f"  skipped : {result.skipped}")
    print(f"  failed  : {result.failed}")

    if args.write_manifest:
        manifest = build_manifest(
            data_dir=data_dir,
            key_prefix=args.key_prefix,
            public_base_url=config["public_base_url"],
        )
        manifest_path = Path(args.manifest_path).resolve()
        if not args.dry_run:
            write_manifest(manifest, manifest_path)
            manifest_key = f"{args.key_prefix.strip('/')}/manifest.json"
            try:
                upload_one(
                    client=client,
                    bucket=config["bucket"],
                    local_file=manifest_path,
                    key=manifest_key,
                    cache_control="public, max-age=300",
                    overwrite=True,
                    dry_run=False,
                )
                print(f"\n📄 manifest: {manifest_path}")
                if config["public_base_url"]:
                    print(f"   URL: {config['public_base_url'].rstrip('/')}/{manifest_key}")
            except Exception as e:
                print(f"\n⚠️ manifest 업로드 실패: {e}")
        else:
            print(f"\n📄 manifest (dry-run): {manifest_path}")
            print(f"   앨범 {len(manifest.albums)}개")

    return 2 if result.failed else 0


def cmd_sync(args: argparse.Namespace) -> int:
    if not args.skip_organize:
        organize_args = argparse.Namespace(
            data_dir=args.data_dir,
            dry_run=args.dry_run,
        )
        code = cmd_organize(organize_args)
        if code != 0:
            return code

    return cmd_upload(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="data/ 현장 사진을 정리하고 Cloudflare R2에 업로드합니다.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(default_data_dir()),
        help="현장 사진 루트 (기본값: data/)",
    )

    sub = parser.add_subparsers(dest="command")

    organize = sub.add_parser("organize", help="카카오톡 파일명을 01.jpg 형식으로 정리")
    organize.add_argument("--dry-run", action="store_true", help="변경 없이 미리보기")
    organize.set_defaults(func=cmd_organize)

    upload = sub.add_parser("upload", help="R2에 업로드")
    upload.add_argument(
        "--key-prefix",
        default="gallery",
        help="R2 Object Key prefix (기본값: gallery → gallery/260520_광양중마동/01.jpg)",
    )
    upload.add_argument("--bucket", default="", help="R2 버킷명 (미지정 시 CF_R2_BUCKET)")
    upload.add_argument(
        "--public-url",
        default="",
        help="공개 URL 베이스 (미지정 시 CF_R2_PUBLIC_URL, manifest URL 생성용)",
    )
    upload.add_argument(
        "--cache-control",
        default="public, max-age=31536000, immutable",
        help="Cache-Control 헤더",
    )
    upload.add_argument("--overwrite", action="store_true", help="동일 파일도 강제 덮어쓰기")
    upload.add_argument("--dry-run", action="store_true", help="실제 업로드 없이 대상만 출력")
    upload.add_argument("--skip-verify", action="store_true", help="업로드 전 R2 연결 확인 생략")
    upload.add_argument(
        "--write-manifest",
        action="store_true",
        default=True,
        help="gallery/manifest.json 생성 및 업로드 (기본: 켜짐)",
    )
    upload.add_argument(
        "--no-write-manifest",
        action="store_false",
        dest="write_manifest",
        help="manifest 생성 생략",
    )
    upload.add_argument(
        "--manifest-path",
        default="output/gallery/manifest.json",
        help="로컬 manifest 저장 경로",
    )
    upload.set_defaults(func=cmd_upload)

    sync = sub.add_parser("sync", help="organize + upload + manifest (일괄 실행)")
    sync.add_argument("--key-prefix", default="gallery")
    sync.add_argument("--bucket", default="")
    sync.add_argument("--public-url", default="")
    sync.add_argument(
        "--cache-control",
        default="public, max-age=31536000, immutable",
    )
    sync.add_argument("--overwrite", action="store_true")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--skip-verify", action="store_true")
    sync.add_argument("--skip-organize", action="store_true", help="파일명 정리 단계 생략")
    sync.add_argument("--write-manifest", action="store_true", default=True)
    sync.add_argument("--no-write-manifest", action="store_false", dest="write_manifest")
    sync.add_argument("--manifest-path", default="output/gallery/manifest.json")
    sync.set_defaults(func=cmd_sync)

    verify = sub.add_parser("verify", help="R2 연결,업로드 권한만 확인")
    verify.add_argument("--bucket", default="")
    verify.add_argument("--key-prefix", default="gallery")
    verify.set_defaults(func=cmd_verify)

    return parser


def main() -> int:
    # 서브커맨드 생략 시 sync(정리+업로드+manifest) 실행
    known_commands = {"organize", "upload", "sync", "verify"}
    if len(sys.argv) == 1 or (
        sys.argv[1] not in known_commands and sys.argv[1] not in ("-h", "--help")
    ):
        sys.argv.insert(1, "sync")

    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):
        print("사용법: python scripts/upload_to_r2.py [organize|upload|sync] [옵션]")
        print("  (서브커맨드 생략 시 sync)")
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
