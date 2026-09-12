# -*- coding: utf-8 -*-
"""
judge_ai.py — AI 보조 판정/요약 (계획서 2.1 'AI 보조' + 4단계)

인증: OAuth (Claude Code CLI 헤드리스 호출).
  - 로컬: `claude` 로그인 세션 재사용 (API 키 불필요)
  - CI(GitHub Actions): 환경변수 CLAUDE_CODE_OAUTH_TOKEN 사용
        → `claude setup-token` 으로 발급

설계 원칙 (계획서 A12 교훈: 토큰 비용 붕괴 방지):
- 항목마다 호출하지 않는다. 카테고리별로 1회만 호출한다. (137건 → 호출 4회)
- 규칙 필터가 이미 노이즈를 제거한 뒤의 항목만 입력으로 준다.
- 모든 호출의 입력/출력 토큰과 CLI가 보고한 비용을 로깅한다. (V3 6번)
"""
import json, re, shutil, subprocess, sys

MODEL = "claude-haiku-4-5"


def find_claude():
    """PATH 에서 claude 실행 파일 탐색 (Windows: claude.cmd/claude.exe 포함)."""
    for name in ("claude", "claude.cmd", "claude.exe"):
        p = shutil.which(name)
        if p:
            return p
    return None


PROMPT = """당신은 데이터 분석가의 아침 브리핑을 돕는 편집자입니다.
아래는 '{cat}' 카테고리로 수집·정제된 오늘의 기사 목록입니다.

기사 목록:
{items}

다음을 한국어로 작성하세요. 엠대시(—)를 절대 쓰지 마세요.
1) "흐름 요약": 오늘 이 카테고리에서 무슨 일이 벌어지는지 3~5줄로. 개별 기사 나열이 아니라 관통하는 맥락 위주로.
2) "읽을 가치 높음": 위 목록 중 실무자가 꼭 열어볼 만한 기사 번호 최대 3개와 각각 한 줄 이유.

반드시 아래 JSON 형식으로만 출력하세요(코드블록 없이):
{{"summary": "흐름 요약 텍스트", "picks": [{{"n": 기사번호, "why": "한 줄 이유"}}]}}"""


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {"summary": text.strip(), "picks": []}


def summarize_category(claude_bin, cat, items, budget_state):
    """카테고리 1건 요약. Claude CLI 헤드리스 호출. budget_state 로 누적 추적."""
    listing = "\n".join(
        f"{i+1}. {it['title']} - {it['summary'][:80]}" for i, it in enumerate(items)
    )
    prompt = PROMPT.format(cat=cat, items=listing)
    proc = subprocess.run(
        [claude_bin, "-p", "--output-format", "json", "--model", MODEL],
        input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI 실패 (rc={proc.returncode}): {proc.stderr.strip()[:300]}")

    envelope = json.loads(proc.stdout)
    result_text = envelope.get("result", "")
    usage = envelope.get("usage", {}) or {}
    ti = usage.get("input_tokens", 0)
    to = usage.get("output_tokens", 0)
    budget_state["in"] += ti
    budget_state["out"] += to
    budget_state["calls"] += 1
    budget_state["cost"] += float(envelope.get("total_cost_usd", 0) or 0)

    data = _extract_json(result_text)
    data["_tokens"] = {"in": ti, "out": to}
    return data


WEEKLY_PROMPT = """당신은 데이터 분석가의 주간 브리핑 편집자입니다.
아래는 최근 7일간 날짜별·카테고리별 '오늘의 흐름' 요약 모음입니다.

{blob}

이번 주를 관통하는 큰 흐름 3가지를 한국어로 뽑아 각각 1~2문장으로 쓰세요.
개별 날짜 나열이 아니라 주간 관점의 변화·반복·신호 위주로. 엠대시(—)는 쓰지 마세요.
번호 목록(1. 2. 3.) 형식의 텍스트로만 출력하세요."""


WEEKLY_CAT_PROMPT = """당신은 데이터 분석가의 주간 브리핑 편집자입니다.
아래는 최근 며칠간 '{cat}' 분야의 일별 '오늘의 흐름' 요약입니다.

{blob}

이 '{cat}' 분야에서 이번 주를 관통하는 흐름을 한국어로 3~4줄로 요약하세요.
개별 날짜 나열이 아니라 주간 관점의 변화·반복·신호 위주로. 엠대시(—)는 쓰지 마세요. 문장 텍스트로만 출력하세요."""


def weekly_category(claude_bin, cat: str, blob: str, budget_state) -> str:
    """한 카테고리의 최근 일별 요약을 받아 그 분야의 '이번 주 흐름' 생성."""
    proc = subprocess.run(
        [claude_bin, "-p", "--output-format", "json", "--model", MODEL],
        input=WEEKLY_CAT_PROMPT.format(cat=cat, blob=blob),
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI 실패 (rc={proc.returncode}): {proc.stderr.strip()[:300]}")
    envelope = json.loads(proc.stdout)
    usage = envelope.get("usage", {}) or {}
    budget_state["in"] += usage.get("input_tokens", 0)
    budget_state["out"] += usage.get("output_tokens", 0)
    budget_state["calls"] += 1
    budget_state["cost"] += float(envelope.get("total_cost_usd", 0) or 0)
    return (envelope.get("result", "") or "").strip()


def weekly_synthesis(claude_bin, daily_summaries: str, budget_state) -> str:
    """7일치 요약 모음(텍스트)을 받아 '이번 주 흐름 3가지' 생성. 실패 시 예외."""
    proc = subprocess.run(
        [claude_bin, "-p", "--output-format", "json", "--model", MODEL],
        input=WEEKLY_PROMPT.format(blob=daily_summaries),
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI 실패 (rc={proc.returncode}): {proc.stderr.strip()[:300]}")
    envelope = json.loads(proc.stdout)
    usage = envelope.get("usage", {}) or {}
    budget_state["in"] += usage.get("input_tokens", 0)
    budget_state["out"] += usage.get("output_tokens", 0)
    budget_state["calls"] += 1
    budget_state["cost"] += float(envelope.get("total_cost_usd", 0) or 0)
    return (envelope.get("result", "") or "").strip()
