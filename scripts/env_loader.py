#!/usr/bin/env python3
"""
환경변수 로더 유틸리티

.env 파일을 읽어서 환경변수로 로드하는 유틸리티
"""

import os
from pathlib import Path
from typing import Optional, Dict


class EnvLoader:
    """환경변수 로더"""
    
    def __init__(self, env_path: Optional[str] = None):
        if env_path:
            self.env_path = Path(env_path)
        else:
            script_dir = Path(__file__).resolve().parent
            project_root = script_dir.parent
            # 프로젝트 루트 → scripts/ 순으로 .env 탐색
            for candidate in (project_root / ".env", script_dir / ".env"):
                if candidate.exists():
                    self.env_path = candidate
                    break
            else:
                self.env_path = project_root / ".env"
        
        self.env_vars = {}
        self.load_env()
    
    def load_env(self):
        """환경변수 파일 로드"""
        if not self.env_path.exists():
            print(f"⚠️ .env 파일이 없습니다: {self.env_path}")
            print("💡 .env.example을 .env로 복사하고 API 키를 설정하세요.")
            return
        
        try:
            with open(self.env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line in lines:
                line = line.strip()
                
                # 주석이나 빈 줄 건너뛰기
                if not line or line.startswith('#'):
                    continue
                
                # KEY=VALUE 형태 파싱
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # 따옴표 제거
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    
                    # 환경변수에 설정
                    os.environ[key] = value
                    self.env_vars[key] = value
            
            print(f"✅ 환경변수 로드 완료: {len(self.env_vars)}개")
            
        except Exception as e:
            print(f"❌ 환경변수 로드 실패: {e}")
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """환경변수 값 가져오기"""
        return os.getenv(key, default)
    
    def get_int(self, key: str, default: int = 0) -> int:
        """정수형 환경변수 값 가져오기"""
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """불린형 환경변수 값 가져오기"""
        value = os.getenv(key, '').lower()
        if value in ('true', '1', 'yes', 'on'):
            return True
        elif value in ('false', '0', 'no', 'off'):
            return False
        return default
    
    def check_required_keys(self, required_keys: list) -> Dict[str, bool]:
        """필수 환경변수 확인"""
        status = {}
        for key in required_keys:
            value = self.get(key)
            is_set = bool(value and value != f'your_{key.lower()}_here')
            status[key] = is_set
        
        return status
    
    def print_status(self):
        """환경변수 상태 출력"""
        api_keys = [
            ('UNSPLASH_ACCESS_KEY', 'Unsplash API'),
            ('PEXELS_API_KEY', 'Pexels API'),
            ('PIXABAY_API_KEY', 'Pixabay API')
        ]
        
        print("\n📋 API 키 설정 상태:")
        for key, description in api_keys:
            value = self.get(key)
            if value and value != f'your_{key.lower()}_here':
                status = "✅ 설정됨"
            else:
                status = "❌ 미설정"
            print(f"  {key}: {status} - {description}")
        
        print(f"\n🔧 설정값:")
        print(f"  이미지 품질: {self.get_int('IMAGE_QUALITY', 85)}")
        print(f"  이미지 크기: {self.get_int('IMAGE_WIDTH', 1200)}x{self.get_int('IMAGE_HEIGHT', 630)}")
        print(f"  캐시 만료: {self.get_int('CACHE_EXPIRES_DAYS', 7)}일")


def load_env(env_path: Optional[str] = None) -> EnvLoader:
    """환경변수 로드 함수"""
    return EnvLoader(env_path)


# 전역 인스턴스
_env_loader = None

def get_env_loader() -> EnvLoader:
    """전역 환경변수 로더 인스턴스 반환"""
    global _env_loader
    if _env_loader is None:
        _env_loader = EnvLoader()
    return _env_loader


if __name__ == "__main__":
    # 테스트 및 상태 확인
    loader = EnvLoader()
    loader.print_status()
    
    print("\n💡 설정 방법:")
    print("1. .env.example을 .env로 복사")
    print("2. .env 파일에서 실제 API 키 입력")
    print("3. 스크립트 다시 실행")