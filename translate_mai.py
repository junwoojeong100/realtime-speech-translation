"""
MAI-Transcribe-1 — YouTube 영상 다국어→한국어 번역 자막 생성기

Azure Speech의 MAI-Transcribe-1 (LLM Speech) 모델을 사용하여
YouTube 영상의 음성을 한국어로 번역합니다.

Usage:
    python translate_mai.py <youtube_url>
    python translate_mai.py <youtube_url> --srt output.srt
    python translate_mai.py <youtube_url> --chunk-seconds 5

Prerequisites:
    - Azure Speech 리소스 (LLM Speech 지원 리전: eastus, westus 등)
    - FFmpeg 설치 (brew install ffmpeg)
    - yt-dlp 설치 (pip install yt-dlp)
    - .env 파일에 AZURE_MAI_SPEECH_RESOURCE_ID 또는 AZURE_MAI_SPEECH_API_KEY 설정
    - Azure CLI 로그인 (az login)
"""

from __future__ import annotations

import argparse
import io
import json
import os
import signal
import subprocess
import sys
import threading
import wave

import requests
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# 타임스탬프 유틸리티
# ---------------------------------------------------------------------------

def format_time_srt(ms: int) -> str:
    """밀리초 → SRT 타임스탬프 형식"""
    total_seconds = ms / 1000
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    millis = int(ms % 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_time_console(ms: int) -> str:
    """밀리초 → 콘솔 출력용 타임스탬프"""
    total_seconds = ms / 1000
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)
    return f"[{minutes:02d}:{seconds:02d}]"


# ---------------------------------------------------------------------------
# REST API 호출
# ---------------------------------------------------------------------------

API_VERSION = "2025-10-15"


def _get_endpoint_and_headers() -> tuple[str, dict[str, str]]:
    """엔드포인트 URL과 인증 헤더를 반환"""
    endpoint = os.getenv("AZURE_MAI_SPEECH_ENDPOINT")
    api_key = os.getenv("AZURE_MAI_SPEECH_API_KEY")
    resource_id = os.getenv("AZURE_MAI_SPEECH_RESOURCE_ID")

    if api_key:
        # API 키 인증 — 리전 엔드포인트 사용 가능
        if not endpoint:
            region = os.getenv("AZURE_MAI_SPEECH_REGION")
            if region:
                endpoint = f"https://{region}.api.cognitive.microsoft.com"
            else:
                print("[!] AZURE_MAI_SPEECH_ENDPOINT 또는 AZURE_MAI_SPEECH_REGION을 설정해주세요.", file=sys.stderr)
                sys.exit(1)
        print(f"[*] API 키로 인증 중... (endpoint: {endpoint})")
        headers = {"Ocp-Apim-Subscription-Key": api_key}
    else:
        # Bearer 토큰 인증 (az login) — 커스텀 서브도메인 엔드포인트 필요
        if resource_id:
            resource_name = resource_id.rstrip("/").split("/")[-1]
            endpoint = f"https://{resource_name}.cognitiveservices.azure.com"
        if not endpoint or ".api.cognitive.microsoft.com" in endpoint:
            print(
                "[!] 토큰 인증(az login)은 커스텀 서브도메인 엔드포인트가 필요합니다.\n"
                "    .env에 AZURE_MAI_SPEECH_RESOURCE_ID를 설정하세요.\n"
                "    (LLM Speech 지원 리전: eastus, westus, northeurope, southeastasia, centralindia)",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"[*] DefaultAzureCredential(az login)으로 인증 중... (endpoint: {endpoint})")
        credential = DefaultAzureCredential()
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        headers = {"Authorization": f"Bearer {token.token}"}

    return endpoint, headers


def transcribe_file(audio_file, endpoint: str, headers: dict[str, str]) -> dict:
    """Fast Transcription API + MAI-Transcribe-1 enhanced mode 호출"""
    url = f"{endpoint}/speechtotext/transcriptions:transcribe?api-version={API_VERSION}"

    definition = json.dumps({
        "enhancedMode": {
            "enabled": True,
            "task": "translate",
            "targetLanguage": "ko",
        }
    })

    files = {
        "audio": ("audio.wav", audio_file, "audio/wav"),
        "definition": (None, definition, "application/json"),
    }

    resp = requests.post(url, headers=headers, files=files, timeout=300)
    if resp.status_code != 200:
        print(f"\n[!] API 에러 ({resp.status_code}): {resp.text}", file=sys.stderr)
        resp.raise_for_status()

    return resp.json()


# ---------------------------------------------------------------------------
# PCM → WAV 변환 유틸리티
# ---------------------------------------------------------------------------

