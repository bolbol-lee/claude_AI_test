# -*- coding: utf-8 -*-
"""네이버 SMTP 메일 발송 공용 모듈.

계정 정보는 네이버SMTP계정정보.txt, 수신인은 수신인정보.txt에서 읽는다.
두 파일 모두 사용자가 계속 갱신하므로 발송 시점에 항상 새로 읽는다.

사용 예:
    from mailer import send_mail
    send_mail("대우", "제목", html=html_str, attachments=["report.xlsx"])

CLI:
    python mailer.py --to 대우 --subject "제목" --html body.html --attach report.xlsx
"""
from __future__ import annotations

import argparse
import mimetypes
import re
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ACCOUNT_FILE = BASE_DIR / "네이버SMTP계정정보.txt"
RECIPIENT_FILE = BASE_DIR / "수신인정보.txt"

SMTP_HOST = "smtp.naver.com"
SMTP_PORT = 587

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_account() -> tuple[str, str]:
    """네이버SMTP계정정보.txt에서 (아이디, 비밀번호)를 읽는다."""
    text = ACCOUNT_FILE.read_text(encoding="utf-8")
    user = re.search(r"아이디\s*[:：]\s*(\S+)", text)
    pw = re.search(r"비밀번호[^:：\n]*[:：]\s*(\S+)", text)
    if not user or not pw:
        raise ValueError(f"{ACCOUNT_FILE.name}에서 아이디/비밀번호를 찾지 못했습니다.")
    return user.group(1), pw.group(1)


def load_address_book() -> tuple[dict[str, str], dict[str, list[str]]]:
    """수신인정보.txt를 파싱해 (이름→주소, 그룹→주소목록)을 돌려준다.

    '## 그룹명' 아래 '- 이름 : 주소' 형식. 주소가 비어 있는 항목은 건너뛴다.
    """
    names: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    current = None
    if not RECIPIENT_FILE.exists():
        return names, groups
    for line in RECIPIENT_FILE.read_text(encoding="utf-8").splitlines():
        header = re.match(r"\s*#+\s*(.+?)\s*$", line)
        if header:
            current = header.group(1)
            groups.setdefault(current, [])
            continue
        entry = re.match(r"\s*[-*]\s*(.+?)\s*[:：]\s*(\S+)?\s*$", line)
        if entry and entry.group(2) and EMAIL_RE.match(entry.group(2)):
            name, addr = entry.group(1), entry.group(2)
            names[name] = addr
            if current:
                groups[current].append(addr)
    return names, groups


def resolve(to) -> list[str]:
    """이메일 주소, 주소록의 이름, 그룹명이 섞인 입력을 주소 목록으로 바꾼다."""
    if isinstance(to, str):
        to = [t.strip() for t in re.split(r"[,;]", to) if t.strip()]
    names, groups = load_address_book()
    out: list[str] = []
    for item in to:
        if EMAIL_RE.match(item):
            out.append(item)
        elif item in names:
            out.append(names[item])
        elif item in groups and groups[item]:
            out.extend(groups[item])
        else:
            raise KeyError(
                f"'{item}'의 이메일 주소를 찾을 수 없습니다. "
                f"{RECIPIENT_FILE.name}에 등록된 이름: {', '.join(names) or '(없음)'}"
            )
    return list(dict.fromkeys(out))


def _attach(msg: MIMEMultipart, path: str | Path) -> None:
    path = Path(path)
    ctype, _ = mimetypes.guess_type(path.name)
    subtype = ctype.split("/", 1)[1] if ctype else "octet-stream"
    part = MIMEApplication(path.read_bytes(), _subtype=subtype)
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", path.name))
    msg.attach(part)


def send_mail(to, subject: str, html: str | None = None, text: str | None = None,
              attachments=None, cc=None) -> list[str]:
    """메일을 보내고 실제 발송된 주소 목록을 돌려준다."""
    if not html and not text:
        raise ValueError("html 또는 text 중 하나는 있어야 합니다.")
    user, pw = load_account()
    sender = f"{user}@naver.com"
    to_addrs = resolve(to)
    cc_addrs = resolve(cc) if cc else []

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)

    alt = MIMEMultipart("alternative")
    if text:
        alt.attach(MIMEText(text, "plain", "utf-8"))
    if html:
        alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)

    for path in attachments or []:
        _attach(msg, path)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(user, pw)
        server.sendmail(sender, to_addrs + cc_addrs, msg.as_string())
    return to_addrs + cc_addrs


def main() -> None:
    p = argparse.ArgumentParser(description="네이버 SMTP로 메일 발송")
    p.add_argument("--to", help="이메일 주소 / 주소록 이름 / 그룹명 (쉼표 구분)")
    p.add_argument("--cc")
    p.add_argument("--subject")
    p.add_argument("--html", help="HTML 본문 파일 경로")
    p.add_argument("--text", help="텍스트 본문 (문자열 또는 파일 경로)")
    p.add_argument("--attach", nargs="*", default=[], help="첨부파일 경로")
    p.add_argument("--list", action="store_true", help="주소록만 출력하고 종료")
    args = p.parse_args()

    if args.list:
        names, groups = load_address_book()
        for group, addrs in groups.items():
            print(f"[{group}]")
            for name, addr in names.items():
                if addr in addrs:
                    print(f"  {name} : {addr}")
            if not addrs:
                print("  (등록된 주소 없음)")
        return

    if not args.to or not args.subject:
        p.error("--to 와 --subject 는 필수입니다 (주소록만 볼 때는 --list).")

    html = Path(args.html).read_text(encoding="utf-8") if args.html else None
    text = args.text
    if text and Path(text).exists():
        text = Path(text).read_text(encoding="utf-8")

    sent = send_mail(args.to, args.subject, html=html, text=text, attachments=args.attach)
    print("SENT ->", ", ".join(sent))


if __name__ == "__main__":
    main()
