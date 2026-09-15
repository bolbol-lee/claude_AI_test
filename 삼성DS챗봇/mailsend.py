# -*- coding: utf-8 -*-
"""
대화 요약 메일 발송.

발송 자체는 옆 프로젝트의 공용 모듈을 그대로 가져다 쓴다:
    C:\\AI\\삼성DS이메일자동화\\mailer.py
계정 정보와 주소록도 그쪽 파일(네이버SMTP계정정보.txt / 수신인정보.txt)을 따른다.
"""

import html as html_mod
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAILER_DIR = Path(r"C:\AI\삼성DS이메일자동화")
SETTINGS_FILE = BASE_DIR / "mail_settings.json"

SAMSUNG_BLUE = "#1428A0"
BLUE_500 = "#2B4ACB"


# ──────────────────────────────────────────────────────────────
#  mailer.py 연결
# ──────────────────────────────────────────────────────────────
def get_mailer():
    """옆 프로젝트의 mailer 모듈을 로드한다. 없으면 RuntimeError."""
    if not (MAILER_DIR / "mailer.py").exists():
        raise RuntimeError(f"메일 모듈을 찾지 못했어요: {MAILER_DIR / 'mailer.py'}")
    if str(MAILER_DIR) not in sys.path:
        sys.path.insert(0, str(MAILER_DIR))
    return importlib.import_module("mailer")


def available() -> bool:
    try:
        get_mailer()
        return True
    except Exception:
        return False


def address_book() -> list[dict]:
    """주소록을 [{name, addr}] 형태로. 실패하면 빈 목록."""
    try:
        names, _ = get_mailer().load_address_book()
        return [{"name": n, "addr": a} for n, a in names.items()]
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────
#  고정 수신인 설정
# ──────────────────────────────────────────────────────────────
def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"default_to": ""}


def save_settings(default_to: str) -> dict:
    data = {"default_to": (default_to or "").strip()}
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return data


# ──────────────────────────────────────────────────────────────
#  요약 프롬프트
# ──────────────────────────────────────────────────────────────
SUMMARY_SYSTEM = """너는 대화 기록을 업무 메일용으로 정리하는 요약 담당이야.
아래 대화는 '칩이'라는 반도체 챗봇과 사용자가 나눈 것이다.

규칙:
- 대화에 실제로 나온 내용만 쓴다. 없는 내용을 채워 넣지 마라.
- 수치·고유명사는 대화에 나온 그대로 인용한다.
- 문서 기반 답변이었다면 출처 표기도 살린다.
- 담백한 업무 문체(~함, ~임)로 쓴다. 이모지는 쓰지 마라.

반드시 아래 JSON 스키마 그대로 출력해라:
{
  "subject": "메일 제목 (25자 내외, 대화 주제를 담아)",
  "headline": "대화 전체를 한 문장으로",
  "summary": ["핵심 내용 불릿 3~5개"],
  "qa": [{"q": "사용자가 물은 것", "a": "칩이가 답한 핵심 (1~2문장)"}],
  "keywords": ["키워드 3~6개"],
  "actions": ["후속 확인이 필요한 항목 0~4개 (없으면 빈 배열)"]
}"""


def summary_messages(history: list[dict]) -> list[dict]:
    """요약 API 호출에 쓸 messages를 만든다."""
    lines = []
    for i, msg in enumerate(history):
        who = "사용자" if msg["role"] == "user" else "칩이"
        lines.append(f"[{i // 2 + 1}턴 · {who}]\n{msg['content']}")
    convo = "\n\n".join(lines)
    return [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {"role": "user", "content": f"다음 대화를 정리해줘.\n\n===== 대화 기록 =====\n{convo}"},
    ]


# ──────────────────────────────────────────────────────────────
#  메일 본문 렌더링
# ──────────────────────────────────────────────────────────────
def _e(s) -> str:
    return html_mod.escape(str(s or ""))


