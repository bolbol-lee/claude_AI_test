# -*- coding: utf-8 -*-
"""
PDF 텍스트 추출 · 청킹 · 질의 관련 청크 검색.

외부 API 없이 로컬에서만 동작한다.
추출: PyMuPDF(fitz) → pypdf → pdfplumber 순으로 시도.
검색: 한국어/영어 혼용을 고려한 경량 BM25 유사 스코어링.
"""

import io
import math
import re
from collections import Counter

# 청킹 설정
CHUNK_CHARS = 1000      # 청크 하나의 목표 길이
CHUNK_OVERLAP = 150     # 청크 간 겹침 (문장이 잘려도 문맥 유지)


# ──────────────────────────────────────────────────────────────
#  1. 텍스트 추출
# ──────────────────────────────────────────────────────────────
def _extract_fitz(data: bytes) -> list[str]:
    import fitz
    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass:
            raise ValueError("암호가 걸린 PDF예요. 암호를 푼 파일로 올려주세요.")
        return [page.get_text("text") or "" for page in doc]


def _extract_pypdf(data: bytes) -> list[str]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("암호가 걸린 PDF예요. 암호를 푼 파일로 올려주세요.")
    return [(p.extract_text() or "") for p in reader.pages]


def _extract_pdfplumber(data: bytes) -> list[str]:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def _clean(text: str) -> str:
    """추출 과정에서 생긴 과한 공백/개행 정리."""
    text = text.replace("\xa0", " ").replace("​", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(data: bytes) -> list[str]:
    """PDF 바이트에서 페이지별 텍스트를 뽑는다. 실패 시 ValueError."""
    errors = []
    for fn in (_extract_fitz, _extract_pypdf, _extract_pdfplumber):
        try:
            pages = [_clean(t) for t in fn(data)]
            if any(p.strip() for p in pages):
                return pages
            errors.append(f"{fn.__name__}: 텍스트 없음")
        except ValueError:
            raise
        except Exception as e:
            errors.append(f"{fn.__name__}: {type(e).__name__}")

    raise ValueError(
        "PDF에서 글자를 찾지 못했어요. 스캔 이미지로만 된 PDF일 수 있어요 "
        "(칩이는 아직 OCR을 못 해요 🥲)"
    )


# ──────────────────────────────────────────────────────────────
#  2. 청킹
# ──────────────────────────────────────────────────────────────
def build_chunks(pages: list[str]) -> list[dict]:
    """페이지별 텍스트를 페이지 번호가 붙은 청크 리스트로 자른다."""
    chunks: list[dict] = []
    for pageno, text in enumerate(pages, start=1):
        text = text.strip()
        if not text:
            continue

        # 문단 단위로 모으다가 CHUNK_CHARS를 넘으면 끊는다.
        buf = ""
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            if len(buf) + len(para) + 1 <= CHUNK_CHARS:
                buf = f"{buf}\n{para}" if buf else para
                continue

            if buf:
                chunks.append({"page": pageno, "text": buf})
                buf = buf[-CHUNK_OVERLAP:] if len(buf) > CHUNK_OVERLAP else ""

            # 문단 자체가 너무 길면 강제로 잘라낸다.
            while len(para) > CHUNK_CHARS:
                chunks.append({"page": pageno, "text": para[:CHUNK_CHARS]})
                para = para[CHUNK_CHARS - CHUNK_OVERLAP:]
            buf = f"{buf}\n{para}".strip() if buf else para

        if buf.strip():
            chunks.append({"page": pageno, "text": buf.strip()})

    return chunks


# ──────────────────────────────────────────────────────────────
#  3. 검색 (경량 BM25)
# ──────────────────────────────────────────────────────────────
_HANGUL = re.compile(r"[가-힣]+")
_LATIN = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """한글은 2-gram, 영문/숫자는 단어 단위로 토큰화한다."""
    tokens = [w.lower() for w in _LATIN.findall(text) if len(w) > 1]
    for word in _HANGUL.findall(text):
        if len(word) == 1:
            tokens.append(word)
        else:
            tokens.extend(word[i:i + 2] for i in range(len(word) - 1))
    return tokens


def search(chunks: list[dict], query: str, limit_chars: int) -> list[dict]:
    """질의와 관련 높은 청크를 limit_chars 예산 안에서 골라 원문 순서로 반환."""
    q_tokens = set(tokenize(query))
    if not q_tokens or not chunks:
        return _take_until(chunks, limit_chars)

    docs = [Counter(tokenize(c["text"])) for c in chunks]
    n = len(docs)
    avg_len = sum(sum(d.values()) for d in docs) / n or 1
    k1, b = 1.5, 0.75

    # 토큰별 문서빈도 → idf
    df = Counter()
    for d in docs:
        df.update(q_tokens & d.keys())

    scored = []
    for i, d in enumerate(docs):
        dl = sum(d.values()) or 1
        score = 0.0
        for t in q_tokens:
            f = d.get(t, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avg_len))
        if score > 0:
            scored.append((score, i))

    if not scored:
        return _take_until(chunks, limit_chars)

    scored.sort(reverse=True)
    picked, used = [], 0
    for _, i in scored:
        size = len(chunks[i]["text"])
        if used + size > limit_chars:
            continue
        picked.append(i)
        used += size
    if not picked:                      # 첫 청크가 예산보다 큰 경우
        picked = [scored[0][1]]

    picked.sort()                       # 원문 순서 유지
    return [chunks[i] for i in picked]


def _take_until(chunks: list[dict], limit_chars: int) -> list[dict]:
    """질의 매칭이 없을 때는 앞에서부터 예산만큼 담는다."""
    out, used = [], 0
    for c in chunks:
        if used + len(c["text"]) > limit_chars:
            break
        out.append(c)
        used += len(c["text"])
    return out or chunks[:1]
