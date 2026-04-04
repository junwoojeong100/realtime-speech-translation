"""
YouTube 스트리밍 한글 자막 생성기 (MAI-Transcribe-1)

yt-dlp → ffmpeg 파이프라인으로 오디오를 다운로드 완료 없이 스트리밍 수신하고,
10초 단위 청크로 MAI-Transcribe-1 API에 보내 결과가 오는 대로 즉시 출력합니다.

사전 준비:
  pip install -r requirements_mai2.txt

.env 파일:
  AZURE_MAI_SPEECH_RESOURCE_ID - Azure Cognitive Services 리소스 ID

사용법:
  python translate_mai2.py "https://www.youtube.com/watch?v=VIDEO_ID"
  python translate_mai2.py "https://www.youtube.com/watch?v=VIDEO_ID" --chunk 10
  python translate_mai2.py "https://www.youtube.com/watch?v=VIDEO_ID" --source-locale ja-JP
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import time
import threading
import wave
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RESOURCE_ID = os.environ.get("AZURE_MAI_SPEECH_RESOURCE_ID", "")
CHUNK_SEC = 10
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM


def _resource_name_from_id(resource_id: str) -> str:
    parts = resource_id.rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2].lower() == "accounts":
        return parts[-1]
    raise ValueError(f"리소스 ID에서 이름을 추출할 수 없습니다: {resource_id}")


def _get_endpoint() -> str:
    if not RESOURCE_ID:
        raise ValueError("AZURE_MAI_SPEECH_RESOURCE_ID를 .env에 설정하세요.")
    name = _resource_name_from_id(RESOURCE_ID)
    return f"https://{name}.cognitiveservices.azure.com"


# ---------------------------------------------------------------------------
# ANSI 색상
# ---------------------------------------------------------------------------

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K"


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _ms_to_srt(ms: float) -> str:
    ms = int(ms)
    h = ms // 3_600_000; ms %= 3_600_000
    m = ms // 60_000; ms %= 60_000
    s = ms // 1_000; ml = ms % 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ml:03d}"


# ---------------------------------------------------------------------------
# 1. yt-dlp → ffmpeg 스트리밍 파이프라인
# ---------------------------------------------------------------------------


def _start_audio_stream(url: str) -> subprocess.Popen:
    """yt-dlp | ffmpeg 파이프라인을 시작하여 raw PCM stdout 스트림을 반환합니다.

    다운로드 완료를 기다리지 않고 즉시 오디오 데이터를 스트리밍합니다.
    """
    ytdlp_cmd = [
        "yt-dlp",
        "--no-playlist",
        "--format", "bestaudio",
        "--output", "-",
        url,
    ]

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", "pipe:0",
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ac", str(CHANNELS),
        "-ar", str(SAMPLE_RATE),
        "-loglevel", "error",
        "pipe:1",
    ]

    ytdlp_proc = subprocess.Popen(
        ytdlp_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    ffmpeg_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=ytdlp_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    ytdlp_proc.stdout.close()

    return ffmpeg_proc


def _pcm_to_wav_bytes(pcm_data: bytes) -> bytes:
    """Raw PCM 데이터를 WAV 형식 바이트로 변환합니다."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 2. API 호출 (azure-ai-transcription SDK)
# ---------------------------------------------------------------------------


def _translate_chunk_bytes(
    wav_bytes: bytes,
    source_locale: str = "en-US",
) -> str | None:
    """WAV 바이트 청크를 한국어로 번역합니다."""
    from azure.identity import DefaultAzureCredential
    from azure.ai.transcription import TranscriptionClient
    from azure.ai.transcription.models import (
        TranscriptionContent,
        TranscriptionOptions,
        EnhancedModeProperties,
    )

    endpoint = _get_endpoint()
    credential = DefaultAzureCredential()
    client = TranscriptionClient(endpoint=endpoint, credential=credential)

    enhanced_mode = EnhancedModeProperties(
        task="translate",
        target_language="ko",
        prompt=[
            "Translate the audio to Korean.",
            "Keep sentences short for subtitles.",
        ],
    )
    options = TranscriptionOptions(
        locales=[source_locale],
        enhanced_mode=enhanced_mode,
    )

    audio_stream = io.BytesIO(wav_bytes)

    # SDK가 BytesIO를 못 읽을 경우 임시 파일 폴백
    tmp_path = None
    try:
        request_content = TranscriptionContent(definition=options, audio=audio_stream)
        result = client.transcribe(request_content)
    except Exception:
        tmp_path = tempfile.mktemp(suffix=".wav")
        with open(tmp_path, "wb") as f:
            f.write(wav_bytes)
        with open(tmp_path, "rb") as f:
            request_content = TranscriptionContent(definition=options, audio=f)
            result = client.transcribe(request_content)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if result.combined_phrases:
        return result.combined_phrases[0].text
    return None


# ---------------------------------------------------------------------------
# 3. 스트리밍 파이프라인
# ---------------------------------------------------------------------------


