#!/usr/bin/env bash
#
# 방송사 뉴스룸 AI 데모 — 전체 예제를 한 번에 시연
# ---------------------------------------------------------------------------
# YTN 같은 방송사 뉴스룸의 대표 워크플로우를 하나의 스크립트로 시연합니다.
#   1) 외신 텍스트 번역  (Reuters/AP/CNN 영어 기사 → 한국어)  — NMT vs LLM vs Translator-LLM
#   2) 국내 뉴스 음성 전사 (한국어 음성 → 한국어 텍스트 + SRT 자막)
#   3) 해외 음성 번역 자막 (영어 음성 → 한국어 자막)
#   4) (선택) YouTube 영상/라이브 → 한국어 번역 자막
#   5) (라이브) 스튜디오 마이크 실시간 전사 — 실행 안내
#
# 사용법:
#   ./demo.sh                         # 전체 자동 시연 (YouTube는 기본 클립 사용)
#   ./demo.sh "https://youtu.be/..."  # 4번 YouTube 번역을 지정 URL로
#   ./demo.sh --no-youtube            # YouTube 섹션 생략(빠른 실행)
#
# 사전 준비: source .venv/bin/activate 불필요(.venv/bin/python 직접 사용),
#   az login, FFmpeg, macOS(say 음성 합성). 자세한 건 README 참고.
# ---------------------------------------------------------------------------

set -uo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
# YouTube 음성 번역 데모용 기본 클립 (Me at the zoo, 19초). URL 인자로 교체, --no-youtube로 생략.
YOUTUBE_URL="https://www.youtube.com/watch?v=jNQXAC9IVRw"
RUN_YOUTUBE=1
for _arg in "$@"; do
  case "$_arg" in
    --no-youtube) RUN_YOUTUBE=0 ;;
    http*) YOUTUBE_URL="$_arg" ;;
  esac
done
OUT="demo_output"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT"

# --- 색상/헤더 ---
BOLD=$'\033[1m'; CYAN=$'\033[96m'; GREEN=$'\033[92m'; YEL=$'\033[93m'; DIM=$'\033[2m'; RST=$'\033[0m'
section() { echo; echo "${BOLD}${CYAN}━━━ $1 ${RST}"; echo; }
note()    { echo "${DIM}$1${RST}"; }
ok()      { echo "${GREEN}✓ $1${RST}"; }
warn()    { echo "${YEL}! $1${RST}"; }

# --- 0) 사전 점검 ---
section "0. 사전 점검"
[ -x "$PY" ] || { echo "${YEL}.venv가 없습니다. python3.12 -m venv .venv && pip install -r requirements*.txt${RST}"; exit 1; }
ok ".venv 확인: $($PY --version)"
if az account show >/dev/null 2>&1; then ok "az login 확인: $(az account show --query name -o tsv)"; else warn "az login이 안 되어 있습니다 → az login 후 다시 실행하세요"; fi
command -v ffmpeg >/dev/null 2>&1 && ok "ffmpeg 확인" || warn "ffmpeg 없음 (음성 데모에 필요: brew install ffmpeg)"
HAVE_SAY=0; command -v say >/dev/null 2>&1 && HAVE_SAY=1
[ "$HAVE_SAY" = 1 ] && ok "macOS say 음성 합성 사용 가능" || warn "say 없음(비 macOS) → 음성 데모는 본인 오디오 파일로 대체 필요"

# 테스트 음성 생성 헬퍼 (aiff → 16kHz mono wav)
gen_wav() { # $1=voice $2=text $3=out.wav
  say -v "$1" -o "$TMP/_a.aiff" "$2" 2>/dev/null || return 1
  ffmpeg -y -i "$TMP/_a.aiff" -ar 16000 -ac 1 "$3" -loglevel error 2>/dev/null
  [ -s "$3" ]
}

# ===========================================================================
# 1) 외신 텍스트 번역 (영어 기사 → 한국어) — 세 가지 엔진 비교
# ===========================================================================
section "1. 외신 텍스트 번역 (Reuters/AP/CNN → 한국어)  ·  NMT vs LLM vs Translator-LLM"
FEED="$TMP/feed_en.txt"
cat > "$FEED" <<'EOF'
Reuters: The European Central Bank held interest rates steady amid signs of cooling inflation.
AP: Negotiators reached a tentative deal early Sunday to avert a government shutdown.
CNN: A powerful typhoon is barreling toward the southern coast, prompting mass evacuations.
EOF
note "원문(영어):"; sed 's/^/   /' "$FEED"
for ENG in nmt llm translator-llm; do
  echo; echo "${BOLD}[$ENG]${RST}"
  $PY text_translate.py --file "$FEED" --engine "$ENG" 2>/dev/null | sed 's/^/   /' || warn "$ENG 엔진 실패(배포/az login 확인)"
