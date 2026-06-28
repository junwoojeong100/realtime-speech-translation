# Realtime Speech Translation

YouTube 영상의 다국어 음성을 한국어로 실시간 번역하는 CLI 도구입니다. 일반 영상과 라이브 스트림 모두 지원하며, SRT 자막 파일 출력이 가능합니다.

## 주요 기능

- YouTube 영상/라이브 스트림 음성 → 한국어 번역
- 다국어 자동 감지 (영어, 페르시아어, 아랍어, 히브리어)
- 오디오 파일/마이크 음성 → 한국어 전사 (STT)
- 외신 텍스트(영어 등) → 한국어 번역 (Azure AI Translator)
- SRT 자막 파일 생성
- 실시간 중간 결과 표시

## 스크립트별 사용 서비스

| 스크립트 | 작업 | Azure 서비스 | 모델 |
|---|---|---|---|
| `translate.py` | 음성 번역 | Speech Translation (Speech SDK) | Speech 번역 모델 |
| `translate_llmspeech_rest.py` | 음성 번역 | LLM Speech (Fast Transcription, REST) | multimodal model |
| `translate_llmspeech_sdk.py` | 음성 번역 | LLM Speech (azure-ai-transcription SDK) | multimodal model |
| `text_translate.py` | 텍스트 번역 | Azure AI Translator(NMT) / Azure OpenAI(LLM) / Translator-LLM | NMT · `gpt-5.4-mini` · `gpt-5.1` |
| `transcribe_file.py` | 음성 전사 | LLM Speech (Fast Transcription, REST) | **mai-transcribe-1.5** |
| `transcribe_mic.py` | 음성 전사 | Speech SDK (실시간 연속 인식) | Speech 인식 모델 |

> **MAI-Transcribe 모델은 전사(transcription)에만 사용되며, 번역(translation)에는 사용되지 않습니다.** 공식 문서 기준 MAI-transcribe는 번역을 지원하지 않고, 실제로 번역 작업에 모델을 지정하면 서비스가 거부합니다(`HTTP 400: Enhanced mode with model requires task to be 'transcribe'`). 번역은 **LLM Speech의 multimodal model**(음성) 또는 **Azure AI Translator**(텍스트)가 담당하며, MAI 모델을 실제로 호출하는 예제는 `transcribe_file.py`(기본 전사 모드, `mai-transcribe-1.5`) 하나뿐입니다.

## 전체 데모 (방송사 뉴스룸 워크플로우)

`demo.sh` 하나로 방송사 뉴스룸의 대표 워크플로우와 **이 리포의 모든 스크립트**를 한 번에 시연합니다 — 고객 데모/PoC에 바로 사용하세요.

```bash
az login          # (안 되어 있으면)
./demo.sh                                          # 전체 자동 시연 (YouTube는 기본 클립 사용)
./demo.sh "https://www.youtube.com/watch?v=VIDEO_ID"   # YouTube를 지정 URL로
./demo.sh --no-youtube                              # YouTube 섹션 생략(빠른 실행)
```

| 단계 | 시연 | 스크립트 |
|---|---|---|
| 1 | 외신 영어 기사 → 한국어 번역 (NMT/LLM/Translator-LLM 비교) | `text_translate.py` |
| 2 | 국내 뉴스 음성 → 한국어 전사 + SRT 자막 | `transcribe_file.py` |
| 3 | 해외(영어) 음성 → 한국어 번역 자막 | `transcribe_file.py --translate-to ko` |
| 4 | YouTube 영상/라이브 → 한국어 번역 (음성 3엔진) | `translate.py` · `translate_llmspeech_rest.py` · `translate_llmspeech_sdk.py` |
| 5 | (라이브) 스튜디오 마이크 실시간 전사 — 실행 안내 | `transcribe_mic.py` |

> 음성 데모는 macOS `say`로 테스트 음성을 자동 생성하고, 결과 SRT 자막은 `demo_output/`에 저장됩니다. 4번 YouTube는 기본 클립(짧은 영어 영상)으로 **3개 음성 번역 스크립트를 모두** 실행합니다. 5번 마이크만 라이브 입력이 필요해 안내로 대체됩니다. (`az login`·FFmpeg·`.venv` 필요)

## 세 가지 음성 번역 엔진

