# Realtime Speech Translation

YouTube 영상의 다국어 음성을 한국어로 실시간 번역하는 CLI 도구입니다. 일반 영상과 라이브 스트림 모두 지원하며, SRT 자막 파일 출력이 가능합니다.

## 주요 기능

- YouTube 영상/라이브 스트림 음성 → 한국어 번역
- 다국어 자동 감지 (영어, 페르시아어, 아랍어, 히브리어)
- 오디오 파일/마이크 음성 → 한국어 전사 (STT)
- 외신 텍스트(영어 등) → 한국어 번역 (Azure AI Translator)
- SRT 자막 파일 생성
- 실시간 중간 결과 표시

## 세 가지 번역 엔진

| | `translate.py` | `translate_mai_rest.py` | `translate_mai_sdk.py` |
|---|---|---|---|
| **엔진** | Azure Speech Translation SDK | MAI-Transcribe (REST API 직접 호출) | MAI-Transcribe (azure-ai-transcription SDK) |
| **방식** | 연속 인식 (스트리밍) | 청크 단위 REST 호출 | 청크 단위 SDK 호출 |
| **라이브 스트림** | 지원 (자동 감지) | 지원 | 지원 |
| **인증** | Azure AD (az login) | API 키 또는 Azure AD | Azure AD (az login) |
| **UI** | 타임스탬프 출력 | 타임스탬프 출력 | ANSI 색상 + 스피너 애니메이션 |

## 사전 요구사항

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) (`brew install ffmpeg`)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (pip으로 자동 설치)
- Azure Speech 리소스 (Azure Portal에서 생성)
- Azure CLI 로그인 (`az login`) — Azure AD 인증 사용 시

## 설치

```bash
# 가상환경 생성 및 활성화
python3.12 -m venv .venv
source .venv/bin/activate

# translate.py 사용 시
pip install -r requirements.txt

# translate_mai_rest.py 사용 시
pip install -r requirements_mai_rest.txt

# translate_mai_sdk.py 사용 시
pip install -r requirements_mai_sdk.txt

# text_translate.py 사용 시 (외신 텍스트 번역)
pip install -r requirements_text.txt

# transcribe_file.py / transcribe_mic.py 사용 시 (음성 전사 STT)
pip install -r requirements_transcribe.txt
```

## 환경 변수 설정

`.env.example`을 복사하여 `.env` 파일을 만들고 값을 채워주세요.

```bash
cp .env.example .env
```

### translate.py

| 변수 | 설명 |
|---|---|
| `AZURE_SPEECH_REGION` | Azure Speech 리소스 리전 |
| `AZURE_SPEECH_RESOURCE_ID` | Azure Speech 리소스의 전체 ARM 리소스 ID |

### translate_mai_rest.py

API 키 인증 또는 Azure AD 인증 중 하나를 선택합니다.

| 변수 | 설명 |
|---|---|
| `AZURE_MAI_SPEECH_API_KEY` | API 키 (키 인증 시) |
| `AZURE_MAI_SPEECH_REGION` | 리전 (키 인증 시, 엔드포인트 미지정 시 사용) |
| `AZURE_MAI_SPEECH_RESOURCE_ID` | 리소스 ID (Azure AD 인증 시) |
| `AZURE_MAI_SPEECH_ENDPOINT` | (선택) 커스텀 엔드포인트 직접 지정 |

### translate_mai_sdk.py

Azure AD 인증만 지원합니다.

| 변수 | 설명 |
|---|---|
| `AZURE_MAI_SPEECH_RESOURCE_ID` | Azure Cognitive Services 리소스 ID |

### transcribe_file.py

| 변수 | 설명 |
|---|---|
| `AZURE_MAI_SPEECH_RESOURCE_ID` | 리소스 ID (미설정 시 `AZURE_SPEECH_RESOURCE_ID` 사용) |

### transcribe_mic.py

| 변수 | 설명 |
|---|---|
| `AZURE_SPEECH_REGION` | Azure Speech 리소스 리전 |
| `AZURE_SPEECH_RESOURCE_ID` | Azure Speech 리소스의 전체 ARM 리소스 ID |

### text_translate.py

| 변수 | 설명 |
|---|---|
| `AZURE_TRANSLATOR_REGION` | Translator 리전 (미설정 시 `AZURE_SPEECH_REGION` 사용) |
| `AZURE_TRANSLATOR_RESOURCE_ID` | 멀티서비스 리소스 ID (미설정 시 `AZURE_SPEECH_RESOURCE_ID` 사용) |
| `AZURE_TRANSLATOR_API_KEY` | (선택) API 키 인증 시 |
| `AZURE_TRANSLATOR_ENDPOINT` | (선택) 커스텀 엔드포인트 |

