# Realtime Speech Translation

YouTube 영상의 다국어 음성을 한국어로 실시간 번역하는 CLI 도구입니다. 일반 영상과 라이브 스트림 모두 지원하며, SRT 자막 파일 출력이 가능합니다.

## 주요 기능

- YouTube 영상/라이브 스트림 음성 → 한국어 번역
- 다국어 자동 감지 (영어, 페르시아어, 아랍어, 히브리어)
- SRT 자막 파일 생성
- 실시간 중간 결과 표시

## 두 가지 번역 엔진

| | `translate.py` | `translate_mai.py` |
|---|---|---|
| **엔진** | Azure Speech Translation SDK | MAI-Transcribe-1 (LLM Speech REST API) |
| **방식** | 연속 인식 (스트리밍) | 청크 단위 REST 호출 |
| **라이브 스트림** | 지원 (자동 감지) | 지원 |
| **인증** | Azure AD (az login) | API 키 또는 Azure AD |

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

# translate_mai.py 사용 시
pip install -r requirements_mai.txt
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

### translate_mai.py

API 키 인증 또는 Azure AD 인증 중 하나를 선택합니다.

| 변수 | 설명 |
|---|---|
| `AZURE_MAI_SPEECH_API_KEY` | API 키 (키 인증 시) |
| `AZURE_MAI_SPEECH_REGION` | 리전 (키 인증 시, 엔드포인트 미지정 시 사용) |
| `AZURE_MAI_SPEECH_RESOURCE_ID` | 리소스 ID (Azure AD 인증 시) |
| `AZURE_MAI_SPEECH_ENDPOINT` | (선택) 커스텀 엔드포인트 직접 지정 |

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

### translate_mai.py — MAI-Transcribe-1

```bash
# 영상 번역
python translate_mai.py "https://www.youtube.com/watch?v=VIDEO_ID"

# SRT 자막 파일 생성
python translate_mai.py "https://www.youtube.com/watch?v=VIDEO_ID" --srt output.srt

# 청크 크기 조절 (초 단위, 작을수록 더 실시간)
python translate_mai.py "https://www.youtube.com/watch?v=VIDEO_ID" --chunk-seconds 5
```

실행 중 `Ctrl+C`로 종료할 수 있습니다.

## License

MIT
