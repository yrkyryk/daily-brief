# -*- coding: utf-8 -*-
"""
telegram_notify.py — Daily Brief를 텔레그램으로 발송한다(하루 여러 번, 증분).

수집은 collect.py 가 이미 해두었다. 이 스크립트는 재수집하지 않는다.

두 가지 모드 (slot.decide_mode 가 시각 기준으로 판정 — slot.py 참조):
  - brief   : 아침(KST 08시~) + 그날 요약 미발송. report.py 의 AI 픽/요약을 전체 발송.
              입력 data/picks_{날짜}.json, data/ai_cache_{날짜}.json
  - headlines: 그 외(요약 이미 발송 / 자정~새벽). AI 없이 새로 수집된 헤드라인만 발송.
              입력 data/raw_{날짜}.jsonl (collect.py 산출물)

증분 추적:
  - data/seen_{날짜}.json 에 그날 수집·노출한 기사 hash 를 누적 기록한다.
  - headlines 는 seen 에 없는(=새로 뜬) 기사만 발송한다.
  - 요약 발송 여부는 data/brief_{날짜}.json 마커로 따로 관리한다(slot.py).
  - 날짜별 파일이라 다음날이면 자동 리셋 → 다시 아침 brief.

인증(환경변수): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SITE_URL(선택)
토큰 없으면 조용히 스킵(exit 0). 발송 실패도 파이프라인을 막지 않는다.

사용:
  python src/telegram_notify.py            # 자동 모드 발송(+ seen 기록)
  python src/telegram_notify.py --dry-run  # 발송·기록 없이 미리보기
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
sys.path.insert(0, str(ROOT / "src"))
import slot  # noqa: E402  발송 모드(brief|headlines) 단일 판정
KST = datetime.timezone(datetime.timedelta(hours=9))
CAT_ORDER = ["경제", "사회", "연예", "실무", "내소스"]
CAT_EMOJI = {"경제": "💹", "사회": "🏛️", "연예": "🎬", "실무": "🛠️", "내소스": "📌"}

CHUNK_SOFT = 3800          # 텔레그램 4096자 한도에 여유를 둔 분할 기준
SUMMARY_MAX = 500          # 카테고리 흐름 요약 상한(보통 150~300자라 사실상 통째)
WHY_MAX = 100              # 기사별 why 자르는 길이
HEADLINES_PER_CAT = 15     # 헤드라인 모드: 카테고리당 최대 표시 수


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


def load_raw(date: str) -> list[dict]:
    path = ROOT / "data" / f"raw_{date}.jsonl"
    try:
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []


def seen_path(date: str) -> pathlib.Path:
    return ROOT / "data" / f"seen_{date}.json"


def load_seen(date: str) -> set[str]:
    data = load_json(seen_path(date), {})
    return set(data.get("seen", [])) if isinstance(data, dict) else set()


def save_seen(date: str, hashes: list[str]) -> None:
    have = load_seen(date)
    merged = list(have) + [h for h in hashes if h not in have]
    payload = {"seen": merged, "updated": datetime.datetime.now(KST).isoformat()}
    seen_path(date).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _footer_blocks() -> list[str]:
    site = os.environ.get("SITE_URL", "").strip()
    return [f"🔗 <a href=\"{esc(site)}\">전체 리포트 보기</a>"] if site else []


def build_brief(date: str) -> list[str]:
    """아침 전체 브리핑(AI 픽 + 흐름 요약)."""
    picks = load_json(ROOT / "data" / f"picks_{date}.json", [])
    cache = load_json(ROOT / "data" / f"ai_cache_{date}.json", {})
    stats = load_json(ROOT / "data" / "stats" / f"{date}.json", {})
    if not picks:
        return []

    blocks: list[str] = []
    head = f"📰 <b>Daily Brief</b> · {esc(date)}"
    total = stats.get("total")
    if total is not None:
        head += f"\n🗂️ 수집 <b>{total}건</b> → ⭐ 핵심 <b>{stats.get('pick_count', len(picks))}건</b>"
    blocks.append(head)

    by_cat: dict[str, list[dict]] = {}
    for it in picks:
        by_cat.setdefault(it.get("cat", ""), []).append(it)

    for cat in CAT_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines = [f"{CAT_EMOJI.get(cat, '')} <b>{esc(cat)}</b>"]
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

    return blocks + _footer_blocks()


def build_headlines(date: str, seen: set[str]) -> list[str]:
    """점심/저녁: 새로 수집된 기사 헤드라인만(AI 없음)."""
    raw = load_raw(date)
    new = [it for it in raw if it.get("hash") and it["hash"] not in seen]
    if not new:
        return []

    by_cat: dict[str, list[dict]] = {}
    for it in new:
        by_cat.setdefault(it.get("cat", ""), []).append(it)

    now = datetime.datetime.now(KST).strftime("%H:%M")
    blocks = [f"🆕 <b>새로 뜬 소식</b> · {esc(date)} {now} · {len(new)}건"]
    for cat in CAT_ORDER:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines = [f"{CAT_EMOJI.get(cat, '')} <b>{esc(cat)}</b> ({len(items)})"]
        for it in items[:HEADLINES_PER_CAT]:
            title = esc(clip(it.get("title", ""), 90))
            link = esc(it.get("link", ""))
            lines.append(f"• <a href=\"{link}\">{title}</a>" if link else f"• {title}")
        if len(items) > HEADLINES_PER_CAT:
            lines.append(f"   …외 {len(items) - HEADLINES_PER_CAT}건")
        blocks.append("\n".join(lines))

    return blocks + _footer_blocks()


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
    ap.add_argument("--dry-run", action="store_true", help="발송·기록 없이 미리보기")
    ap.add_argument("--date", default=datetime.datetime.now(KST).strftime("%Y-%m-%d"))
    args = ap.parse_args()

    date = args.date
    seen = load_seen(date)
    mode = slot.decide_mode(date)
    is_brief = mode == "brief"

    blocks = build_brief(date) if is_brief else build_headlines(date, seen)
    if not blocks:
        print(f"[telegram] {date} ({mode}) 발송할 내용이 없습니다 — 스킵")
        return 0

    messages = pack_messages(blocks)
    # 이번 실행에서 seen 에 추가할 hash: 그날 수집한 모든 기사(중복 방지 기준선)
    all_hashes = [it["hash"] for it in load_raw(date) if it.get("hash")]

    if args.dry_run:
        print(f"[telegram] --dry-run ({mode}): 메시지 {len(messages)}개 (발송·기록 안 함)\n")
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
            print(f"[telegram] 발송 실패 {i}/{len(messages)} (HTTP {e.code}): {e.read().decode('utf-8', 'replace')}")
        except Exception as e:  # 네트워크 등 — 파이프라인은 막지 않는다
            fails += 1
            print(f"[telegram] 발송 실패 {i}/{len(messages)}: {e}")

    # 전부 성공했을 때만 seen 기록(부분 실패 시 다음 실행에서 재시도되게 남겨둔다)
    if fails == 0:
        save_seen(date, all_hashes)
        if is_brief:
            slot.mark_brief_sent(date)  # 그날 요약 완료 표시 → 이후 실행은 headlines
        print(f"[telegram] ({mode}) 발송 완료 {sent_ok}개 · seen {len(all_hashes)}건 기록")
    else:
        print(f"[telegram] ({mode}) 발송 {sent_ok}/{len(messages)}개 (실패 {fails}) — 기록 보류")
    return 0


if __name__ == "__main__":
    sys.exit(main())