## 사용법

### translate.py — Speech SDK

```bash
# 일반 영상 번역
python translate.py "https://www.youtube.com/watch?v=VIDEO_ID"

# SRT 자막 파일 생성
python translate.py "https://www.youtube.com/watch?v=VIDEO_ID" --srt output.srt

# 라이브 스트림 강제 모드
python translate.py "https://www.youtube.com/watch?v=VIDEO_ID" --live

# 다운로드한 오디오 파일 유지
python translate.py "https://www.youtube.com/watch?v=VIDEO_ID" --keep-audio
```

### translate_mai_rest.py — MAI-Transcribe (REST API)

```bash
# 영상 번역
python translate_mai_rest.py "https://www.youtube.com/watch?v=VIDEO_ID"

# SRT 자막 파일 생성
python translate_mai_rest.py "https://www.youtube.com/watch?v=VIDEO_ID" --srt output.srt

# 청크 크기 조절 (초 단위, 작을수록 더 실시간)
python translate_mai_rest.py "https://www.youtube.com/watch?v=VIDEO_ID" --chunk-seconds 5
```

### translate_mai_sdk.py — MAI-Transcribe (azure-ai-transcription SDK)

```bash
# 영상 번역
python translate_mai_sdk.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 청크 크기 조절 (초 단위, 기본 10초)
python translate_mai_sdk.py "https://www.youtube.com/watch?v=VIDEO_ID" --chunk 5

# 소스 언어 지정 (기본: en-US)
python translate_mai_sdk.py "https://www.youtube.com/watch?v=VIDEO_ID" --source-locale ja-JP

# SRT 자막 파일 생성
python translate_mai_sdk.py "https://www.youtube.com/watch?v=VIDEO_ID" --output output.srt
```

실행 중 `Ctrl+C`로 종료할 수 있습니다.

### transcribe_file.py — 오디오 파일 전사 (STT)

기본 모델은 최신 `mai-transcribe-1.5`입니다(전사 모드 한정 — 번역 모드에서는 서비스 제약으로 기본 모델이 사용됩니다).

```bash
# 한국어 음성 파일 전사 (기본 모델 mai-transcribe-1.5)
python transcribe_file.py news_ko.wav

# SRT 자막 파일 생성
python transcribe_file.py news_ko.wav --srt output.srt

# 모델/소스 언어 지정
python transcribe_file.py clip.wav --model mai-transcribe-1 --locale en-US

# 전사 대신 한국어로 번역 (모델 지정은 무시됨)
python transcribe_file.py foreign.wav --translate-to ko
```

macOS에서는 `say` 명령으로 한국어 테스트 음성을 만들어 바로 확인할 수 있습니다.

```bash
say -v Yuna -o ko.aiff "안녕하세요. 오늘 서울 증시는 상승 마감했습니다."
ffmpeg -i ko.aiff -ar 16000 -ac 1 ko.wav
python transcribe_file.py ko.wav
```

### transcribe_mic.py — 마이크 실시간 전사

```bash
# 기본 마이크에서 한국어 실시간 전사 (Ctrl+C로 종료)
python transcribe_mic.py

# SRT 자막 파일 생성
python transcribe_mic.py --srt output.srt

# 소스 언어 지정
python transcribe_mic.py --locale en-US

# 다국어 자동 감지
python transcribe_mic.py --auto-detect ko-KR en-US ja-JP
```

macOS는 첫 실행 시 터미널 마이크 권한 허용이 필요합니다(시스템 설정 → 개인정보 보호 및 보안 → 마이크).

### text_translate.py — 외신 텍스트 번역 (Azure AI Translator)

로이터·AP·CNN 등 외신 영어 텍스트를 한국어로 번역합니다. 요청 한도(1,000줄·50,000자)에 맞춰 자동 배치 처리하며, 표준입력으로 실시간 인입을 처리할 수 있습니다.

```bash
# 단건 번역 (영어 → 한국어)
python text_translate.py "The central bank raised interest rates."

# 파일(줄 단위) 번역 → 결과 파일 생성
python text_translate.py --file news_en.txt --output news_ko.txt

# 표준입력에서 번역
cat news_en.txt | python text_translate.py --stdin

# 소스 언어 지정 (자동 감지 대신)
python text_translate.py "Wall Street rallied." --from en --to ko
```

## License

MIT
