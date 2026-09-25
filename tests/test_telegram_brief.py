# -*- coding: utf-8 -*-
"""build_brief 가 커스텀 소스(내소스)를 발송에 포함하는지 검증.

배경: 내소스는 AI 요약·픽 대상이 아니라 picks_{날짜}.json 에 들어가지 않는다.
brief 모드가 picks 만 보내던 동안에는 아침 발송 경로가 없었고, 같은 실행이
수집 전체를 seen 에 기록하므로 저녁 헤드라인에서도 "새 글"로 잡히지 않아
사실상 텔레그램에 전달되지 않았다. 그래서 brief 가 원문 목록을 직접 붙인다.
"""
import json
import pathlib
import sys
import tempfile

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
import telegram_notify as tn  # noqa: E402

DATE = "2026-09-25"


def setup_data(root: pathlib.Path, mine_count: int, picks: int = 2) -> None:
    """report.py 가 남기는 산출물을 흉내낸다."""
    data = root / "data"
    (data / "stats").mkdir(parents=True, exist_ok=True)

    pick_items = [
        {"title": f"경제기사{i}", "link": f"https://news.test/{i}",
         "cat": "경제", "why": "이유", "source": "테스트"}
        for i in range(picks)
    ]
    (data / f"picks_{DATE}.json").write_text(
        json.dumps(pick_items, ensure_ascii=False), encoding="utf-8")
    (data / f"ai_cache_{DATE}.json").write_text(
        json.dumps({"경제": {"summary": "흐름 요약"}}, ensure_ascii=False), encoding="utf-8")
    (data / "stats" / f"{DATE}.json").write_text(
        json.dumps({"total": 100, "pick_count": picks}, ensure_ascii=False), encoding="utf-8")

    raw = pick_items + [
        {"title": f"내블로그글{i}", "link": f"https://blog.test/{i}",
         "cat": "내소스", "source": "내 블로그", "hash": f"h{i}"}
        for i in range(mine_count)
    ]
    (data / f"raw_{DATE}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in raw), encoding="utf-8")


def test_brief_includes_custom_sources() -> None:
    """picks 에 없어도 내소스 글이 아침 브리핑에 실린다."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        tn.ROOT = root
        setup_data(root, mine_count=3)

        text = "\n".join(tn.build_brief(DATE))
        assert "내소스" in text, "내소스 블록이 없다"
        for i in range(3):
            assert f"내블로그글{i}" in text, f"내블로그글{i} 가 빠졌다"
        assert "경제기사0" in text, "기존 AI 픽이 사라졌다"


def test_brief_without_custom_sources() -> None:
    """내소스가 없으면 빈 블록을 만들지 않는다."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        tn.ROOT = root
        setup_data(root, mine_count=0)

        text = "\n".join(tn.build_brief(DATE))
        assert "내소스" not in text, "내소스가 없는데 블록이 생겼다"
        assert "경제기사0" in text


def test_custom_sources_capped() -> None:
    """내소스가 많아도 상한까지만 싣고 남은 수를 알린다."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        tn.ROOT = root
        over = tn.MINE_MAX + 4
        setup_data(root, mine_count=over)

        text = "\n".join(tn.build_brief(DATE))
        assert f"내블로그글{tn.MINE_MAX - 1}" in text, "상한 직전 항목이 빠졌다"
        assert f"내블로그글{tn.MINE_MAX}" not in text, "상한을 넘겨 실었다"
        assert "…외 4건" in text, "남은 건수 안내가 없다"


def run() -> None:
    passed = 0
    for fn in (test_brief_includes_custom_sources,
               test_brief_without_custom_sources,
               test_custom_sources_capped):
        fn()
        passed += 1
    print(f"OK: {passed} tests passed")


if __name__ == "__main__":
    run()
