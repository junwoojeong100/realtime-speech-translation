"""
음성 전사(STT) — 로컬 오디오 파일 (Fast Transcription + MAI-Transcribe)

방송 녹음 등 로컬 오디오를 한국어로 '전사'합니다(한국어 음성 → 한국어 텍스트).
기본 모델은 최신 mai-transcribe-1.5이며 task=transcribe로 동작합니다. 기본 소스
언어는 한국어(ko-KR)이고, --translate-to로 번역 모드도 사용할 수 있습니다.

기존 translate_mai_rest.py가 항상 한국어로 '번역'하는 것과 달리, 이 스크립트는
기본이 '전사(말한 언어 그대로 텍스트화)'입니다.

참고: 모델 지정(--model)은 전사 모드에서만 유효합니다. 번역(--translate-to)에는
서비스가 모델 지정을 허용하지 않으므로 기본 모델이 사용됩니다.

Usage:
    # 한국어 뉴스 음성 전사 (기본, model: mai-transcribe-1.5)
    python transcribe_file.py news_ko.wav

    # SRT 자막 파일로 저장
    python transcribe_file.py news_ko.wav --srt news_ko.srt

    # 모델/소스 언어 지정
    python transcribe_file.py clip.wav --model mai-transcribe-1 --locale en-US

    # 전사 대신 번역 모드 (모델 지정은 무시됨)
    python transcribe_file.py foreign.wav --translate-to ko

Prerequisites:
    - pip install -r requirements_transcribe.txt
    - .env에 AZURE_MAI_SPEECH_RESOURCE_ID(또는 AZURE_SPEECH_RESOURCE_ID) 설정
    - Azure CLI 로그인 (az login)
    - 지원 오디오: wav/mp3/m4a/ogg 등 (Fast Transcription 허용 포맷)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

API_VERSION = "2025-10-15"


# ---------------------------------------------------------------------------
# 엔드포인트 / 인증
# ---------------------------------------------------------------------------

def _get_endpoint() -> str:
    resource_id = os.getenv("AZURE_MAI_SPEECH_RESOURCE_ID") or os.getenv("AZURE_SPEECH_RESOURCE_ID")
    if not resource_id:
        print(
            "[!] .env에 AZURE_MAI_SPEECH_RESOURCE_ID(또는 AZURE_SPEECH_RESOURCE_ID)를 설정하세요.",
            file=sys.stderr,
        )
        sys.exit(1)
    name = resource_id.rstrip("/").split("/")[-1]
    return f"https://{name}.cognitiveservices.azure.com"


def _get_headers() -> dict[str, str]:
    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return {"Authorization": f"Bearer {token.token}"}


# ---------------------------------------------------------------------------
# 타임스탬프
# ---------------------------------------------------------------------------

def _ms_to_srt(ms: int) -> str:
    h = ms // 3_600_000; ms %= 3_600_000
    m = ms // 60_000; ms %= 60_000
    s = ms // 1_000; ml = ms % 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ml:03d}"


def _ms_to_console(ms: int) -> str:
    total = ms // 1000
    return f"[{total // 60:02d}:{total % 60:02d}]"


# ---------------------------------------------------------------------------
# 전사 호출
# ---------------------------------------------------------------------------

def transcribe_file(
    audio_path: str,
    locales: list[str],
    translate_to: str | None = None,
    model: str = "mai-transcribe-1.5",
) -> dict:
    """Fast Transcription API 호출 — 기본 전사, translate_to 지정 시 번역."""
    endpoint = _get_endpoint()
    headers = _get_headers()
    url = f"{endpoint}/speechtotext/transcriptions:transcribe?api-version={API_VERSION}"

    enhanced: dict = {"enabled": True}
    if translate_to:
        # 번역(task=translate)은 모델 지정을 지원하지 않으므로 기본 모델 사용
        enhanced.update({"task": "translate", "targetLanguage": translate_to})
    else:
        enhanced.update({"task": "transcribe"})
        if model:
            enhanced["model"] = model

    definition = {"locales": locales, "enhancedMode": enhanced}

    with open(audio_path, "rb") as audio:
        files = {
            "audio": (os.path.basename(audio_path), audio, "application/octet-stream"),
            "definition": (None, json.dumps(definition), "application/json"),
        }
        resp = requests.post(url, headers=headers, files=files, timeout=600)

    if resp.status_code != 200:
        print(f"[!] API 오류 ({resp.status_code}): {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="로컬 오디오 파일 전사(STT) — MAI-Transcribe (기본 mai-transcribe-1.5)",
    )
    parser.add_argument("audio", help="오디오 파일 경로 (wav/mp3/m4a 등)")
    parser.add_argument(
        "--locale", dest="locales", action="append",
        help="소스 언어 로케일(반복 지정 시 자동 감지, 기본 ko-KR)",
    )
    parser.add_argument("--translate-to", default=None, help="전사 대신 번역할 타깃 언어(예: ko)")
    parser.add_argument(
        "--model", default="mai-transcribe-1.5",
        help="전사 모델 (기본: mai-transcribe-1.5). 전사 모드에서만 적용되며 --translate-to 사용 시 무시됩니다.",
    )
    parser.add_argument("--srt", help="SRT 자막 파일 출력 경로")
    args = parser.parse_args()

    if not os.path.exists(args.audio):
        parser.error(f"오디오 파일을 찾을 수 없습니다: {args.audio}")

    locales = args.locales or ["ko-KR"]
    if args.translate_to:
        mode = f"번역(→{args.translate_to})"
    else:
        mode = f"전사(model: {args.model})"
    print(f"[*] {mode} 시작 — {args.audio}  (locale: {', '.join(locales)})")
    print("=" * 60)

    result = transcribe_file(args.audio, locales, args.translate_to, args.model)

    srt_entries: list[str] = []
    idx = 1
    for phrase in result.get("phrases", []):
        offset = phrase.get("offsetMilliseconds", 0)
        duration = phrase.get("durationMilliseconds", 0)
        text = phrase.get("text", "")
        locale = phrase.get("locale", "??")
        print(f"{_ms_to_console(offset)} [{locale}] {text}")

        if args.srt and text:
            srt_entries.append(
                f"{idx}\n{_ms_to_srt(offset)} --> {_ms_to_srt(offset + duration)}\n{text}\n"
            )
            idx += 1

    if args.srt and srt_entries:
        with open(args.srt, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))
        print(f"\n[✓] SRT 저장 완료: {args.srt}")

    print("[✓] 완료!")


if __name__ == "__main__":
    main()