| | `translate.py` | `translate_llmspeech_rest.py` | `translate_llmspeech_sdk.py` |
|---|---|---|---|
| **엔진** | Azure Speech Translation SDK | LLM Speech (REST API 직접 호출) | LLM Speech (azure-ai-transcription SDK) |
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

# translate_llmspeech_rest.py 사용 시
pip install -r requirements_llmspeech_rest.txt

# translate_llmspeech_sdk.py 사용 시
pip install -r requirements_llmspeech_sdk.txt

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

### translate_llmspeech_rest.py

API 키 인증 또는 Azure AD 인증 중 하나를 선택합니다.

| 변수 | 설명 |
|---|---|
| `AZURE_MAI_SPEECH_API_KEY` | API 키 (키 인증 시) |
| `AZURE_MAI_SPEECH_REGION` | 리전 (키 인증 시, 엔드포인트 미지정 시 사용) |
| `AZURE_MAI_SPEECH_RESOURCE_ID` | 리소스 ID (Azure AD 인증 시) |
| `AZURE_MAI_SPEECH_ENDPOINT` | (선택) 커스텀 엔드포인트 직접 지정 |

### translate_llmspeech_sdk.py

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
| `AZURE_AI_PROJECT_ENDPOINT` | (`--engine llm`) Foundry 프로젝트 엔드포인트 (모델 `gpt-5.4-mini`은 계정 레벨 배포를 공유) |
| `AZURE_TRANSLATOR_LLM_DEPLOYMENT` | (`--engine translator-llm`) Translator용 GPT 배포 이름 (기본 `gpt-5.1`) |

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

### translate_llmspeech_rest.py — LLM Speech (REST API)

```bash
# 영상 번역
python translate_llmspeech_rest.py "https://www.youtube.com/watch?v=VIDEO_ID"

# SRT 자막 파일 생성
python translate_llmspeech_rest.py "https://www.youtube.com/watch?v=VIDEO_ID" --srt output.srt

# 청크 크기 조절 (초 단위, 작을수록 더 실시간)
python translate_llmspeech_rest.py "https://www.youtube.com/watch?v=VIDEO_ID" --chunk-seconds 5
```

### translate_llmspeech_sdk.py — LLM Speech (azure-ai-transcription SDK)

```bash
# 영상 번역
python translate_llmspeech_sdk.py "https://www.youtube.com/watch?v=VIDEO_ID"

# 청크 크기 조절 (초 단위, 기본 10초)
python translate_llmspeech_sdk.py "https://www.youtube.com/watch?v=VIDEO_ID" --chunk 5

# 소스 언어 지정 (기본: en-US)
python translate_llmspeech_sdk.py "https://www.youtube.com/watch?v=VIDEO_ID" --source-locale ja-JP

# SRT 자막 파일 생성
python translate_llmspeech_sdk.py "https://www.youtube.com/watch?v=VIDEO_ID" --output output.srt
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

### text_translate.py — 외신 텍스트 번역 (NMT / LLM / Translator-LLM)

로이터·AP·CNN 등 외신 영어 텍스트를 한국어로 번역합니다. **세 가지 엔진**을 `--engine`으로 선택합니다.

- **`nmt`(기본)** — Azure AI Translator: 저비용·고속·예측가능 → **대량/실시간 인입**에 적합
- **`llm`** — Azure OpenAI(`gpt-5.4-mini`) — **Foundry 프로젝트 경유**: 프롬프트 자유도↑, 문맥·뉘앙스 품질↑
- **`translator-llm`** — Translator 2026-06-06 + GPT 배포(기본 `gpt-5.1`) **경유**: Translator 한 인터페이스로 LLM 품질 + `tone`/`gender` 옵션 (mini/nano 미지원)

| 엔진 | 경로 | 모델 | 비용 | 품질·특징 | 적합 |
|---|---|---|---|---|---|
| `nmt`(기본) | Azure AI Translator | NMT | **최저**(~$10/백만자) | 빠름·예측가능·GA | 대량·실시간 인입 |
| `llm` | Azure OpenAI (**Foundry 프로젝트** 경유) | `gpt-5.4-mini` | 토큰 과금(모델별) | 문맥·뉘앙스↑, 프롬프트 자유 | 고가치 기사·복합 가공 |
| `translator-llm` | Translator **경유** LLM | `gpt-5.1`(풀모델만) | 토큰 과금(프리미엄) | 문맥↑ + tone/gender 내장 | Translator 한 곳에서 NMT↔LLM 전환 |

```bash
# NMT(기본) — 대량·고속
python text_translate.py "The central bank raised interest rates."

