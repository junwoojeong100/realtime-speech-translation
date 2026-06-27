"""
실시간 음성 전사(STT) — 마이크 입력 (Azure Speech SDK)

스튜디오 마이크 등 실시간 한국어 음성을 즉시 한국어 텍스트로 전사하는 라이브
PoC 샘플입니다(요건 1: 한국어 음성 → 한국어 텍스트). 방송 환경의
'라이브 음성 → 실시간 자막' 시나리오를 시연하며, 연속 인식(continuous
recognition)으로 중간 결과를 실시간 표시합니다. 기본 소스 언어는 한국어(ko-KR)입니다.

Usage:
    # 기본 마이크에서 한국어 실시간 전사 (기본, 요건 1 — Ctrl+C로 종료)
    python transcribe_mic.py

    # SRT 자막 파일로 저장
    python transcribe_mic.py --srt live.srt

    # (선택) 다른 소스 언어로 전사
    python transcribe_mic.py --locale en-US

    # (선택) 다국어 자동 감지
    python transcribe_mic.py --auto-detect ko-KR en-US ja-JP

Prerequisites:
    - pip install -r requirements_transcribe.txt
    - .env에 AZURE_SPEECH_REGION, AZURE_SPEECH_RESOURCE_ID 설정
    - Azure CLI 로그인 (az login)
    - 마이크 접근 권한 (macOS는 터미널에 마이크 권한 허용 필요)
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

import azure.cognitiveservices.speech as speechsdk
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# 설정 / 인증
# ---------------------------------------------------------------------------

def _get_config() -> tuple[str, str]:
    region = os.getenv("AZURE_SPEECH_REGION")
    resource_id = os.getenv("AZURE_SPEECH_RESOURCE_ID")
    if not region or not resource_id:
        print(
            "[!] .env에 AZURE_SPEECH_REGION과 AZURE_SPEECH_RESOURCE_ID를 설정하세요.",
            file=sys.stderr,
        )
        sys.exit(1)
    return region, resource_id


def _get_token() -> str:
    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return token.token


def _ms_to_srt(ticks: int) -> str:
    """100ns ticks → SRT 타임스탬프."""
    ms = ticks // 10_000
    h = ms // 3_600_000; ms %= 3_600_000
    m = ms // 60_000; ms %= 60_000
    s = ms // 1_000; ml = ms % 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ml:03d}"


def _console_ts(ticks: int) -> str:
    total = ticks // 10_000_000
    return f"[{total // 60:02d}:{total % 60:02d}]"


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="마이크 실시간 전사(STT) — Azure Speech SDK, 라이브 자막 PoC",
    )
    parser.add_argument("--locale", default="ko-KR", help="소스 언어 로케일 (기본 ko-KR)")
    parser.add_argument(
        "--auto-detect", nargs="+", default=None, metavar="LOCALE",
        help="다국어 자동 감지 후보(최대 4개). 예: --auto-detect ko-KR en-US",
    )
    parser.add_argument("--srt", help="SRT 자막 파일 출력 경로")
    args = parser.parse_args()

    region, resource_id = _get_config()
    print("[*] Azure 토큰 획득 중...")
    token = _get_token()

    speech_config = speechsdk.SpeechConfig(
        auth_token=f"aad#{resource_id}#{token}",
        region=region,
    )

    audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

    # 인식기 구성 (단일 언어 또는 자동 감지)
    if args.auto_detect:
        auto_cfg = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=args.auto_detect[:4],
        )
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_cfg,
        )
        lang_label = "자동 감지(" + ", ".join(args.auto_detect[:4]) + ")"
    else:
        speech_config.speech_recognition_language = args.locale
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        lang_label = args.locale

    srt_entries: list[str] = []
    srt_index = [1]
    done = threading.Event()
    stop_event = threading.Event()

    def on_recognizing(evt):
        if evt.result.text:
            sys.stdout.write(f"\r  … {evt.result.text}")
            sys.stdout.flush()

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
            sys.stdout.write("\r\033[K")  # 중간 결과 줄 지우기
            print(f"{_console_ts(evt.result.offset)} {evt.result.text}")
            if args.srt:
                start = _ms_to_srt(evt.result.offset)
                end = _ms_to_srt(evt.result.offset + evt.result.duration)
                srt_entries.append(
                    f"{srt_index[0]}\n{start} --> {end}\n{evt.result.text}\n"
                )
                srt_index[0] += 1

    def on_canceled(evt):
        if evt.reason == speechsdk.CancellationReason.Error:
            print(f"\n[!] 오류: {evt.error_details}", file=sys.stderr)
        done.set()

    def on_session_stopped(evt):
        done.set()

    recognizer.recognizing.connect(on_recognizing)
    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(on_session_stopped)

    # 토큰 갱신 스레드(45분마다)
    def refresh_token():
        while not stop_event.is_set():
            stop_event.wait(timeout=45 * 60)
            if stop_event.is_set():
                break
            try:
                recognizer.authorization_token = f"aad#{resource_id}#{_get_token()}"
                print("\n[*] Azure 토큰 갱신 완료")
            except Exception as e:  # noqa: BLE001
                print(f"\n[!] 토큰 갱신 실패: {e}", file=sys.stderr)

    threading.Thread(target=refresh_token, daemon=True).start()

    print(f"\n[*] 마이크 실시간 전사 시작 ({lang_label}) — Ctrl+C로 종료")
    print("=" * 60)
    recognizer.start_continuous_recognition()

    try:
        while not done.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[*] 종료 요청, 정리 중...")
    finally:
        stop_event.set()
        recognizer.stop_continuous_recognition()

    if args.srt and srt_entries:
        with open(args.srt, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))
        print(f"\n[✓] SRT 저장 완료: {args.srt}")

    print("[✓] 전사 종료!")


if __name__ == "__main__":
    main()
