# -*- coding: utf-8 -*-
"""
interests.py — 사용자 관심 키워드 로드/매칭.

interests.txt(루트)에 관심 키워드를 줄 단위로 둔다(# 주석 허용).
report.py 가 이를 이용해 '관심 키워드' 전용 섹션을 만든다.
결정론적 문자열 매칭이라 왜 뽑혔는지 설명 가능하다.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load() -> list[str]:
    """interests.txt 의 키워드 목록(원문 표기 유지). 없으면 빈 리스트."""
    path = ROOT / "interests.txt"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        kw = line.strip()
        if kw and not kw.startswith("#"):
            out.append(kw)
    return out


def match(text: str, interests: list[str]) -> list[str]:
    """text 에 등장한 관심 키워드(고유, 대소문자 무시). 매칭 없으면 빈 리스트."""
    low = (text or "").lower()
    return [kw for kw in interests if kw.lower() in low]
