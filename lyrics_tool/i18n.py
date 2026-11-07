"""화면 문구 (영어·한국어).

`t(ui, key, **kw)` 하나로 쓴다. 없는 키는 키 이름을 그대로 돌려줘 화면에서 바로 눈에 띄게 한다.
라이브러리 메시지(엔진 오류·정리 내역·실패 사유)도 여기서 가져와 UI 언어를 따른다.
"""

from __future__ import annotations

UI_LANGS = [("English", "en"), ("한국어", "ko")]

S: dict[str, tuple[str, str]] = {
    # ---- 머리말
    "app_title": ("Lyrics Chunk Reader", "가사 직독직해"),
    "subtitle": ("Splits song lyrics into meaning chunks and glosses each one, then gives a literal translation. "
                 "Settings are in the left sidebar, line editing in the right.",
                 "가사를 의미 단위로 끊어 조각마다 뜻을 달고 직역합니다. 설정은 왼쪽, 줄 수정은 오른쪽 사이드바에 있습니다."),
    # ---- 입력
    "input": ("Lyrics", "가사 입력"),
    "input_collapsed": ("Lyrics — {name} · {n} lines", "가사 입력 — {name} · {n}줄"),
    "lyrics_ph": ("Paste lyrics and press Translate (Ctrl/Cmd+Enter). Blank lines are kept as stanza breaks.\n"
                  "[Chorus] labels, timestamps, credits and site leftovers are cleaned up automatically.",
                  "가사를 붙여넣고 번역 (Ctrl/Cmd+Enter). 빈 줄은 연 구분으로 유지됩니다.\n"
                  "[Chorus]·타임스탬프·크레딧·사이트 잔여물은 자동으로 정리합니다."),
    "title_ph": ("Song title (optional, defaults to the first line)", "곡 제목 (선택, 비우면 첫 줄)"),
    "auto_detect": ("Auto-detect", "자동 감지"),
    "to_lang": ("→ {lang}", "→ {lang}"),
    "translate": ("Translate", "번역"),
    "stop": ("Stop", "중단"),
    "auto_clean": ("Auto-clean", "자동 정리"),
    "force": ("Ignore cache", "캐시 무시"),
    "clean_only": ("Clean only", "정리만 하기"),
    "upload": ("File (.txt .lrc)", "파일 (.txt .lrc)"),
    "untitled": ("Untitled", "제목 없음"),
    # ---- 툴바·뷰어
    "mode_source": ("Source order (chunks)", "원문 어순 (끊어읽기)"),
    "mode_target": ("Target order (literal)", "번역 어순 (직역)"),
    "mode_both": ("Both", "둘 다"),
    "unit_line": ("By line", "줄 단위"),
    "unit_sentence": ("By sentence", "문장 단위"),
    "reading": ("Pronunciation", "발음"),
    "hide": ("Hide translation", "번역 가리기"),
    "edit_toggle": ("✎ Edit line", "✎ 줄 수정"),
    "empty": ("Paste lyrics and press <b>Translate</b> to see them here.<br>"
              "Click a line number to edit that line.",
              "가사를 붙여넣고 <b>번역</b>을 누르면 여기에 표시됩니다.<br>줄 번호를 누르면 그 줄을 고칠 수 있습니다."),
    "pending": ("Waiting for translation…", "번역 대기 중…"),
    "dict_title": ("Look up in dictionary", "사전에서 찾기"),
    "tts_title": ("Click to listen", "눌러서 듣기"),
    "tts_dict_title": ("Click: listen · Middle-click: dictionary", "클릭: 듣기 · 휠 클릭: 사전"),
    "tts_no_voice": ("No voice is installed for this language. Add one in your OS speech settings.",
                     "이 언어의 음성이 설치되어 있지 않습니다. OS 음성 설정에서 추가해 주세요."),
    # ---- 왼쪽 사이드바
    "settings": ("Settings", "설정"),
    "acc_engine": ("Engine", "엔진"),
    "engine": ("Translation engine", "번역 엔진"),
    "engine_ollama": ("Ollama (local)", "Ollama (로컬)"),
    "engine_gemini": ("Gemini (free API)", "Gemini (무료 API)"),
    "engine_openai": ("OpenAI-compatible API", "OpenAI 호환 API"),
    "model": ("Model", "모델"),
    "model_info_ollama": ("Blank = OLLAMA_MODEL (default {model})", "비우면 OLLAMA_MODEL (기본 {model})"),
    "model_info_gemini": ("Blank = GEMINI_MODEL (default {model}; more accurate: gemini-3.6-flash)",
                          "비우면 GEMINI_MODEL (기본 {model}, 더 정확하게: gemini-3.6-flash)"),
    "model_info_openai": ("Blank = OPENAI_MODEL", "비우면 OPENAI_MODEL"),
    "url_ph_ollama": ("Ollama address (default http://localhost:11434)", "Ollama 주소 (기본 http://localhost:11434)"),
    "url_ph_openai": ("Base URL (e.g. https://api.groq.com/openai/v1)", "Base URL (예: https://api.groq.com/openai/v1)"),
    "api_key": ("API key (blank = .env value, never saved)", "API 키 (비우면 .env 값 사용, 저장되지 않음)"),
    "base_url": ("Server address", "서버 주소"),
    "check": ("Test connection", "연결 확인"),
    "clear_cache": ("Clear cache", "캐시 비우기"),
    "batch": ("Max lines per request", "한 번에 보낼 최대 줄 수"),
    "batch_info": ("Longer stanzas are split. Smaller = fewer refusals, larger = faster. "
                   "Changing it changes segments, so earlier cache entries may miss.",
                   "연이 이보다 길면 나눠 보냅니다. 작을수록 거부가 줄고, 클수록 빠릅니다. "
                   "값을 바꾸면 기존 캐시와 구간이 달라집니다."),
    "retries": ("Retries on request failure", "요청 실패 시 재시도 횟수"),
    "retries_info": ("On dropped connections, timeouts, rate limits (429) or overload (5xx), waits and retries — "
                     "as long as the server asks, otherwise 2·4·8… s.",
                     "연결 끊김·시간 초과·한도 초과(429)·서버 과부하(5xx)일 때 기다렸다가 다시 요청합니다. "
                     "서버가 알려 준 대기 시간, 없으면 2·4·8…초."),
    "fb_engine": ("Fallback engine", "보조 엔진"),
    "fb_engine_info": ("Retries only the lines the main engine failed. Uses keys/addresses from .env.",
                       "주 엔진에서 실패한 줄만 다시 시도합니다. 키·주소는 .env 값을 씁니다."),
    "fb_model": ("Fallback model", "보조 모델"),
    "fb_model_ph": ("Blank = .env default", "비우면 .env 기본값"),
    "none": ("None", "사용 안 함"),
    "privacy": ("With Ollama, lyrics never leave your PC. API engines send the input to that service.",
                "Ollama는 가사가 PC 밖으로 나가지 않습니다. API 엔진은 입력이 해당 서비스로 전송됩니다."),
    "acc_display": ("Display", "표시"),
    "font": ("Font size", "글자 크기"),
    "numbers": ("Line numbers (click to edit that line)", "줄 번호 (누르면 그 줄 수정)"),
    "dict": ("Dictionary links on chunks", "청크 사전 링크"),
    "dict_info": ("Click a chunk's source text to hear it; middle-click (or Ctrl+click) opens the dictionary "
                  "in a new tab.",
                  "끊어읽기 카드의 원문을 누르면 소리로 읽어 주고, 휠 클릭(또는 Ctrl+클릭)하면 새 탭에서 사전을 엽니다."),
    "dict_naver": ("Naver Dictionary", "네이버 사전"),
    "dict_intl": ("Jisho · MDBG · Wiktionary", "Jisho · MDBG · Wiktionary"),
    "dict_off": ("Off", "사용 안 함"),
    "acc_export": ("Export", "내보내기"),
    "files": ("Markdown · printable HTML · JSON", "Markdown · 인쇄용 HTML · JSON"),
    # ---- 히스토리
    "history_count": ("📚 Recent translations ({n})", "📚 최근 번역 ({n})"),
    "history_current": ("📚 Recent translations ({n}) — open: {title}", "📚 최근 번역 ({n}) — 지금: {title}"),
    "history_help": ("Click a row to open the saved translation right away — nothing is translated again. "
                     "Only songs with every line translated are kept, one JSON file per song in `{path}`.",
                     "줄을 누르면 저장된 번역을 바로 엽니다(다시 번역하지 않음). 모든 줄이 번역된 곡만 "
                     "`{path}` 폴더에 곡마다 JSON 파일로 남습니다."),
    "history_empty": ("No saved translations yet. A song appears here once every line is translated.",
                      "아직 저장된 번역이 없습니다. 모든 줄이 번역된 곡이 여기에 나타납니다."),
    "col_title": ("Title", "제목"),
    "col_langs": ("Languages", "언어"),
    "col_lines": ("Lines", "줄"),
    "col_model": ("Model", "모델"),
    "col_saved": ("Saved", "저장"),
    "hist_delete_current": ("🗑 Delete the open song from history", "🗑 지금 연 곡을 히스토리에서 삭제"),
    "history_opened": ("Opened the saved translation from {when}. Press Translate to translate it again.",
                       "{when}에 저장한 번역을 열었습니다. 다시 번역하려면 번역을 누르세요."),
    "history_saved": ("Saved to history.", "히스토리에 저장했습니다."),
    "history_not_saved": ("Not saved to history because some lines failed.",
                          "실패한 줄이 있어 히스토리에 저장하지 않았습니다."),
    "history_deleted": ("Deleted from history.", "히스토리에서 삭제했습니다."),
    "history_pick": ("Open a song from the list first.", "먼저 목록에서 곡을 여세요."),
    "history_missing": ("That history entry no longer exists.", "그 히스토리 항목이 없습니다."),
    # ---- 오른쪽 사이드바
    "edit": ("Edit line", "줄 수정"),
    "edit_help": ("Click a **line number** in the viewer to load it here. Retranslate it with the current engine "
                  "or fix it by hand. Repeated stanzas are updated together.",
                  "뷰어의 **줄 번호**를 누르면 그 줄을 불러옵니다. 현재 엔진으로 다시 번역하거나 직접 고쳐 "
                  "저장하세요. 같은 연이 반복되면 함께 반영됩니다."),
    "line_no": ("Line", "줄 번호"),
    "load_line": ("Load", "불러오기"),
    "chunks": ("Chunks (one per line: `source | gloss`)", "청크 (한 줄에 `원문 | 뜻`)"),
    "line_tr": ("Line translation", "줄 직역"),
    "sent_tr": ("Sentence translation", "문장 직역"),
    "sent_tr_range": ("Sentence translation (lines {a}–{b})", "문장 직역 ({a}~{b}줄)"),
    "retrans": ("Retranslate this line", "이 줄 다시 번역"),
    "save": ("Save edit", "수정 저장"),
    "retry_all": ("Retranslate all failed lines", "실패한 줄 모두 다시 번역"),
    "line_head": ("**Line {n}** `{src}`", "**{n}줄** `{src}`"),
    "line_pending": ("**Line {n}** `{src}` — not translated yet.", "**{n}줄** `{src}` — 아직 번역되지 않았습니다."),
    "line_grouped": ("Lines {a}–{b} form one sentence. Retranslating translates the whole sentence.",
                     "{a}~{b}줄이 한 문장으로 묶여 있습니다. 다시 번역하면 문장 전체를 함께 번역합니다."),
    "line_not_target": ("Line {n} has nothing to translate (blank or out of range).",
                        "{n}번 줄은 번역 대상이 아닙니다(빈 줄이거나 범위 밖)."),
    # ---- 상태·알림
    "n_lines": ("{n} lines", "{n}줄"),
    "segments": ("segments {done}/{total}", "구간 {done}/{total}"),
    "engine_status": ("engine {name} `{model}`", "엔진 {name} `{model}`"),
    "failed_lines": ("⚠ {n} lines failed — retranslate them in 'Edit line'",
                     "⚠ {n}줄 실패 — '줄 수정'에서 다시 번역할 수 있습니다"),
    "translating": ("Translating…", "번역 중…"),
    "cleaned": ("Cleaned: {items}", "가사 정리: {items}"),
    "nothing_to_clean": ("Nothing to clean.", "정리할 내용이 없습니다."),
    "file_loaded": ("Loaded file: {name}", "파일을 불러왔습니다: {name}"),
    "cache_hits": ("Loaded {n} segments from cache.", "캐시에서 {n}개 구간을 불러왔습니다."),
    "fb_retrying": ("Retrying failed lines with the fallback engine ({name} `{model}`)…",
                    "보조 엔진({name} `{model}`)으로 실패한 줄 재시도 중…"),
    "fb_done": ("Fallback engine translated {fixed}/{failed} lines.", "보조 엔진으로 {fixed}/{failed}줄을 번역했습니다."),
    "stopped": ("⏹ Stopped. Finished parts are kept.", "⏹ 중단했습니다. 번역된 부분까지는 유지됩니다."),
    "retranslated": ("Retranslated line {n}.", "{n}줄을 다시 번역했습니다."),
    "saved": ("Saved your edit to line {n}.", "{n}줄 수정 내용을 저장했습니다."),
    "retrying": ("Retrying failed lines…", "실패한 줄 재시도 중…"),
    "retry_done": ("Finished retrying.", "재시도를 마쳤습니다."),
    "err_no_lyrics": ("Please enter lyrics.", "가사를 입력해 주세요."),
    "err_run_first": ("Translate first.", "먼저 번역을 실행하세요."),
    "err_run_first_line": ("Translate first and enter a line number.", "먼저 번역을 실행하고 줄 번호를 입력하세요."),
    "err_same_lang": ("The source and target languages are both {lang}. Pick another target language.",
                      "원문과 번역 언어가 모두 {lang}입니다. 다른 번역 언어를 고르세요."),
    "models_loaded": ("Added {n} available models to the model list.", "사용 가능한 모델 {n}개를 모델 목록에 넣었습니다."),
    "cache_cleared": ("Cleared {n} cached segments.", "캐시 {n}개 구간을 지웠습니다."),
    # ---- 번역 코어
    "refused": ("The model refused: {text}", "모델이 거부했습니다: {text}"),
    "json_fail": ("Could not parse JSON: {text}", "JSON 파싱 실패: {text}"),
    "no_lines": ("The response has no 'lines' array.", "응답에 'lines' 배열이 없습니다."),
    "bad_format": ("The response format did not match", "응답 형식이 맞지 않음"),
    "failed": ("Translation failed", "번역 실패"),
    "not_translated": ("This line is not translated yet.", "아직 번역되지 않은 줄입니다."),
    "need_chunks": ("Enter both the chunks and the line translation.", "청크와 줄 직역을 모두 입력해 주세요."),
    # ---- 엔진
    "timeout": ("{name} timed out ({s}s)", "{name} 응답 시간 초과 ({s}s)"),
    "connect": ("Cannot connect to the {name} server: {url}", "{name} 서버에 연결할 수 없습니다: {url}"),
    "http_error": ("{name} error {status}: {detail}", "{name} 오류 {status}: {detail}"),
    "auth_fail": ("{name} authentication failed ({status}) — check your API key.",
                  "{name} 인증 실패 ({status}) — API 키를 확인하세요."),
    "tries": (" ({n} attempts)", " ({n}회 시도)"),
    "model_missing": ("Connected, but model `{model}` was not found{hint}.",
                      "연결됨. 하지만 모델 `{model}`을 찾을 수 없습니다{hint}."),
    "ollama_hint": (" — run `ollama pull {model}` in a terminal", " — 터미널에서 `ollama pull {model}`"),
    "connected": ("{name} connected · model `{model}` available", "{name} 연결됨 · 모델 `{model}` 사용 가능"),
    "no_gemini_key": ("No Gemini API key (GEMINI_API_KEY).", "Gemini API 키가 없습니다 (GEMINI_API_KEY)."),
    "gemini_input_blocked": ("Gemini blocked the input: {reason}", "Gemini 입력 차단: {reason}"),
    "gemini_empty": ("Gemini returned no candidates.", "Gemini 응답 후보가 비어 있습니다."),
    "gemini_blocked": ("Gemini blocked the response: {reason}", "Gemini 응답 차단: {reason}"),
    "content_filter": ("Blocked by the API content filter", "API 콘텐츠 필터에 의해 차단됨"),
    # ---- 가사 정리
    "clean_ts": ("{n} timestamps", "타임스탬프 {n}줄 정리"),
    "clean_meta": ("{n} LRC tags", "LRC 정보 {n}줄 정리"),
    "clean_sections": ("{n} section labels (→ stanza breaks)", "구간 표시(→ 연 구분) {n}줄 정리"),
    "clean_credits": ("{n} credit lines", "크레딧 {n}줄 정리"),
    "clean_junk": ("{n} site leftovers", "사이트 잔여물 {n}줄 정리"),
    "clean_breaks": ("added {n} stanza breaks from timing gaps", "시간 간격으로 연 구분 {n}곳 추가"),
    "clean_hangul": ("removed {n} interleaved Korean translation lines", "한국어 번역 줄 {n}줄 제거"),
}


def t(ui: str, key: str, **kw) -> str:
    pair = S.get(key)
    if pair is None:
        return key
    text = pair[1] if ui == "ko" else pair[0]
    return text.format(**kw) if kw else text


def pick_ui(accept_language: str | None) -> str:
    """브라우저 Accept-Language에서 첫 언어가 한국어면 ko, 아니면 en."""
    first = (accept_language or "").split(",")[0].strip().lower()
    return "ko" if first.startswith("ko") else "en"
