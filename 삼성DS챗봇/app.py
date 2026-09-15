# -*- coding: utf-8 -*-
"""
칩이 (Chip-i) - 삼성전자 DS부문 반도체 챗봇
표준 라이브러리만 사용하는 로컬 웹 챗봇 서버.

실행:  python app.py
브라우저가 자동으로 http://127.0.0.1:8000 을 엽니다.
"""

import base64
import binascii
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import mailsend
import pdfdoc

# ──────────────────────────────────────────────────────────────
#  설정
# ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

MODEL = "gpt-5.4-mini"        # 사용 모델
MAX_COMPLETION_TOKENS = 1000  # 한 턴 최대 출력 토큰
MEMORY_TURNS = 10             # 기억할 대화 턴 수 (user+assistant = 1턴)
REASONING_EFFORT = "none"     # none / low / medium / high / xhigh
TEMPERATURE = 0.8

MAIL_SUMMARY_MAX_TOKENS = 2000  # 대화 요약 메일 생성용 (채팅 1000토큰과 별개)
MAX_UPLOAD_MB = 20            # 업로드 가능한 PDF 최대 크기
MAX_CONTEXT_CHARS = 24000     # 한 턴에 모델에 넣을 문서 발췌 최대 길이
DOC_TEMPERATURE = 0.2         # 문서 기반 답변은 낮은 온도로 (창작 억제)

HOST = "127.0.0.1"
PORT = 8000
API_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """너는 '칩이(Chip-i)'라는 이름의 귀여운 반도체 마스코트 챗봇이야.
삼성전자 DS부문(반도체) 사내 도우미 컨셉이고, 작은 실리콘 칩에 눈이 달린 모습이야.

말투와 성격:
- 상냥하고 친근한 존댓말을 써. 밝고 씩씩하지만 과하게 호들갑스럽지는 않아.
- 자기를 부를 땐 '칩이'라고 해. (예: "칩이가 알려드릴게요!")
- 이모지는 한 답변에 1~3개 정도만 자연스럽게. (✨🔷⚡🧊🔬💙 같은 것들)
- 어려운 내용은 반도체에 빗대어 귀엽게 비유해줘.
  (예: "그건 클럭이 살짝 어긋난 거예요!", "제 캐시에 저장해뒀어요!")

전문성:
- 반도체 공정(포토·식각·증착·CMP·확산), 소자, 메모리(DRAM/NAND/HBM),
  파운드리, 패키징(TSV·본딩), 수율·불량 분석, 장비, EUV 등은 정확하게 설명해.
- 반도체 외의 일반적인 질문도 친절하게 도와줘.
- 모르거나 불확실하면 솔직하게 모른다고 말해. 지어내지 마.
- 사내 기밀이나 확인되지 않은 수치를 사실처럼 단정하지 마.

분량:
- 기본은 3~6문장으로 간결하게. 길어질 땐 짧은 불릿으로 정리해.
- 출력 한도가 1000토큰이니 너무 길게 늘어놓지 말고 핵심부터 말해."""

# 문서가 업로드된 상태에서 쓰는 시스템 프롬프트 (근거 기반 전용 모드)
DOC_SYSTEM_PROMPT = """너는 '칩이(Chip-i)'라는 이름의 귀여운 반도체 마스코트 챗봇이야.
지금은 **문서 기반 답변 모드**로 동작한다. 아래 규칙은 무엇보다 우선한다.

절대 규칙:
1. 오직 아래에 주어지는 [문서 발췌]의 내용만 근거로 답해라.
2. 네가 이미 알고 있는 배경지식, 상식, 추측, 일반적인 반도체 지식을
   답변에 절대 섞지 마라. 발췌에 없으면 없는 것이다.
3. 발췌에서 답을 찾을 수 없으면 지어내지 말고 이렇게 말해라:
   "그 내용은 업로드하신 문서에서 찾지 못했어요 🥲" — 그리고 문서에서
   확인 가능한 관련 내용이 있다면 그것만 덧붙여라.
4. 외부 검색이나 외부 자료를 참조하지 마라. 그럴 능력이 없다고 생각해라.
5. 숫자, 수치, 날짜, 고유명사는 발췌에 적힌 그대로만 인용해라.
   반올림하거나 단위를 바꾸거나 보기 좋게 다듬지 마라.
6. 문장마다 근거가 된 곳을 `[파일명 p.페이지]` 형식으로 표시해라.
7. 문서와 무관한 일반 질문을 받으면, 지금은 문서 기반 모드라 답할 수 없다고
   안내하고 우측 패널에서 문서를 비우면 된다고 알려줘.

말투:
- 평소처럼 상냥한 존댓말에 이모지 1~2개. 자기는 '칩이'라고 불러.
- 🥲 는 문서에서 답을 못 찾았을 때만 써라. 평소에는 ✨🔷📄⚡ 같은 밝은 이모지를 써.
- 단, 규칙 1~6은 말투보다 우선한다. 귀엽게 보이려고 없는 내용을 만들지 마라.

분량:
- 3~6문장으로 간결하게. 항목이 많으면 짧은 불릿으로.
- 출력 한도는 1000토큰이다."""


