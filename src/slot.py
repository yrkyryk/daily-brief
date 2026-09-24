# -*- coding: utf-8 -*-
"""slot.py — 그날 발송 모드(brief|headlines)를 단일 지점에서 판정한다.

기존엔 "그날 첫 실행이냐"(seen 파일 유무)로 요약/헤드라인을 갈랐다. 그런데
GitHub Actions cron 은 best-effort 라 저녁 슬롯이 자정을 넘겨 실행되면
"다음날 첫 실행"으로 오인돼 새벽에 전체 요약이 나가는 문제가 있었다.

그래서 판정을 시각 기준으로 바꾼다:
  - brief(전체 요약): 그날 아직 요약을 안 보냈고 + 지금이 아침(KST 08시)~ 일 때만.
  - headlines: 그 외 전부(요약 이미 발송 / 자정~새벽 구간).

효과:
  - 저녁 슬롯이 새벽까지 밀려도 headlines 로만 나가 → 새벽 요약 원천 차단.
  - 아침 슬롯이 통째로 드롭되면 오후/저녁 실행이 요약으로 승격(그날 요약을 놓치지 않음).

"요약 발송함" 표시는 data/brief_{날짜}.json 마커로 남긴다.
seen 파일과 분리하는 이유: seen 은 헤드라인 증분 추적용이라 헤드라인 발송도
매번 갱신하므로 "요약을 보냈는가"의 신호로 쓸 수 없다.
"""
import datetime
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"           # 테스트에서 재지정 가능
KST = datetime.timezone(datetime.timedelta(hours=9))
MORNING_HOUR = 8                   # 이 시각(KST) 이전 실행은 요약 금지(새벽 차단)
SEND_GAP_HOURS = 6                 # 이 시간 안에 발송이 있었으면 안전망 cron 은 불필요


def now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)


def brief_marker(date: str) -> pathlib.Path:
    return DATA_DIR / f"brief_{date}.json"


def brief_sent(date: str) -> bool:
    """그날 전체 요약이 이미 발송됐는지."""
    return brief_marker(date).exists()


def mark_brief_sent(date: str, now: datetime.datetime | None = None) -> None:
    """요약 발송 성공 후 호출 — 그날 요약 완료 마커를 남긴다."""
    when = (now or now_kst()).isoformat()
    brief_marker(date).write_text(f'{{"sent_at": "{when}"}}', encoding="utf-8")


def decide_mode(date: str, now: datetime.datetime | None = None) -> str:
    """'brief' 또는 'headlines' 반환. 파일 존재 + 시각만 보는 순수 판정."""
    now = (now or now_kst()).astimezone(KST)
    if brief_sent(date):
        return "headlines"                     # 그날 요약 이미 발송
    today = now.strftime("%Y-%m-%d")
    if date == today and now.hour < MORNING_HOUR:
        return "headlines"                     # 자정~새벽: 요약 금지
    return "brief"                             # 아침 이후 첫 요약(또는 과거 백필)


def seen_path(date: str) -> pathlib.Path:
    return DATA_DIR / f"seen_{date}.json"


def last_send_at(date: str) -> datetime.datetime | None:
    """그날 마지막 '실제 발송' 시각. 발송 이력이 없으면 None.

    telegram_notify 는 메시지를 전량 발송 성공했을 때만 seen 을 기록한다.
    따라서 seen 파일의 updated 가 곧 마지막 발송 시각이다.
    """
    try:
        raw = json.loads(seen_path(date).read_text(encoding="utf-8"))
        return datetime.datetime.fromisoformat(raw["updated"]).astimezone(KST)
    except Exception:
        return None


def safety_net_suppressed(date: str, now: datetime.datetime | None = None) -> bool:
    """안전망 cron(schedule 트리거)을 건너뛸지 판정.

    발송 시각은 외부 스케줄러(workflow_dispatch)가 정한다. 그게 살아 있으면
    최근에 발송이 있었을 테니 안전망은 불필요하다 → 중단해서 중복을 0으로 만든다.
    외부 스케줄러가 죽은 날에만 안전망이 실제로 발송한다.

    안전망 cron 은 10:30 / 18:15 KST 전후에 도착하므로 자정 경계는 고려하지 않는다.
    """
    last = last_send_at(date)
    if last is None:
        return False                           # 그날 발송 이력 없음 → 안전망 필요
    now = (now or now_kst()).astimezone(KST)
    return (now - last) < datetime.timedelta(hours=SEND_GAP_HOURS)


if __name__ == "__main__":
    # python src/slot.py [날짜]                 → brief | headlines
    # python src/slot.py [날짜] --safety-check   → ok | suppress (안전망 cron 진행 여부)
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = args[0] if args else now_kst().strftime("%Y-%m-%d")
    if "--safety-check" in sys.argv:
        print("suppress" if safety_net_suppressed(d) else "ok")
    else:
        print(decide_mode(d))
