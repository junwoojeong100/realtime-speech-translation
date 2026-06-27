"""
외신 영어 텍스트 번역 (Azure AI Translator, Text Translation v3.0)

로이터·AP·CNN 등 실시간 인입되는 외신 영어 스크립트(텍스트)를 한국어로 번역하는
대량 처리용 PoC 샘플입니다(요건 2: 영어 외신 텍스트 → 한국어). 음성이 아닌
'텍스트→텍스트' 번역 영역으로, translate.py / transcribe_*.py(음성 계열)와는
별개의 Azure 서비스를 사용합니다. 소스 언어는 기본 자동 감지(영어 포함)입니다.

인증:
    - 기본: Microsoft Entra ID(AAD) 토큰 — az login 필요, 키 비활성 환경 지원
      (Authorization: Bearer + Ocp-Apim-ResourceId + Ocp-Apim-Subscription-Region)
    - 선택: API 키(AZURE_TRANSLATOR_API_KEY)

Usage:
    # 단건 번역 (영어 외신 → 한국어)
    python translate_text.py "The central bank raised interest rates by 25 basis points."

    # 파일(줄 단위) 번역 → 결과 파일로 저장
    python translate_text.py --file news_en.txt --output news_ko.txt

    # 표준입력(실시간 인입 시뮬레이션) 번역
    cat feed_en.txt | python translate_text.py --stdin

    # 소스 언어를 영어로 명시 (자동 감지 대신)
    python translate_text.py "Wall Street rallied on cooler inflation data." --from en --to ko

Prerequisites:
    - pip install -r requirements_text.txt
    - .env에 AZURE_TRANSLATOR_RESOURCE_ID(또는 AZURE_SPEECH_RESOURCE_ID) 및
      AZURE_TRANSLATOR_REGION(또는 AZURE_SPEECH_REGION) 설정
    - Azure CLI 로그인 (az login) — AAD 인증 시
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# 설정 / 인증
# ---------------------------------------------------------------------------

API_VERSION = "3.0"
DEFAULT_ENDPOINT = "https://api.cognitive.microsofttranslator.com"

# Translator /translate 요청 한도 (v3.0): 배열 최대 1000개, 총 50,000자
MAX_ARRAY_ELEMENTS = 1000
MAX_CHARS_PER_REQUEST = 50_000

# AAD 토큰 캐시 (만료 임박 시 갱신)
_token_cache: dict[str, object] = {"token": None, "expires_on": 0}


def _get_endpoint() -> str:
    return (os.getenv("AZURE_TRANSLATOR_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")


def _get_region() -> str | None:
    return os.getenv("AZURE_TRANSLATOR_REGION") or os.getenv("AZURE_SPEECH_REGION")


def _get_resource_id() -> str | None:
    return os.getenv("AZURE_TRANSLATOR_RESOURCE_ID") or os.getenv("AZURE_SPEECH_RESOURCE_ID")


def _get_aad_token() -> str:
    """DefaultAzureCredential로 토큰 획득(만료 임박 시 갱신)."""
    from azure.identity import DefaultAzureCredential

    now = time.time()
    if _token_cache["token"] and float(_token_cache["expires_on"]) - now > 300:
        return str(_token_cache["token"])

    credential = DefaultAzureCredential()
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    _token_cache["token"] = token.token
    _token_cache["expires_on"] = token.expires_on
    return token.token


def _build_headers() -> dict[str, str]:
    """인증 헤더 구성 — API 키 우선, 없으면 AAD 토큰."""
    api_key = os.getenv("AZURE_TRANSLATOR_API_KEY")
    region = _get_region()

    if api_key:
        headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": "application/json",
        }
        if region:
            headers["Ocp-Apim-Subscription-Region"] = region
        return headers

    # AAD 인증
    resource_id = _get_resource_id()
    if not region or not resource_id:
        print(
            "[!] AAD 인증에는 AZURE_TRANSLATOR_REGION(또는 AZURE_SPEECH_REGION)과\n"
            "    AZURE_TRANSLATOR_RESOURCE_ID(또는 AZURE_SPEECH_RESOURCE_ID)가 필요합니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    token = _get_aad_token()
    return {
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-ResourceId": resource_id,
        "Ocp-Apim-Subscription-Region": region,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# 번역 호출
# ---------------------------------------------------------------------------

def _chunk_texts(texts: list[str]):
    """Translator 요청 한도(1000개 / 50,000자)에 맞춰 텍스트를 배치로 분할."""
    batch: list[str] = []
    batch_chars = 0
    for t in texts:
        t_len = len(t)
        # 단일 텍스트가 한도를 초과하면 단독 배치로 보냄(서비스가 거부할 수 있음 → 경고)
        if t_len > MAX_CHARS_PER_REQUEST:
            print(
                f"[!] 경고: {t_len}자 라인이 단일 요청 한도({MAX_CHARS_PER_REQUEST})를 초과합니다. "
                "긴 문장은 분할을 권장합니다.",
                file=sys.stderr,
            )
        if batch and (len(batch) >= MAX_ARRAY_ELEMENTS or batch_chars + t_len > MAX_CHARS_PER_REQUEST):
            yield batch
            batch, batch_chars = [], 0
        batch.append(t)
        batch_chars += t_len
    if batch:
        yield batch


def translate_batch(
    texts: list[str],
    to_langs: list[str],
    from_lang: str | None = None,
    endpoint: str | None = None,
) -> list[dict]:
    """텍스트 배열을 한 번의 요청으로 번역하여 결과(JSON 배열)를 반환."""
    endpoint = endpoint or _get_endpoint()
    params = {"api-version": API_VERSION, "to": to_langs}
    if from_lang:
        params["from"] = from_lang

    url = f"{endpoint}/translate"
    body = [{"Text": t} for t in texts]

    # 토큰 만료/일시 네트워크 오류 대비 재시도
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            headers = _build_headers()
            resp = requests.post(url, params=params, headers=headers, json=body, timeout=60)
        except requests.exceptions.RequestException as e:
            # 연결 거부/타임아웃 등 일시 오류 → 백오프 후 재시도
            last_err = e
            if attempt < 3:
                time.sleep(1.0 * (attempt + 1))
                continue
            print(f"[!] 네트워크 오류로 번역 실패: {e}", file=sys.stderr)
            raise

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (401, 403) and attempt < 3 and not os.getenv("AZURE_TRANSLATOR_API_KEY"):
            # 토큰 강제 갱신 후 재시도
            _token_cache["token"] = None
            continue
        if resp.status_code == 429 and attempt < 3:
            time.sleep(1.5 * (attempt + 1))
            continue
        print(f"[!] Translator API 오류 ({resp.status_code}): {resp.text}", file=sys.stderr)
        resp.raise_for_status()

    if last_err:
        raise last_err
    return []


# ---------------------------------------------------------------------------
# 입력 수집
# ---------------------------------------------------------------------------

def _gather_texts(args) -> list[str]:
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
        return [ln for ln in lines if ln.strip()]
    if args.stdin:
        lines = [ln.rstrip("\n") for ln in sys.stdin]
        return [ln for ln in lines if ln.strip()]
    if args.text:
        return [args.text]
    return []


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="외신 텍스트 번역 (Azure AI Translator) — 단건/파일/스트림 대량 번역 PoC",
    )
    parser.add_argument("text", nargs="?", help="번역할 텍스트(단건). 생략 시 --file 또는 --stdin 사용")
    parser.add_argument("--file", help="번역할 텍스트 파일 경로(줄 단위 번역)")
    parser.add_argument("--stdin", action="store_true", help="표준입력에서 줄 단위로 읽어 번역")
    parser.add_argument("--from", dest="from_lang", default=None, help="소스 언어 코드(생략 시 자동 감지)")
    parser.add_argument("--to", dest="to_langs", action="append", help="타깃 언어 코드(반복 지정 가능, 기본 ko)")
    parser.add_argument("--output", help="결과를 저장할 파일 경로(번역문만 줄 단위로 기록)")
    parser.add_argument("--show-source", action="store_true", help="원문도 함께 출력")
    args = parser.parse_args()

    to_langs = args.to_langs or ["ko"]
    texts = _gather_texts(args)
    if not texts:
        parser.error("번역할 입력이 없습니다. 텍스트 인자, --file, 또는 --stdin 중 하나를 지정하세요.")

    total_chars = sum(len(t) for t in texts)
    print(
        f"[*] 입력 {len(texts):,}줄 / {total_chars:,}자  →  {', '.join(to_langs)} 번역 시작",
        file=sys.stderr,
    )

    out_lines: list[str] = []
    translated_count = 0
    start = time.monotonic()

    for batch in _chunk_texts(texts):
        results = translate_batch(batch, to_langs, args.from_lang)
        for src, item in zip(batch, results):
            translations = item.get("translations", [])
            for tr in translations:
                ko_text = tr.get("text", "")
                if args.output:
                    out_lines.append(ko_text)
                if args.show_source:
                    print(f"[{tr.get('to')}] 원문: {src}")
                    print(f"[{tr.get('to')}] 번역: {ko_text}\n")
                else:
                    print(ko_text)
            translated_count += 1

    elapsed = time.monotonic() - start

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines) + "\n")
        print(f"[✓] 저장 완료: {args.output}", file=sys.stderr)

    print(
        f"[✓] 완료 — {translated_count:,}줄, {total_chars:,}자, {elapsed:.1f}초 "
        f"({total_chars / elapsed:,.0f} 자/초)" if elapsed > 0 else "[✓] 완료",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
