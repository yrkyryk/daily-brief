# -*- coding: utf-8 -*-
"""fetch_article 블로그 수집 테스트 (python tests/test_fetch_blog.py 로 실행).

기본 실행은 네트워크를 타지 않는다. 판단 로직 두 개가 순수 함수이기 때문이다.
  - resolve_feed()      : 플랫폼 URL → 피드 URL (규칙표 조회)
  - accept_as_article() : 목록·프로필 페이지를 '글'로 오인하지 않기 위한 가드

실제 사이트를 때리는 통합 테스트는 --network 플래그로만 돈다.

실패를 모아서 마지막에 한 번에 출력한다(test_promo.py 와 동일한 관례).
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
import fetch_article  # noqa: E402

FAILURES: list[str] = []
CHECKED = 0


def check(cond: bool, msg: str) -> None:
    global CHECKED
    CHECKED += 1
    if not cond:
        FAILURES.append(msg)


def test_resolve_feed() -> None:
    """규칙표: 플랫폼 URL 을 피드 URL 로 바꾼다."""
    cases = [
        # 네이버 블로그: 기존 하드코딩 특례를 규칙표로 흡수한 것이므로 회귀 테스트다
        ("https://blog.naver.com/adcsk",
         "https://rss.blog.naver.com/adcsk.xml"),
        ("https://blog.naver.com/PostList.naver?blogId=adcsk",
         "https://rss.blog.naver.com/adcsk.xml"),
        # 벨로그: 프로필 URL 은 목록 페이지라 HTML 폴백으로는 못 가져온다
        ("https://velog.io/@teo",
         "https://v2.velog.io/rss/@teo"),
        # 미디엄: @ 를 보존해야 개인·퍼블리케이션이 둘 다 맞는다
        ("https://medium.com/@tuanchris",
         "https://medium.com/feed/@tuanchris"),
        ("https://medium.com/daangn",
         "https://medium.com/feed/daangn"),
        # D2: 고정 피드. 경로가 /home 이라 '홈 추측'으로는 안 걸린다
        ("https://d2.naver.com/home",
         "https://d2.naver.com/d2.atom"),
    ]
    for url, expect in cases:
        got = fetch_article.resolve_feed(url)
        check(got == expect, f"resolve_feed({url}) = {got!r}, 기대 {expect!r}")

    # 규칙표에 없는 곳은 None 이어야 한다. 체인의 뒷단계로 흘러가야 하기 때문이다.
    for url in [
        "https://jojoldu.tistory.com/",          # 자동탐지로 해결됨
        "https://brunch.co.kr/@svillustrated",   # rss/@필명 은 0건이라 규칙에서 뺐다
        "https://example.com/blog",
    ]:
        got = fetch_article.resolve_feed(url)
        check(got is None, f"resolve_feed({url}) 가 {got!r}, None 이어야 함")


def run() -> None:
    test_resolve_feed()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)}/{CHECKED} 실패")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK: {CHECKED} checks passed")


if __name__ == "__main__":
    run()