def pcm_to_wav_bytes(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """PCM raw 데이터를 WAV 형식의 bytes로 변환"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 스트리밍 번역 (일반 영상 + 라이브 공통)
# ---------------------------------------------------------------------------

CHUNK_SECONDS = 10  # 청크 크기 (초) — 작을수록 더 실시간에 가까움


def translate_stream(youtube_url: str, srt_path: str | None = None,
                     chunk_seconds: int = CHUNK_SECONDS, is_live: bool = False):
    """yt-dlp → ffmpeg 파이프라인으로 오디오를 스트리밍하며 청크 단위로 번역"""
    endpoint, headers = _get_endpoint_and_headers()

    stop_event = threading.Event()
    srt_entries = []
    srt_index = [1]
    cumulative_offset_ms = [0]

    # --- Ctrl+C 핸들러 ---
    original_sigint = signal.getsignal(signal.SIGINT)

    def sigint_handler(signum, frame):
        print("\n[*] 종료 요청 수신, 정리 중...")
        stop_event.set()

    signal.signal(signal.SIGINT, sigint_handler)

    # --- yt-dlp → ffmpeg 스트리밍 파이프라인 ---
    mode_label = "라이브" if is_live else "영상"
    print(f"[*] {mode_label} 스트림 연결 중...")

    ytdlp_proc = subprocess.Popen(
        [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestaudio/best",
            "-o", "-",
            youtube_url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    ffmpeg_proc = subprocess.Popen(
        [
            "ffmpeg",
            "-i", "pipe:0",
            "-f", "s16le",
            "-ar", "16000",
            "-ac", "1",
            "-loglevel", "error",
            "pipe:1",
        ],
        stdin=ytdlp_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    ytdlp_proc.stdout.close()

    sample_rate = 16000
    bytes_per_second = sample_rate * 2  # 16bit mono
    chunk_bytes = bytes_per_second * chunk_seconds

    print(f"\n[*] 실시간 번역 시작 (다국어 → 한국어, {chunk_seconds}초 단위) — Ctrl+C로 종료")
    print("=" * 60)

    pcm_buffer = bytearray()

    try:
        while not stop_event.is_set():
            data = ffmpeg_proc.stdout.read(3200)  # 100ms 분량
            if not data:
                # 남은 데이터 처리
                if pcm_buffer:
                    _process_chunk(
                        endpoint, headers, bytes(pcm_buffer), sample_rate,
                        cumulative_offset_ms, srt_path, srt_entries, srt_index,
                    )
                break

            pcm_buffer.extend(data)

            if len(pcm_buffer) >= chunk_bytes:
                chunk = bytes(pcm_buffer[:chunk_bytes])
                pcm_buffer = pcm_buffer[chunk_bytes:]

                _process_chunk(
                    endpoint, headers, chunk, sample_rate,
                    cumulative_offset_ms, srt_path, srt_entries, srt_index,
                )
    finally:
        stop_event.set()

        try:
            ffmpeg_proc.terminate()
        except OSError:
            pass
        try:
            ytdlp_proc.terminate()
        except OSError:
            pass

        signal.signal(signal.SIGINT, original_sigint)

        if srt_path and srt_entries:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(srt_entries))
            print(f"\n[✓] SRT 자막 저장완료: {srt_path}")

        print("[✓] 번역 완료!")


def _process_chunk(
    endpoint: str,
    headers: dict[str, str],
    pcm_data: bytes,
    sample_rate: int,
    cumulative_offset_ms: list[int],
    srt_path: str | None,
    srt_entries: list[str],
    srt_index: list[int],
):
    """청크를 WAV로 변환 후 MAI-Transcribe-1 API로 번역"""
    wav_data = pcm_to_wav_bytes(pcm_data, sample_rate=sample_rate)

    try:
        audio_stream = io.BytesIO(wav_data)
        result = transcribe_file(audio_stream, endpoint, headers)
    except Exception as e:
        print(f"\n[!] API 호출 에러: {e}", file=sys.stderr)
        chunk_duration_ms = len(pcm_data) * 1000 // (sample_rate * 2)
        cumulative_offset_ms[0] += chunk_duration_ms
        return

    base_offset = cumulative_offset_ms[0]

    if result.get("phrases"):
        for phrase in result["phrases"]:
            abs_offset_ms = base_offset + phrase.get("offsetMilliseconds", 0)
            duration_ms = phrase.get("durationMilliseconds", 0)
            text = phrase.get("text", "")
            locale = phrase.get("locale", "??")

            timestamp = format_time_console(abs_offset_ms)
            print(f"{timestamp} [{locale}] {text}")

            if srt_path and text:
                start_time = format_time_srt(abs_offset_ms)
                end_time = format_time_srt(abs_offset_ms + duration_ms)
                srt_entries.append(
                    f"{srt_index[0]}\n{start_time} --> {end_time}\n{text}\n"
                )
                srt_index[0] += 1

    chunk_duration_ms = len(pcm_data) * 1000 // (sample_rate * 2)
    cumulative_offset_ms[0] += chunk_duration_ms


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="YouTube 영상 다국어→한국어 실시간 번역 자막 생성기 (MAI-Transcribe-1)"
    )
    parser.add_argument("url", help="YouTube 동영상 URL")
    parser.add_argument("--srt", help="SRT 자막 파일 출력 경로 (예: output.srt)", default=None)
    parser.add_argument(
        "--chunk-seconds", type=int, default=CHUNK_SECONDS,
        help=f"청크 크기(초), 작을수록 더 실시간 (기본: {CHUNK_SECONDS})",
    )
    args = parser.parse_args()

    translate_stream(args.url, args.srt, chunk_seconds=args.chunk_seconds)


if __name__ == "__main__":
    main()