# LLM — Azure OpenAI 직접 호출 (문맥·뉘앙스 품질↑)
python text_translate.py "The Fed's pivot caught markets flat-footed." --engine llm

# Translator 경유 LLM (gpt-5.1, tone/gender 등 지원)
python text_translate.py "The Fed's pivot caught markets flat-footed." --engine translator-llm

# 파일(줄 단위) 번역 → 결과 파일 생성
python text_translate.py --file news_en.txt --output news_ko.txt --engine llm

# 표준입력에서 번역
cat news_en.txt | python text_translate.py --stdin
```

> **선택 가이드**: 관용구·맥락이 중요하면 LLM 계열이 더 정확합니다. 예) "the Fed's *pivot*" → NMT "회귀"(오역) vs LLM "방향 전환". 대량·실시간은 **NMT 기본**, 고가치 기사만 **LLM 선택 적용**하는 **하이브리드**가 효율적입니다.
> - **`llm`(직접) vs `translator-llm`(경유)**: 품질은 비슷. 프롬프트 완전 제어·저비용 모델이면 `llm`, Translator 한 곳에서 NMT↔LLM 전환·tone/gender 내장 옵션이면 `translator-llm`.
> - 두 LLM 경로 모두 **Azure OpenAI 모델 배포 필요** (translator-llm은 gpt-5.1/5.4 **풀모델만**).
> - **Azure 리소스 구성**: 단일 AIServices(Foundry) 리소스 `speech-rt-3d9e02`에 Speech·Translator·OpenAI 배포가 모두 있고, Foundry 프로젝트 `proj-realtime-speech`가 이를 공유합니다. **모델 배포는 계정(Foundry 리소스) 레벨**이며 프로젝트가 함께 사용합니다(프로젝트별 별도 배포 아님). `--engine llm`은 `AZURE_AI_PROJECT_ENDPOINT`로 **프로젝트를 경유**합니다.

## 서비스 비교: 비용·성능·용도

이 리포가 사용하는 4가지 Azure 서비스를 고객 관점에서 비교합니다.

> ⚠️ **가격 주의**: 아래 비용은 **2026년 초 기준, 글로벌(미국) 종량제 개략값**입니다. 리전·약정 티어·기능 조합에 따라 달라지므로, 반드시 [Azure 가격 계산기](https://azure.microsoft.com/pricing/calculator/)와 공식 페이지([Speech](https://azure.microsoft.com/pricing/details/speech/) · [Translator](https://azure.microsoft.com/pricing/details/translator/))로 확인하세요. (LLM Speech·MAI-Transcribe는 **공개 preview**)

| 서비스 (스크립트) | 입력 → 출력 | 처리 방식 | 개략 비용 | 성능·특징 | 적합한 용도 |
|---|---|---|---|---|---|
| **Speech Translation** (`translate.py`) | 음성 → 번역 텍스트 | 실시간 스트리밍 | **~$10 / 오디오시간**¹ | 전통적·안정적(GA), 다국어 자동감지, 실시간 중간결과 | 안정성이 중요한 실시간 음성 번역 |
| **LLM Speech** (`translate_llmspeech_*`, `transcribe_file.py`) | 음성 → 전사/번역 | 청크/동기(Fast Transcription) | **~$0.36 / 오디오시간**² | LLM 강화(문맥·정확도↑), 다국어, GPU 초고속, **preview** | 고품질 전사·번역을 **저비용**으로 |
| **Speech SDK 실시간 인식** (`transcribe_mic.py`) | 마이크 음성 → 전사 | 실시간 연속 인식 | **~$1 / 오디오시간** | 저지연 스트리밍, 안정적(GA) | 라이브 자막(스튜디오·회의) |
| **Azure AI Translator** (`text_translate.py`) | 텍스트 → 번역 텍스트 | 동기/배치(대량) | **~$10 / 백만자**³ | NMT, 대량·저지연, GA, 100+ 언어 (`--engine llm`으로 Azure OpenAI 전환 가능) | 외신·문서 등 **텍스트** 대량 번역 |

¹ 음성 입출력 포함 SKU 기준(음성→텍스트만이면 더 낮을 수 있음). ² Fast Transcription과 **동일 SKU·가격**(공식 명시). ³ 종량제 기준, 약정 티어 시 ~$8.22/백만자, F0 무료 200만자/월.

### 핵심 인사이트 (고객 설명용)
- **음성 번역은 LLM Speech가 전통 Speech Translation보다 크게 저렴**(LLM Speech ~$0.36/시간 vs Speech Translation 수 $~$10/시간대)하고 품질도 더 높습니다. 단, LLM Speech는 **preview**(프로덕션 SLA 없음)이므로, 안정성·GA가 필수면 `translate.py`(Speech Translation)를 사용합니다.
- **전사(한국어 STT)** 는 LLM Speech의 `mai-transcribe-1.5`가 정확도·속도 면에서 우수하나 preview입니다.
- **텍스트 번역**(외신 스크립트)은 음성 서비스와 무관하게 Azure AI Translator를 쓰며, 문자 수 기반 과금이라 대량 처리 시 **약정 티어**로 단가를 낮출 수 있습니다.

### 빠른 선택 가이드
- 라이브 방송/회의 **음성 → 실시간 번역 자막** + GA 필수 → `translate.py`
- **음성 → 번역**을 **저비용·고품질**로(파일럿/PoC 허용) → `translate_llmspeech_*`
- **한국어 음성 → 한국어 텍스트 전사** → `transcribe_file.py`(파일) / `transcribe_mic.py`(마이크)
- **텍스트(외신) → 번역** → `text_translate.py` (대량·고속 = `--engine nmt` 기본, 고품질 = `--engine llm`)

## 여기서 쓰지 않은 전사·번역 대안 (참고 가이드)

상황에 따라 더 적합할 수 있는, 이 리포에 포함하지 않은 Azure 옵션입니다.

### 전사(STT) 대안

| 방법 | 특징 | 개략 비용 | 언제 사용 |
|---|---|---|---|
| **Batch Transcription** (Speech) | 대량 파일 **비동기** 처리, 화자분리·채널 지원 | **~$0.18 / 오디오시간** (최저) | 실시간 불필요한 **대량 아카이브**(녹화방송, 콜센터 로그) |
| **Azure OpenAI 음성 모델** (Whisper / `gpt-4o-transcribe` / `-mini`) | 99+ 언어 파일 전사, 분당 과금 | **~$0.006/분**(≈$0.36/시간), mini **~$0.003/분** | OpenAI 생태계 통합, 99+ 언어 파일 전사 (Whisper는 25MB 제한) |
| **Azure AI Video Indexer** | 전사 + 자막 + 화자/장면/얼굴/키워드 인덱싱 | 분 단위 과금 | 영상 **미디어 워크플로우**(검색·하이라이트·OTT 자막) |
| **Custom Speech** | 도메인 용어·악센트·소음 환경 정확도 향상 커스텀 모델 | 학습+호스팅 추가비 | 전문용어·고유명사(방송 인명/지명) 정확도가 critical |

### 번역 대안

> LLM 번역은 이미 `text_translate.py`로 제공됩니다 — `--engine llm`(Azure OpenAI 직접), `--engine translator-llm`(Translator 경유). 아래는 그 외 대안입니다.

| 방법 | 특징 | 언제 사용 |
|---|---|---|
| **Document Translation** (Translator) | docx·pptx·pdf 등 **서식 유지** 문서 배치 번역 | 보고서·계약서 등 **문서 통째** 번역 |
| **Custom Translator** | 용어집·병렬 코퍼스로 도메인 특화 번역 | 산업 전문용어 일관성이 중요할 때 |

> 정리: **실시간·저지연 음성**은 Speech 계열, **대량 텍스트**는 Translator, **최고 문맥 품질·복합 가공**은 LLM(Azure OpenAI/Translator LLM), **대량 파일 저비용 전사**는 Batch가 일반적으로 유리합니다. 비용·정확도·지연·규정준수(리전/데이터 처리) 요건에 맞춰 선택하세요.

## License

MIT