def render_html(data: dict, history: list[dict], model: str) -> str:
    """삼성블루 테마의 테이블 기반 HTML 메일 본문."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    turns = len(history) // 2

    def card(title: str, inner: str) -> str:
        return f"""
        <tr><td style="padding:0 28px 18px;">
          <div style="font-size:12px;font-weight:700;color:{SAMSUNG_BLUE};
                      letter-spacing:.4px;margin-bottom:8px;">{title}</div>
          {inner}
        </td></tr>"""

    summary_items = "".join(
        f'<li style="margin:0 0 6px;line-height:1.75;">{_e(s)}</li>'
        for s in data.get("summary", []))
    summary_block = (
        f'<ul style="margin:0;padding-left:18px;font-size:14px;color:#18204A;">'
        f'{summary_items}</ul>') if summary_items else ""

    qa_block = "".join(f"""
        <div style="border:1px solid #D6DEF5;border-radius:10px;
                    padding:12px 14px;margin-bottom:8px;background:#FFFFFF;">
          <div style="font-size:13px;font-weight:700;color:{SAMSUNG_BLUE};
                      margin-bottom:5px;">Q. {_e(item.get('q'))}</div>
          <div style="font-size:13.5px;color:#3A4472;line-height:1.75;">
            A. {_e(item.get('a'))}</div>
        </div>""" for item in data.get("qa", []))

    kw_block = "".join(f"""
        <span style="display:inline-block;background:#EEF3FE;color:{BLUE_500};
                     border:1px solid #DDE5FB;border-radius:999px;
                     padding:4px 11px;font-size:12px;font-weight:700;
                     margin:0 5px 5px 0;">#{_e(k)}</span>"""
        for k in data.get("keywords", []))

    act_items = "".join(
        f'<li style="margin:0 0 6px;line-height:1.75;">{_e(a)}</li>'
        for a in data.get("actions", []))
    act_block = (
        f'<ul style="margin:0;padding-left:18px;font-size:14px;color:#18204A;">'
        f'{act_items}</ul>') if act_items else ""

    transcript = "".join(f"""
        <div style="margin-bottom:10px;">
          <div style="font-size:11px;font-weight:700;
                      color:{'#1428A0' if m['role'] == 'user' else '#5A6591'};
                      margin-bottom:3px;">
            {'🙋 사용자' if m['role'] == 'user' else '🔷 칩이'}</div>
          <div style="font-size:12.5px;color:#4A5480;line-height:1.7;
                      white-space:pre-wrap;">{_e(m['content'])}</div>
        </div>""" for m in history)

    return f"""<!doctype html>
<html><body style="margin:0;padding:24px 12px;background:#F4F7FE;
      font-family:'Malgun Gothic','맑은 고딕','Apple SD Gothic Neo',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="max-width:640px;margin:0 auto;background:#FFFFFF;
              border-radius:18px;overflow:hidden;
              box-shadow:0 10px 30px -18px rgba(20,40,160,.5);">

  <tr><td style="background:{SAMSUNG_BLUE};padding:26px 28px;">
    <div style="font-size:11px;color:#C9D6FF;letter-spacing:2px;
                font-weight:700;margin-bottom:7px;">SAMSUNG DS · CHIP-i</div>
    <div style="font-size:21px;color:#FFFFFF;font-weight:800;
                line-height:1.4;">{_e(data.get('headline') or '대화 요약')}</div>
    <div style="font-size:12px;color:#C9D6FF;margin-top:9px;">
      {now} · 최근 {turns}턴 · {_e(model)}</div>
  </td></tr>

  <tr><td style="height:18px;"></td></tr>

  {card("한눈에 보기", summary_block) if summary_block else ""}
  {card("주요 문답", qa_block) if qa_block else ""}
  {card("키워드", kw_block) if kw_block else ""}
  {card("확인이 필요한 것", act_block) if act_block else ""}

  <tr><td style="padding:4px 28px 22px;">
    <div style="font-size:12px;font-weight:700;color:{SAMSUNG_BLUE};
                letter-spacing:.4px;margin-bottom:8px;">전체 대화 기록</div>
    <div style="background:#F7F9FE;border:1px solid #E3EAF9;
                border-radius:12px;padding:14px 16px;">{transcript}</div>
  </td></tr>

  <tr><td style="background:#F7F9FE;border-top:1px solid #E3EAF9;
                 padding:16px 28px;text-align:center;">
    <div style="font-size:11px;color:#8A94BD;line-height:1.7;">
      칩이(Chip-i) 반도체 챗봇이 자동으로 정리해 보낸 메일입니다.<br>
      요약은 AI가 생성한 것이라 원문과 다를 수 있으니 전체 대화 기록을 함께 확인해 주세요.
    </div>
  </td></tr>
</table>
</body></html>"""


def render_text(data: dict, history: list[dict]) -> str:
    """HTML을 못 읽는 클라이언트용 대체 본문."""
    out = [data.get("headline") or "대화 요약", "=" * 40, ""]
    if data.get("summary"):
        out += ["[한눈에 보기]"] + [f"- {s}" for s in data["summary"]] + [""]
    for item in data.get("qa", []):
        out += [f"Q. {item.get('q')}", f"A. {item.get('a')}", ""]
    if data.get("keywords"):
        out += ["[키워드] " + ", ".join(data["keywords"]), ""]
    if data.get("actions"):
        out += ["[확인 필요]"] + [f"- {a}" for a in data["actions"]] + [""]

    out += ["-" * 40, "[전체 대화 기록]", ""]
    for m in history:
        out += [f"{'사용자' if m['role'] == 'user' else '칩이'}: {m['content']}", ""]
    return "\n".join(out)


# ──────────────────────────────────────────────────────────────
#  발송
# ──────────────────────────────────────────────────────────────
def send(to: str, subject: str, html: str, text: str) -> list[str]:
    """mailer.send_mail 위임. 실패 시 예외를 그대로 올린다."""
    return get_mailer().send_mail(to, subject, html=html, text=text)
