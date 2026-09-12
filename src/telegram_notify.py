# -*- coding: utf-8 -*-
"""
telegram_notify.py — 오늘자 Daily Brief를 텔레그램으로 발송한다.

수집/AI 호출을 다시 하지 않는다. report.py 가 이미 남긴 산출물만 재활용한다:
  - data/picks_{날짜}.json    : 선별 기사(제목·링크·why)
  - data/ai_cache_{날짜}.json : 카테고리별 흐름 요약
  - data/stats/{날짜}.json    : 수집/선별 건수

인증(환경변수):
  TELEGRAM_BOT_TOKEN  : @BotFather 로 발급
  TELEGRAM_CHAT_ID    : 봇과 대화 후 getUpdates 로 확인 (개인/그룹/채널 id)
  SITE_URL (선택)     : 전체 리포트 링크 (예: https://<나>.github.io/<repo>/)

토큰/chat_id 가 없으면 조용히 스킵(exit 0)한다 — 포크해도 파이프라인이 깨지지 않는다.
발송 실패도 파이프라인을 막지 않는다(전달은 best-effort 부가 기능).

사용:
  python src/telegram_notify.py            # 실제 발송
  python src/telegram_notify.py --dry-run  # 발송 없이 메시지만 출력(동작 확인용)
  python src/telegram_notify.py --date 2026-09-12
"""
import argparse
import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
KST = datetime.timezone(datetime.timedelta(hours=9))
CAT_ORDER = ["경제", "사회", "연예", "실무", "내소스"]
CAT_EMOJI = {"경제": "💹", "사회": "🏛️", "연예": "🎬", "실무": "🛠️", "내소스": "📌"}

TG_LIMIT = 4096
CHUNK_SOFT = 3800          # 안전 여유를 둔 분할 기준
SUMMARY_MAX = 500          # 카테고리 흐름 요약 상한(보통 150~300자라 사실상 통째로 보냄)
WHY_MAX = 100              # 기사별 why 자르는 길이


def esc(s: object) -> str:
    """텔레그램 HTML 파싱용 이스케이프.

    텔레그램 HTML 모드는 & < > 세 가지만 확실히 지원하므로 이것만 변환한다
    (html.escape 기본값처럼 따옴표를 &#x27;/&quot; 로 바꾸면 그대로 노출됨).
    URL(href)도 & 만 escape 하면 되고, 따옴표는 URL에 사실상 없다.
    """
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def load_json(path: pathlib.Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def build_blocks(date: str) -> list[str]:
    """발송할 텍스트를 '블록' 단위(헤더/카테고리별/푸터)로 만든다.

    블록 단위로 나눠 두면 4096자 제한에 맞춰 메시지로 재조립하기 쉽다.
    """
    picks = load_json(ROOT / "data" / f"picks_{date}.json", [])
    cache = load_json(ROOT / "data" / f"ai_cache_{date}.json", {})
    stats = load_json(ROOT / "data" / "stats" / f"{date}.json", {})

    blocks: list[str] = []

    total = stats.get("total")
    pick_n = stats.get("pick_count", len(picks))
    head = f"📰 <b>Daily Brief</b> · {esc(date)}"
    if total is not None:
        head += f"\n🗂️ 수집 <b>{total}건</b> → ⭐ 핵심 <b>{pick_n}건</b>"
    blocks.append(head)

    # 카테고리별: 흐름 요약 + 선별 기사
    by_cat: dict[str, list[dict]] = {}
    for it in picks:
        by_cat.setdefault(it.get("cat", ""), []).append(it)

    for cat in CAT_ORDER:
        items = by_cat.get(cat, [])
        # 오늘 선별된 기사가 없으면 카테고리 자체를 뺀다.
        # (요약은 ai_cache 에서 오는데, 소스 변경 전 캐시가 남아 있을 수 있어
        #  기사 0건인데 옛 요약만 유령처럼 붙는 것을 막는다.)
        if not items:
            continue
        summary = ""
        c = cache.get(cat)
        if isinstance(c, dict):
            summary = c.get("summary", "")

        lines = [f"{CAT_EMOJI.get(cat, '')} <b>{esc(cat)}</b>"]
        if summary:
            lines.append(f"<i>{esc(clip(summary, SUMMARY_MAX))}</i>")
        for it in items:
            title = esc(clip(it.get("title", ""), 90))
            link = esc(it.get("link", ""))
            row = f"• <a href=\"{link}\">{title}</a>" if link else f"• {title}"
            why = clip(it.get("why", ""), WHY_MAX)
            if why:
                row += f"\n   ↳ {esc(why)}"
            lines.append(row)
        blocks.append("\n".join(lines))

    site = os.environ.get("SITE_URL", "").strip()
    if site:
        blocks.append(f"🔗 <a href=\"{esc(site)}\">전체 리포트 보기</a>")

    return blocks


def pack_messages(blocks: list[str]) -> list[str]:
    """블록들을 텔레그램 길이 제한에 맞는 메시지 여러 개로 묶는다."""
    messages: list[str] = []
    cur = ""
    for b in blocks:
        # 단일 블록이 한도를 넘으면 줄 단위로 강제 분할
        if len(b) > CHUNK_SOFT:
            if cur:
                messages.append(cur)
                cur = ""
            piece = ""
            for line in b.split("\n"):
                if len(piece) + len(line) + 1 > CHUNK_SOFT:
                    if piece:
                        messages.append(piece)
                    piece = line
                else:
                    piece = f"{piece}\n{line}" if piece else line
            if piece:
                cur = piece
            continue

        if not cur:
            cur = b
        elif len(cur) + len(b) + 2 <= CHUNK_SOFT:
            cur = f"{cur}\n\n{b}"
        else:
            messages.append(cur)
            cur = b
    if cur:
        messages.append(cur)
    return messages


def send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="발송하지 않고 메시지만 출력")
    ap.add_argument("--date", default=datetime.datetime.now(KST).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    blocks = build_blocks(args.date)
    if len(blocks) <= 1:  # 헤더뿐이면 발송할 내용이 없음
        print(f"[telegram] {args.date} 발송할 브리핑 데이터가 없습니다 — 스킵")
        return 0

    messages = pack_messages(blocks)

    if args.dry_run:
        print(f"[telegram] --dry-run: 메시지 {len(messages)}개 (실제 발송 안 함)\n")
        for i, m in enumerate(messages, 1):
            print(f"----- 메시지 {i}/{len(messages)} ({len(m)}자) -----")
            print(m)
            print()
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[telegram] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 미설정 — 발송 스킵(정상)")
        return 0

    sent = 0
    for i, m in enumerate(messages, 1):
        try:
            send_message(token, chat_id, m)
            sent += 1
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            print(f"[telegram] 발송 실패 {i}/{len(messages)} (HTTP {e.code}): {body}")
        except Exception as e:  # 네트워크 등 — 파이프라인은 막지 않는다
            print(f"[telegram] 발송 실패 {i}/{len(messages)}: {e}")
    print(f"[telegram] 발송 완료 {sent}/{len(messages)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
