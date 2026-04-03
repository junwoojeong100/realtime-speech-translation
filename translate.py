"""
Azure Speech Translation — YouTube 영상 다국어→한국어 번역 자막 생성기

Usage:
    python translate.py <youtube_url>
    python translate.py <youtube_url> --srt output.srt

Prerequisites:
    - Azure Speech 리소스 (Azure Portal에서 생성)
    - FFmpeg 설치 (brew install ffmpeg)
    - .env 파일에 AZURE_SPEECH_REGION 설정
    - Azure CLI 로그인 (az login) 또는 기타 Azure 자격증명 설정
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

import azure.cognitiveservices.speech as speechsdk
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# YouTube 유틸리티
# ---------------------------------------------------------------------------

def is_live_stream(youtube_url: str) -> bool:
    """yt-dlp로 YouTube URL이 라이브 스트림인지 확인"""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-download",
        "--no-playlist",
        youtube_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[!] yt-dlp 메타데이터 조회 실패:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    info = json.loads(result.stdout)
    is_live = info.get("is_live", False)
    if is_live:
        title = info.get("title", "(제목 없음)")
        print(f"[*] 라이브 스트림 감지: {title}")
    return is_live


def download_audio(youtube_url: str, output_path: str) -> str:
    """yt-dlp로 YouTube 오디오를 WAV 16kHz mono로 다운로드"""
    print(f"[*] 오디오 다운로드 중: {youtube_url}")
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "wav",
        "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
        "--output", output_path,
        "--no-playlist",
        youtube_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[!] yt-dlp 에러:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    # yt-dlp가 확장자를 자동 변경할 수 있으므로 .wav 파일 확인
    wav_path = os.path.splitext(output_path)[0] + ".wav"
    if not os.path.exists(wav_path):
        print(f"[!] WAV 파일을 찾을 수 없습니다: {wav_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[✓] 다운로드 완료: {wav_path}")
    return wav_path


def format_time_srt(offset_ticks: int) -> str:
    """Speech SDK의 offset (100ns ticks) → SRT 타임스탬프 형식"""
    total_seconds = offset_ticks / 10_000_000
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    millis = int((total_seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_time_console(offset_ticks: int) -> str:
    """Speech SDK의 offset (100ns ticks) → 콘솔 출력용 타임스탬프"""
    total_seconds = offset_ticks / 10_000_000
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)
    return f"[{minutes:02d}:{seconds:02d}]"


# 입력 언어 자동 감지 후보 (연속 인식 모드 최대 4개)
SOURCE_LANGUAGES = ["en-US", "fa-IR", "ar-SA", "he-IL"]

# 언어 코드 → 콘솔 표시 라벨
LANG_LABELS = {
    "en-US": "EN",
    "fa-IR": "FA",
    "ar-SA": "AR",
    "he-IL": "HE",
}


def get_lang_label(result) -> str:
    """인식 결과에서 감지된 언어의 표시 라벨 반환"""
    auto_detect = speechsdk.AutoDetectSourceLanguageResult(result)
    lang = auto_detect.language
    return LANG_LABELS.get(lang, lang or "??")


def get_speech_token(region: str) -> str:
    """DefaultAzureCredential으로 Speech 서비스용 토큰 획득"""
    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return token.token


# ---------------------------------------------------------------------------
# 콘솔 표시 유틸리티
# ---------------------------------------------------------------------------

def get_terminal_width() -> int:
    import shutil
    return shutil.get_terminal_size().columns


def display_width(text: str) -> int:
    """CJK 전각 문자를 고려한 터미널 표시 너비 계산"""
    import unicodedata
    w = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        w += 2 if eaw in ("W", "F") else 1
    return w


def calc_display_lines(text: str) -> int:
    """텍스트가 터미널에서 차지하는 줄 수 계산"""
    tw = get_terminal_width()
    w = display_width(text)
    if w == 0:
        return 0
    return max(1, (w + tw - 1) // tw)


# ---------------------------------------------------------------------------
# 공통 이벤트 핸들러 생성
# ---------------------------------------------------------------------------

def create_event_handlers(srt_path, srt_entries, srt_index, done_event, interim_lines):
    """recognizer 이벤트 핸들러들을 생성하여 반환"""

    def clear_interim():
        n = interim_lines[0]
        if n > 0:
            if n > 1:
                sys.stdout.write(f"\033[{n - 1}A")
            sys.stdout.write("\r\033[J")
            sys.stdout.flush()
            interim_lines[0] = 0

    def on_recognizing(evt):
        if evt.result.reason == speechsdk.ResultReason.TranslatingSpeech:
            translation = evt.result.translations.get("ko", "")
            timestamp = format_time_console(evt.result.offset)
            line = f"  {timestamp} {translation}"
            clear_interim()
            interim_lines[0] = calc_display_lines(line)
            print(line, end="", flush=True)

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.TranslatedSpeech:
            original = evt.result.text
            translation = evt.result.translations.get("ko", "")
            timestamp = format_time_console(evt.result.offset)
            lang_label = get_lang_label(evt.result)

            clear_interim()
            print(f"{timestamp} [{lang_label}] {original}")
            print(f"         [KO] {translation}")

            if srt_path and translation:
                duration = evt.result.duration
                start_time = format_time_srt(evt.result.offset)
                end_time = format_time_srt(evt.result.offset + duration)
                srt_entries.append(
                    f"{srt_index[0]}\n{start_time} --> {end_time}\n{translation}\n"
                )
                srt_index[0] += 1
        elif evt.result.reason == speechsdk.ResultReason.NoMatch:
            pass

    def on_canceled(evt):
        if evt.reason == speechsdk.CancellationReason.Error:
            print(f"\n[!] 에러: {evt.error_details}", file=sys.stderr)
        elif evt.reason == speechsdk.CancellationReason.EndOfStream:
            print("\n[✓] 오디오 스트림 끝")
        done_event.set()

    def on_session_stopped(evt):
        done_event.set()

    return on_recognizing, on_recognized, on_canceled, on_session_stopped


# ---------------------------------------------------------------------------
# 공통 설정 생성
# ---------------------------------------------------------------------------

def create_translation_config():
    """Speech Translation 설정 및 recognizer에 필요한 config 반환"""
    speech_region = os.getenv("AZURE_SPEECH_REGION")
    resource_id = os.getenv("AZURE_SPEECH_RESOURCE_ID")

    if not speech_region or not resource_id:
        print("[!] .env 파일에 AZURE_SPEECH_REGION과 AZURE_SPEECH_RESOURCE_ID를 설정해주세요.", file=sys.stderr)
        sys.exit(1)

    print("[*] Azure 자격증명으로 토큰 획득 중...")
    aad_token = get_speech_token(speech_region)

    translation_config = speechsdk.translation.SpeechTranslationConfig(
        auth_token=f"aad#{resource_id}#{aad_token}",
        region=speech_region,
    )
    translation_config.add_target_language("ko")

    auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
        languages=SOURCE_LANGUAGES,
    )

    return translation_config, auto_detect_config, speech_region, resource_id


# ---------------------------------------------------------------------------
# 일반 영상 번역 (기존 로직)
# ---------------------------------------------------------------------------

def translate_audio(wav_path: str, srt_path: str | None = None):
    """WAV 파일을 Azure Speech Translation으로 번역"""
    translation_config, auto_detect_config, speech_region, resource_id = create_translation_config()

    audio_config = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.translation.TranslationRecognizer(
        translation_config=translation_config,
        audio_config=audio_config,
        auto_detect_source_language_config=auto_detect_config,
    )

    srt_entries = []
    srt_index = [1]
    done_event = threading.Event()
    interim_lines = [0]

    on_recognizing, on_recognized, on_canceled, on_session_stopped = \
        create_event_handlers(srt_path, srt_entries, srt_index, done_event, interim_lines)

    recognizer.recognizing.connect(on_recognizing)
    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(on_session_stopped)

    langs = ", ".join(LANG_LABELS.values())
    print(f"\n[*] 번역 시작 ({langs} → 한국어, 언어 자동 감지)...")
    print("=" * 60)
    recognizer.start_continuous_recognition()
    done_event.wait()
    recognizer.stop_continuous_recognition()

    if srt_path and srt_entries:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))
        print(f"\n[✓] SRT 자막 저장완료: {srt_path}")

    print("[✓] 번역 완료!")


# ---------------------------------------------------------------------------
# 라이브 스트림 번역
# ---------------------------------------------------------------------------

def translate_live_stream(youtube_url: str, srt_path: str | None = None):
    """라이브 스트림을 실시간으로 번역"""
    translation_config, auto_detect_config, speech_region, resource_id = create_translation_config()

    # PushAudioInputStream 설정 (PCM 16kHz, 16bit, mono)
    stream_format = speechsdk.audio.AudioStreamFormat(
        samples_per_second=16000, bits_per_sample=16, channels=1,
    )
    push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)
    audio_config = speechsdk.audio.AudioConfig(stream=push_stream)

    recognizer = speechsdk.translation.TranslationRecognizer(
        translation_config=translation_config,
        audio_config=audio_config,
        auto_detect_source_language_config=auto_detect_config,
    )

    srt_entries = []
    srt_index = [1]
    done_event = threading.Event()
    interim_lines = [0]
    stop_event = threading.Event()

    on_recognizing, on_recognized, on_canceled, on_session_stopped = \
        create_event_handlers(srt_path, srt_entries, srt_index, done_event, interim_lines)

    recognizer.recognizing.connect(on_recognizing)
    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(on_session_stopped)

    # --- Ctrl+C 핸들러 ---
    original_sigint = signal.getsignal(signal.SIGINT)

    def sigint_handler(signum, frame):
        print("\n[*] 종료 요청 수신, 정리 중...")
        stop_event.set()

    signal.signal(signal.SIGINT, sigint_handler)

    # --- 토큰 갱신 스레드 (45분마다) ---
    def refresh_token():
        while not stop_event.is_set():
            stop_event.wait(timeout=45 * 60)
            if stop_event.is_set():
                break
            try:
                new_token = get_speech_token(speech_region)
                recognizer.authorization_token = f"aad#{resource_id}#{new_token}"
                print("\n[*] Azure 토큰 갱신 완료")
            except Exception as e:
                print(f"\n[!] 토큰 갱신 실패: {e}", file=sys.stderr)

    token_thread = threading.Thread(target=refresh_token, daemon=True)
    token_thread.start()

    # --- yt-dlp → ffmpeg 스트리밍 파이프라인 ---
    print("[*] 라이브 스트림 연결 중...")

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

    # yt-dlp의 stdout을 ffmpeg가 소유하므로 닫기
    ytdlp_proc.stdout.close()

    def feed_audio():
        """ffmpeg 출력을 PushAudioInputStream에 전달"""
        try:
            while not stop_event.is_set():
                data = ffmpeg_proc.stdout.read(3200)  # 100ms 분량
                if not data:
                    break
                push_stream.write(data)
        finally:
            push_stream.close()

    feed_thread = threading.Thread(target=feed_audio, daemon=True)
    feed_thread.start()

    # --- 인식 시작 ---
    langs = ", ".join(LANG_LABELS.values())
    print(f"\n[*] 라이브 번역 시작 ({langs} → 한국어, 언어 자동 감지) — Ctrl+C로 종료")
    print("=" * 60)
    recognizer.start_continuous_recognition()

    # 종료 대기: done_event(스트림 끝) 또는 stop_event(Ctrl+C)
    while not done_event.is_set() and not stop_event.is_set():
        done_event.wait(timeout=1)

    # --- 정리 ---
    stop_event.set()

    try:
        ffmpeg_proc.terminate()
    except OSError:
        pass
    try:
        ytdlp_proc.terminate()
    except OSError:
        pass

    feed_thread.join(timeout=5)
    recognizer.stop_continuous_recognition()

    signal.signal(signal.SIGINT, original_sigint)

    if srt_path and srt_entries:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))
        print(f"\n[✓] SRT 자막 저장완료: {srt_path}")

    print("[✓] 라이브 번역 종료!")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="YouTube 영상 다국어→한국어 실시간 번역 자막 생성기"
    )
    parser.add_argument("url", help="YouTube 동영상 URL")
    parser.add_argument("--srt", help="SRT 자막 파일 출력 경로 (예: output.srt)", default=None)
    parser.add_argument("--keep-audio", action="store_true", help="다운로드한 오디오 파일 유지")
    parser.add_argument("--live", action="store_true", help="라이브 모드 강제 활성화")
    args = parser.parse_args()

    # 라이브 여부 판단: --live 플래그 또는 자동 감지
    live = args.live or is_live_stream(args.url)

    if live:
        # 라이브 스트림: 파이프라인 방식
        translate_live_stream(args.url, args.srt)
    else:
        # 일반 영상: 다운로드 후 번역 (기존 로직)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, "audio.%(ext)s")
            wav_path = download_audio(args.url, output_template)

            if args.keep_audio:
                import shutil
                kept_path = os.path.join(os.getcwd(), "audio.wav")
                shutil.copy2(wav_path, kept_path)
                print(f"[*] 오디오 파일 복사: {kept_path}")

            translate_audio(wav_path, args.srt)


if __name__ == "__main__":
    main()
