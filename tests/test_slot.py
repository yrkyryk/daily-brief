# -*- coding: utf-8 -*-
"""slot.decide_mode 규칙 테스트 (의존성 없이 python tests/test_slot.py 로 실행).

핵심 규칙:
  - 아침(KST 08시~) + 그날 요약 미발송  → brief
  - 자정~새벽(KST 08시 미만)             → headlines (새벽 요약 차단)
  - 그날 요약 이미 발송(brief 마커 존재)  → headlines
  - 아침 슬롯이 드롭돼도 오후/저녁에 승격 → brief
  - --date 로 과거 날짜 백필 시 새벽 가드 미적용
"""
import datetime
import json
import pathlib
import sys
import tempfile

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
import slot  # noqa: E402

KST = datetime.timezone(datetime.timedelta(hours=9))


def at(date: str, hour: int, minute: int = 0) -> datetime.datetime:
    y, m, d = map(int, date.split("-"))
    return datetime.datetime(y, m, d, hour, minute, tzinfo=KST)


def write_seen(date: str, when: datetime.datetime) -> None:
    """telegram_notify 가 발송 성공 시 남기는 seen 파일을 흉내낸다."""
    slot.seen_path(date).write_text(
        json.dumps({"seen": [], "updated": when.isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def run() -> None:
    passed = 0
    with tempfile.TemporaryDirectory() as tmp:
        slot.DATA_DIR = pathlib.Path(tmp)
        today = "2026-09-15"

        # 1) 아침(08:30) 첫 실행 → brief
        assert slot.decide_mode(today, at(today, 8, 30)) == "brief"
        passed += 1

        # 2) 아침 지연(10:18)도 아직 brief 미발송이면 brief
        assert slot.decide_mode(today, at(today, 10, 18)) == "brief"
        passed += 1

        # 3) 자정 넘긴 저녁 슬롯(00:51) → headlines (새벽 요약 차단)
        assert slot.decide_mode(today, at(today, 0, 51)) == "headlines"
        passed += 1

        # 4) 07:59 도 아직 새벽 → headlines
        assert slot.decide_mode(today, at(today, 7, 59)) == "headlines"
        passed += 1

        # 5) 요약 발송 후엔 아침 시간대라도 headlines
        slot.mark_brief_sent(today, at(today, 8, 30))
        assert slot.brief_sent(today) is True
        assert slot.decide_mode(today, at(today, 8, 31)) == "headlines"
        passed += 1

        # 6) 아침 슬롯 드롭 → 오후(13:07)에 승격되어 brief
        tomorrow = "2026-09-16"
        assert slot.decide_mode(tomorrow, at(tomorrow, 13, 7)) == "brief"
        passed += 1

        # 7) 저녁(18:07)까지 밀려도 아직 미발송이면 brief
        assert slot.decide_mode(tomorrow, at(tomorrow, 18, 7)) == "brief"
        passed += 1

        # 8) 과거 날짜 백필: 현재 시각이 새벽이어도 dawn 가드 미적용 → brief
        past = "2026-09-10"
        now_dawn_next_day = at("2026-09-16", 3, 0)
        assert slot.decide_mode(past, now_dawn_next_day) == "brief"
        passed += 1

        # --- 안전망 cron 억제 규칙 (safety_net_suppressed) ---
        # 외부 스케줄러가 발송 시각을 정하고, 안전망 cron 은 그게 죽은 날에만 돈다.
        sn = "2026-09-17"

        # 9) 그날 발송 이력 없음(외부 스케줄러 사망) → 안전망 진행
        assert slot.safety_net_suppressed(sn, at(sn, 10, 30)) is False
        passed += 1

        # 10) 외부가 08:30 에 발송함 → 10:30 안전망은 2h 차이라 억제
        write_seen(sn, at(sn, 8, 30))
        assert slot.safety_net_suppressed(sn, at(sn, 10, 30)) is True
        passed += 1

        # 11) 그 뒤 외부가 죽어 08:30 이 마지막 → 18:15 안전망은 9h45m 차이라 진행
        assert slot.safety_net_suppressed(sn, at(sn, 18, 15)) is False
        passed += 1

        # 12) 외부가 13:00 에도 발송 → 18:15 안전망은 5h15m(<6h) 이라 억제
        write_seen(sn, at(sn, 13, 0))
        assert slot.safety_net_suppressed(sn, at(sn, 18, 15)) is True
        passed += 1

        # 13) 외부가 18:00 에 발송 → 18:15 안전망은 15분 차이라 억제
        write_seen(sn, at(sn, 18, 0))
        assert slot.safety_net_suppressed(sn, at(sn, 18, 15)) is True
        passed += 1

        # 14) seen 파일이 깨져 있어도 예외 없이 "발송 이력 없음"으로 보고 진행
        slot.seen_path(sn).write_text("{ broken", encoding="utf-8")
        assert slot.safety_net_suppressed(sn, at(sn, 18, 15)) is False
        passed += 1

    print(f"OK: {passed} assertions passed")


if __name__ == "__main__":
    run()