def realtime_subtitle(
    youtube_url: str,
    *,
    chunk_sec: int = CHUNK_SEC,
    source_locale: str = "en-US",
    output_srt: str | None = None,
):
    """yt-dlp→ffmpeg 스트리밍으로 YouTube 오디오를 받아 준실시간 자막 생성."""

    chunk_bytes_size = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * chunk_sec

    print(f"\n{CYAN}▶ 스트리밍 시작: {youtube_url}{RESET}")
    print(f"  청크: {chunk_sec}초  |  yt-dlp → ffmpeg 파이프라인")
    print(f"  {'─' * 56}\n")

    proc = _start_audio_stream(youtube_url)
    stdout = proc.stdout

    srt_lines: list[str] = []
    chunk_idx = 0
    stream_start = time.monotonic()

    try:
        while True:
            # ── PCM 데이터 청크 읽기 (스트리밍) ──
            pcm_data = b""
            while len(pcm_data) < chunk_bytes_size:
                remaining = chunk_bytes_size - len(pcm_data)
                block = stdout.read(min(remaining, 8192))
                if not block:
                    break
                pcm_data += block

            if not pcm_data:
                break

            chunk_start_sec = chunk_idx * chunk_sec
            chunk_end_sec = chunk_start_sec + (len(pcm_data) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH))

            # ── WAV 변환 ──
            wav_bytes = _pcm_to_wav_bytes(pcm_data)

            # ── API 호출 (스레드 + 스피너) ──
            api_result: list[str | None] = [None]
            api_error: list[Exception | None] = [None]
            api_done = threading.Event()

            def call_api(wb=wav_bytes, sl=source_locale):
                try:
                    api_result[0] = _translate_chunk_bytes(wb, sl)
                except Exception as e:
                    api_error[0] = e
                finally:
                    api_done.set()

            api_start = time.monotonic()
            t = threading.Thread(target=call_api, daemon=True)
            t.start()

            # 대기 스피너
            spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            spin_i = 0
            while not api_done.is_set():
                elapsed = time.monotonic() - api_start
                c = spinner[spin_i % len(spinner)]
                print(
                    f"\r  {YELLOW}{c} [{_format_time(chunk_start_sec)}] "
                    f"번역 중... {elapsed:.1f}s{RESET}",
                    end="", flush=True,
                )
                spin_i += 1
                api_done.wait(timeout=0.1)

            api_elapsed = time.monotonic() - api_start
            print(f"\r{CLEAR_LINE}", end="")

            if api_error[0]:
                print(f"  {YELLOW}⚠ [{_format_time(chunk_start_sec)}] 오류: {api_error[0]}{RESET}")
                chunk_idx += 1
                continue

            text = api_result[0]
            if not text or not text.strip():
                chunk_idx += 1
                continue

            # ── 즉시 출력 ──
            ts = f"{_format_time(chunk_start_sec)} → {_format_time(chunk_end_sec)}"
            print(
                f"  {DIM}[{ts}]{RESET}  "
                f"{GREEN}{text.strip()}{RESET}  "
                f"{DIM}({api_elapsed:.1f}s){RESET}"
            )

            # SRT 누적
            srt_idx = chunk_idx + 1
            srt_lines.append(str(srt_idx))
            srt_lines.append(
                f"{_ms_to_srt(chunk_start_sec * 1000)} --> "
                f"{_ms_to_srt(chunk_end_sec * 1000)}"
            )
            srt_lines.append(text.strip())
            srt_lines.append("")

            chunk_idx += 1

    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}⏹ 사용자에 의해 중단됨{RESET}")
    finally:
        proc.terminate()
        proc.wait()

    print(f"\n  {'─' * 56}")
    total_elapsed = time.monotonic() - stream_start
    print(f"{CYAN}▶ 완료!{RESET}  {chunk_idx}개 청크, {_format_time(total_elapsed)} 소요\n")

    if output_srt and srt_lines:
        with open(output_srt, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
        print(f"  SRT 저장: {output_srt}\n")

    return "\n".join(srt_lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="YouTube 동영상 준실시간 한글 자막 생성 (MAI-Transcribe-1)",
    )
    parser.add_argument("url", help="YouTube 동영상 URL")
    parser.add_argument(
        "--chunk", "-c", type=int, default=CHUNK_SEC,
        help=f"청크 크기(초, 기본 {CHUNK_SEC}초)",
    )
    parser.add_argument(
        "--source-locale", "-s", default="en-US",
        help="소스 언어 로케일 (기본: en-US)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="SRT 파일로 저장 (선택)",
    )
    args = parser.parse_args()

    if not RESOURCE_ID:
        print("오류: AZURE_MAI_SPEECH_RESOURCE_ID를 .env에 설정하세요.", file=sys.stderr)
        sys.exit(1)

    realtime_subtitle(
        args.url,
        chunk_sec=args.chunk,
        source_locale=args.source_locale,
        output_srt=args.output,
    )


if __name__ == "__main__":
    main()