done

# ===========================================================================
# 2) 국내 뉴스 음성 → 한국어 전사 (STT) + SRT 자막
# ===========================================================================
section "2. 국내 뉴스 음성 → 한국어 전사 (STT) + SRT 자막 생성"
KO_TEXT="안녕하십니까, 와이티엔 뉴스입니다. 오늘 코스피는 외국인 매수세에 힘입어 상승 마감했습니다. 정부는 내일 부동산 안정 대책을 발표할 예정입니다."
if [ "$HAVE_SAY" = 1 ] && gen_wav "Yuna" "$KO_TEXT" "$TMP/ko_news.wav"; then
  note "입력 음성(합성): $KO_TEXT"; echo
  $PY transcribe_file.py "$TMP/ko_news.wav" --srt "$OUT/ko_news.srt" 2>/dev/null | sed 's/^/   /' \
    && ok "자막 저장: $OUT/ko_news.srt" || warn "전사 실패(az login/배포 확인)"
else
  warn "한국어 음성 생성 불가 → 본인 파일로:  $PY transcribe_file.py news_ko.wav --srt out.srt"
fi

# ===========================================================================
# 3) 해외 음성 → 한국어 번역 자막
# ===========================================================================
section "3. 해외(영어) 음성 → 한국어 번역 자막"
EN_TEXT="Good evening. This is a live report from London. The summit ended without a joint statement, and officials say negotiations will continue next week."
if [ "$HAVE_SAY" = 1 ] && gen_wav "Samantha" "$EN_TEXT" "$TMP/en_report.wav"; then
  note "입력 음성(합성, 영어): $EN_TEXT"; echo
  $PY transcribe_file.py "$TMP/en_report.wav" --locale en-US --translate-to ko --srt "$OUT/en_report_ko.srt" 2>/dev/null | sed 's/^/   /' \
    && ok "자막 저장: $OUT/en_report_ko.srt" || warn "번역 전사 실패(az login/배포 확인)"
else
  warn "영어 음성 생성 불가 → 본인 파일로:  $PY transcribe_file.py clip.wav --locale en-US --translate-to ko"
fi

# ===========================================================================
# 4) YouTube 영상/라이브 → 한국어 번역 자막 (음성 번역 3엔진 모두)
# ===========================================================================
section "4. YouTube 영상/라이브 → 한국어 번역 자막  ·  음성 번역 3엔진"
if [ "$RUN_YOUTUBE" = 1 ]; then
  note "URL: $YOUTUBE_URL"
  note "(기본 클립입니다. 본인 영상/라이브로:  ./demo.sh \"<YouTube URL>\")"
  for spec in \
    "translate.py|Speech Translation SDK" \
    "translate_llmspeech_rest.py|LLM Speech (REST)" \
    "translate_llmspeech_sdk.py|LLM Speech (SDK)"; do
    script="${spec%%|*}"; label="${spec##*|}"
    echo; echo "${BOLD}[$script — $label]${RST}"
    $PY "$script" "$YOUTUBE_URL" || warn "$script 실패(URL/네트워크 확인)"
  done
else
  note "(--no-youtube로 건너뜀)"
fi

# ===========================================================================
# 5) (라이브) 스튜디오 마이크 실시간 전사 — 실행 안내
# ===========================================================================
section "5. (라이브) 스튜디오 마이크 실시간 전사"
note "마이크 입력은 대화형이라 데모에 자동 포함하지 않습니다. 직접 실행:"
note "   $PY transcribe_mic.py            # 한국어 실시간 자막(Ctrl+C 종료)"
note "   $PY transcribe_mic.py --srt live.srt"

# --- 마무리 ---
section "완료"
ok "생성된 자막 파일: $OUT/"
ls -1 "$OUT" 2>/dev/null | sed 's/^/   - /'
note "각 스크립트 개별 사용법과 비용·서비스 비교는 README.md 참고."