# ──────────────────────────────────────────────────────────────
#  API 키
# ──────────────────────────────────────────────────────────────
def load_dotenv(path: Path) -> None:
    """의존성 없이 .env 를 읽어 os.environ 에 넣는다 (KEY=VALUE, # 주석 지원)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_api_key() -> str:
    load_dotenv(ENV_FILE)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        sys.exit(
            f"[오류] OPENAI_API_KEY 를 찾을 수 없습니다.\n"
            f"       {ENV_FILE} 파일에 다음 한 줄을 넣어주세요:\n"
            f"       OPENAI_API_KEY=sk-..."
        )
    return key


API_KEY = load_api_key()

# ──────────────────────────────────────────────────────────────
#  세션별 대화 메모리 (최근 MEMORY_TURNS 턴만 유지)
# ──────────────────────────────────────────────────────────────
_sessions: dict[str, list[dict]] = {}
_lock = threading.Lock()


def get_history(sid: str) -> list[dict]:
    with _lock:
        return list(_sessions.setdefault(sid, []))


def remember(sid: str, user_msg: str, bot_msg: str) -> int:
    """대화를 저장하고 최근 MEMORY_TURNS 턴만 남긴 뒤, 보유 턴 수를 반환."""
    with _lock:
        hist = _sessions.setdefault(sid, [])
        hist.append({"role": "user", "content": user_msg})
        hist.append({"role": "assistant", "content": bot_msg})
        del hist[: max(0, len(hist) - MEMORY_TURNS * 2)]
        return len(hist) // 2


def forget(sid: str) -> None:
    with _lock:
        _sessions.pop(sid, None)


# ──────────────────────────────────────────────────────────────
#  세션별 업로드 문서 저장소
# ──────────────────────────────────────────────────────────────
_docs: dict[str, list[dict]] = {}


def doc_list(sid: str) -> list[dict]:
    """UI에 내려줄 문서 목록 (청크 원문은 빼고)."""
    with _lock:
        return [
            {k: d[k] for k in ("id", "name", "pages", "chars", "chunks")}
            for d in _docs.get(sid, [])
        ]


def doc_add(sid: str, name: str, data: bytes) -> dict:
    """PDF를 파싱해 세션 문서 목록에 추가한다."""
    pages = pdfdoc.extract_pages(data)
    chunks = pdfdoc.build_chunks(pages)
    if not chunks:
        raise ValueError("PDF에서 읽을 수 있는 글자가 없었어요 🥲")

    doc = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "pages": len(pages),
        "chars": sum(len(c["text"]) for c in chunks),
        "chunks": len(chunks),
        "_chunks": chunks,
    }
    with _lock:
        _docs.setdefault(sid, []).append(doc)
    return {k: doc[k] for k in ("id", "name", "pages", "chars", "chunks")}


def doc_remove(sid: str, doc_id: str) -> None:
    with _lock:
        docs = _docs.get(sid, [])
        _docs[sid] = [d for d in docs if d["id"] != doc_id]


def doc_clear(sid: str) -> None:
    with _lock:
        _docs.pop(sid, None)


def build_context(sid: str, query: str) -> tuple[str, list[dict]]:
    """질의에 관련된 발췌문을 모아 프롬프트용 텍스트로 만든다."""
    with _lock:
        docs = list(_docs.get(sid, []))
    if not docs:
        return "", []

    # 문서별로 예산을 나눠 한 문서가 전체를 독식하지 않게 한다.
    budget = MAX_CONTEXT_CHARS // len(docs)
    blocks, sources = [], []
    for doc in docs:
        hits = pdfdoc.search(doc["_chunks"], query, budget)
        for chunk in hits:
            blocks.append(f"[{doc['name']} p.{chunk['page']}]\n{chunk['text']}")
            sources.append({"name": doc["name"], "page": chunk["page"]})

    header = (
        "다음은 사용자가 업로드한 문서에서 발췌한 내용이다. "
        "오직 이 내용만 근거로 답하라. 여기에 없는 정보는 모른다고 답하라.\n\n"
        "===== [문서 발췌] =====\n"
    )
    return header + "\n\n---\n\n".join(blocks) + "\n===== [발췌 끝] =====", sources


# ──────────────────────────────────────────────────────────────
#  OpenAI 호출
# ──────────────────────────────────────────────────────────────
def ask_openai(messages: list[dict], temperature: float = TEMPERATURE,
               max_tokens: int = MAX_COMPLETION_TOKENS,
               as_json: bool = False) -> tuple[str, dict]:
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "reasoning_effort": REASONING_EFFORT,
        "temperature": temperature,
    }
    if as_json:
        payload["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)

    choice = data["choices"][0]
    text = (choice["message"].get("content") or "").strip()
    if choice.get("finish_reason") == "length":
        if text:
            text += "\n\n…(토큰 한도에 닿아서 여기까지예요! 이어서 물어봐 주세요 ✨)"
        else:
            text = "앗, 답이 너무 길어져서 토큰이 다 떨어졌어요 😵 조금만 좁혀서 물어봐 주실래요?"
    return text or "…(칩이가 그만 할 말을 잃었어요)", data.get("usage", {})


# ──────────────────────────────────────────────────────────────
#  HTTP 핸들러
# ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "ChipiChat/1.0"

    def log_message(self, fmt, *args):  # 접속 로그는 조용히
        pass

    # ---- helpers ----
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    # ---- routes ----
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, (BASE_DIR / "index.html").read_bytes(),
                       "text/html; charset=utf-8")
        elif path == "/api/config":
            self._json(200, {
                "model": MODEL,
                "max_tokens": MAX_COMPLETION_TOKENS,
                "memory_turns": MEMORY_TURNS,
                "max_upload_mb": MAX_UPLOAD_MB,
            })
        else:
            self._send(404, b"Not Found", "text/plain; charset=utf-8")

    def _handle_mail_send(self, sid: str, body: dict):
        to = (body.get("to") or "").strip() or mailsend.load_settings()["default_to"]
        if not to:
            return self._json(400, {"error": "받는 사람을 먼저 정해주세요 📮"})

        history = get_history(sid)
        if not history:
            return self._json(400, {"error": "아직 정리해서 보낼 대화가 없어요 🥲"})

        # 1) 대화 요약 (채팅과 별개 호출 · JSON 강제)
        try:
            raw, usage = ask_openai(
                mailsend.summary_messages(history),
                temperature=0.3, max_tokens=MAIL_SUMMARY_MAX_TOKENS, as_json=True)
            summary = json.loads(raw)
        except urllib.error.HTTPError as e:
            print(f"[메일 요약 API 오류] {e.code}")
            return self._json(502, {"error": f"요약 중 API 오류가 났어요 ({e.code})"})
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[메일 요약 파싱 실패] {type(e).__name__}: {e}")
            return self._json(502, {"error": "요약 결과를 읽지 못했어요. 다시 시도해 주세요."})
        except Exception as e:
            print(f"[메일 요약 오류] {type(e).__name__}: {e}")
            return self._json(502, {"error": f"요약에 실패했어요 ({type(e).__name__})"})

        # 2) 발송
        subject = f"[칩이] {summary.get('subject') or '대화 요약'}"
        try:
            sent = mailsend.send(
                to, subject,
                mailsend.render_html(summary, history, MODEL),
                mailsend.render_text(summary, history))
        except KeyError as e:
            return self._json(400, {"error": str(e).strip('"')})
        except Exception as e:
            print(f"[메일 발송 오류] {type(e).__name__}: {e}")
            return self._json(502, {"error": f"메일 발송에 실패했어요 ({type(e).__name__})"})

        print(f"[메일] {subject} -> {', '.join(sent)}")
        return self._json(200, {
            "sent": sent,
            "subject": subject,
            "turns": len(history) // 2,
            "usage": usage,
        })

    def _handle_upload(self, sid: str, body: dict):
        name = (body.get("name") or "문서.pdf").strip()
        if not name.lower().endswith(".pdf"):
            return self._json(400, {"error": "아직은 PDF만 읽을 수 있어요 📄"})

        try:
            data = base64.b64decode(body.get("data") or "", validate=True)
        except (binascii.Error, ValueError):
            return self._json(400, {"error": "파일을 옮기다 깨진 것 같아요. 다시 올려주세요."})

        if not data:
            return self._json(400, {"error": "빈 파일이에요."})
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            return self._json(413, {"error": f"파일이 너무 커요. {MAX_UPLOAD_MB}MB까지 받을 수 있어요."})
        if not data.startswith(b"%PDF"):
            return self._json(400, {"error": "PDF 파일이 아닌 것 같아요 🤔"})

        try:
            info = doc_add(sid, name, data)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            print(f"[PDF 오류] {type(e).__name__}: {e}")
            return self._json(500, {"error": f"PDF를 읽다가 문제가 생겼어요 ({type(e).__name__})"})

        print(f"[업로드] {name} · {info['pages']}p · {info['chars']:,}자 · {info['chunks']}청크")
        return self._json(200, {"doc": info, "docs": doc_list(sid)})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": "잘못된 요청 형식이에요."})

        sid = str(body.get("sid") or "default")

        if path == "/api/reset":
            forget(sid)
            return self._json(200, {"ok": True, "turns": 0})

        if path == "/api/docs":
            # 새로고침 후 문서 목록과 기억 턴 수를 함께 복원한다.
            return self._json(200, {
                "docs": doc_list(sid),
                "turns": len(get_history(sid)) // 2,
            })

        if path == "/api/mail/config":
            return self._json(200, {
                "available": mailsend.available(),
                "default_to": mailsend.load_settings()["default_to"],
                "book": mailsend.address_book(),
            })

        if path == "/api/mail/save":
            saved = mailsend.save_settings(body.get("to") or "")
            return self._json(200, {"default_to": saved["default_to"]})

        if path == "/api/mail/send":
            return self._handle_mail_send(sid, body)

        if path == "/api/upload":
            return self._handle_upload(sid, body)

        if path == "/api/doc_delete":
            if body.get("all"):
                doc_clear(sid)
            else:
                doc_remove(sid, str(body.get("id") or ""))
            return self._json(200, {"docs": doc_list(sid)})

        if path != "/api/chat":
            return self._send(404, b"Not Found", "text/plain; charset=utf-8")

        user_msg = (body.get("message") or "").strip()
        if not user_msg:
            return self._json(400, {"error": "메시지가 비어 있어요."})

        # 업로드된 문서가 있으면 → 근거 기반 전용 모드
        context, sources = build_context(sid, user_msg)
        doc_mode = bool(context)

        messages = [{"role": "system",
                     "content": DOC_SYSTEM_PROMPT if doc_mode else SYSTEM_PROMPT}]
        messages += get_history(sid)
        if doc_mode:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": user_msg})

        try:
            reply, usage = ask_openai(
                messages, DOC_TEMPERATURE if doc_mode else TEMPERATURE)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail)["error"]["message"]
            except Exception:
                detail = detail[:300]
            print(f"[API 오류 {e.code}] {detail}")
            return self._json(502, {"error": f"OpenAI API 오류 ({e.code}): {detail}"})
        except Exception as e:
            print(f"[오류] {type(e).__name__}: {e}")
            return self._json(502, {"error": f"통신 오류가 났어요 ({type(e).__name__})"})

        turns = remember(sid, user_msg, reply)
        cited = sorted({(s["name"], s["page"]) for s in sources})
        self._json(200, {
            "reply": reply,
            "turns": turns,
            "memory_turns": MEMORY_TURNS,
            "usage": usage,
            "doc_mode": doc_mode,
            "sources": [{"name": n, "page": p} for n, p in cited],
        })


# ──────────────────────────────────────────────────────────────
#  실행
# ──────────────────────────────────────────────────────────────
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    port = PORT
    for _ in range(10):
        try:
            httpd = ThreadingHTTPServer((HOST, port), Handler)
            break
        except OSError:
            port += 1
    else:
        sys.exit("[오류] 사용 가능한 포트를 찾지 못했습니다.")

    url = f"http://{HOST}:{port}"
    print("=" * 52)
    print("  칩이(Chip-i) · 삼성전자 DS 반도체 챗봇")
    print("=" * 52)
    print(f"  모델      : {MODEL}")
    print(f"  최대 토큰 : {MAX_COMPLETION_TOKENS} / 턴")
    print(f"  메모리    : 최근 {MEMORY_TURNS}턴")
    print(f"  주소      : {url}")
    print("  종료      : Ctrl + C")
    print("=" * 52)

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n칩이 전원을 내렸어요. 안녕히 가세요! 💙")
        httpd.shutdown()


if __name__ == "__main__":
    main()
