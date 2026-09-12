# -*- coding: utf-8 -*-
"""
telegram_notify.py — 오늘자 Daily Brief를 텔레그램으로 발송한다(증분 방식).

수집/AI 호출을 다시 하지 않는다. report.py 가 이미 남긴 산출물만 재활용한다:
  - data/picks_{날짜}.json    : 선별 기사(제목·링크·why·hash)
  - data/ai_cache_{날짜}.json : 카테고리별 흐름 요약
  - data/stats/{날짜}.json    : 수집/선별 건수

증분 발송(하루 여러 번 실행 대비):
  - data/sent_{날짜}.json 에 이미 발송한 기사 hash 를 기록한다.
  - 다음 실행 땐 아직 안 보낸 픽만 발송한다(같은 기사 중복 방지).
  - 그날 첫 발송(아침) = 전체 브리핑, 이후(점심/저녁) = 새로 뜬 소식만.
  - sent 파일은 날짜별이라 다음날이면 자동 리셋 → 다시 전체 브리핑.

인증(환경변수):
  TELEGRAM_BOT_TOKEN  : @BotFather 로 발급
  TELEGRAM_CHAT_ID    : 봇과 대화 후 getUpdates 로 확인
  SITE_URL (선택)     : 전체 리포트 링크

토큰이 없으면 조용히 스킵(exit 0). 발송 실패도 파이프라인을 막지 않는다.

사용:
  python src/telegram_notify.py            # 실제 발송(+ sent 기록)
  python src/telegram_notify.py --dry-run  # 발송·기록 없이 메시지만 출력
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
SUMMARY_MAX = 500          # 카테고리 흐름 요약 상한(보통 150~300자라 사실상 통째)
WHY_MAX = 100              # 기사별 why 자르는 길이


def esc(s: object) -> str:
    """텔레그램 HTML 파싱용 이스케이프(& < > 만; 따옴표는 건드리지 않음)."""
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def load_json(path: pathlib.Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def sent_path(date: str) -> pathlib.Path:
    return ROOT / "data" / f"sent_{date}.json"


def load_sent(date: str) -> set[str]:
    data = load_json(sent_path(date), {})
    if isinstance(data, dict):
        return set(data.get("sent", []))
    return set()


def save_sent(date: str, hashes: list[str]) -> None:
    have = load_sent(date)
    merged = list(have) + [h for h in hashes if h not in have]
    payload = {"sent": merged, "updated": datetime.datetime.now(KST).isoformat()}
    sent_path(date).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build(date: str) -> tuple[list[str], list[str]]:
    """(발송 메시지 블록들, 이번에 새로 보내는 hash 목록) 반환.

    이미 보낸 기사는 제외한다. 보낼 새 픽이 없으면 ([], []).
    """
    picks = load_json(ROOT / "data" / f"picks_{date}.json", [])
    cache = load_json(ROOT / "data" / f"ai_cache_{date}.json", {})
    stats = load_json(ROOT / "data" / "stats" / f"{date}.json", {})
    sent = load_sent(date)
    is_first = len(sent) == 0

    new_picks = [p for p in picks if p.get("hash") and p["hash"] not in sent]
    if not new_picks:
        return [], []
    new_hashes = [p["hash"] for p in new_picks]

    blocks: list[str] = []
    if is_first:
        head = f"📰 <b>Daily Brief</b> · {esc(date)}"
        total = stats.get("total")
        if total is not None:
            pick_n = stats.get("pick_count", len(picks))
            head += f"\n🗂️ 수집 <b>{total}건</b> → ⭐ 핵심 <b>{pick_n}건</b>"
    else:
        now = datetime.datetime.now(KST).strftime("%H:%M")
        head = f"🆕 <b>새로 뜬 소식</b> · {esc(date)} {now} · {len(new_picks)}건"
    blocks.append(head)

    by_cat: dict[str, list[dict]] = {}
    for it in new_picks:
        by_cat.setdefault(it.get("cat", ""), []).append(it)

    for cat in CAT_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines = [f"{CAT_EMOJI.get(cat, '')} <b>{esc(cat)}</b>"]
        # 흐름 요약은 첫(전체) 발송에만 붙인다. 증분 발송은 새 기사 위주로 간결하게.
        if is_first:
            c = cache.get(cat)
            summary = c.get("summary", "") if isinstance(c, dict) else ""
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

    return blocks, new_hashes


def pack_messages(blocks: list[str]) -> list[str]:
    """블록들을 텔레그램 길이 제한에 맞는 메시지 여러 개로 묶는다."""
    messages: list[str] = []
    cur = ""
    for b in blocks:
        if len(b) > CHUNK_SOFT:  # 단일 블록이 한도 초과 → 줄 단위 강제 분할
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
    ap.add_argument("--dry-run", action="store_true", help="발송·기록 없이 메시지만 출력")
    ap.add_argument("--date", default=datetime.datetime.now(KST).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    blocks, new_hashes = build(args.date)
    if not blocks:
        print(f"[telegram] {args.date} 발송할 새 소식이 없습니다 — 스킵")
        return 0

    messages = pack_messages(blocks)

    if args.dry_run:
        print(f"[telegram] --dry-run: 메시지 {len(messages)}개, 새 픽 {len(new_hashes)}건 (발송·기록 안 함)\n")
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

    sent_ok = 0
    fails = 0
    for i, m in enumerate(messages, 1):
        try:
            send_message(token, chat_id, m)
            sent_ok += 1
        except urllib.error.HTTPError as e:
            fails += 1
            body = e.read().decode("utf-8", "replace")
            print(f"[telegram] 발송 실패 {i}/{len(messages)} (HTTP {e.code}): {body}")
        except Exception as e:  # 네트워크 등 — 파이프라인은 막지 않는다
            fails += 1
            print(f"[telegram] 발송 실패 {i}/{len(messages)}: {e}")

    # 전부 성공했을 때만 발송 기록(부분 실패 시 다음 실행에서 재시도되게 남겨둔다)
    if fails == 0:
        save_sent(args.date, new_hashes)
        print(f"[telegram] 발송 완료 {sent_ok}개 · 새 기사 {len(new_hashes)}건 기록")
    else:
        print(f"[telegram] 발송 {sent_ok}/{len(messages)}개 (실패 {fails}) — 기록 보류(다음 실행 재시도)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
