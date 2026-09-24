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


def _page(og_type: str = "", body: str = "") -> str:
    """가드 테스트용 최소 HTML. 실측한 실패 사례의 본문 길이를 재현한다."""
    meta = f'<meta property="og:type" content="{og_type}">' if og_type else ""
    return f"<html><head>{meta}</head><body><article>{body}</article></body></html>"


def test_accept_as_article() -> None:
    """가드: 목록·프로필 페이지를 '글 하나'로 오인하지 않는다.

    실측(2026-09-24)한 쓰레기 유입 3건이 전부 차단돼야 한다.
    """
    # 루트 = 블로그 홈. 본문이 길어도 글이 아니다.
    check(not fetch_article.accept_as_article(
        "https://www.oopy.io", _page(body="가" * 500)),
        "루트 URL 이 글로 인정됨")
    check(not fetch_article.accept_as_article(
        "https://www.oopy.io/", _page(body="가" * 500)),
        "슬래시로 끝나는 루트가 글로 인정됨")

    # 프로필 페이지(@). 벨로그 목록이 여기 해당한다.
    check(not fetch_article.accept_as_article(
        "https://velog.io/@teo", _page(body="가" * 500)),
        "@프로필 URL 이 글로 인정됨")

    # 본문이 짧으면 글이 아니다. 실측: 벨로그 27자, D2 44자, 우피 62자.
    for n in (27, 44, 62, 199):
        check(not fetch_article.accept_as_article(
            "https://d2.naver.com/home", _page(body="가" * n)),
            f"본문 {n}자가 글로 인정됨")

    # 임계값 경계: 200자부터 통과한다.
    check(fetch_article.accept_as_article(
        "https://d2.naver.com/home", _page(body="가" * 200)),
        "본문 200자가 글로 거부됨")

    # 실측: 티스토리 개별 글 2130자.
    check(fetch_article.accept_as_article(
        "https://jojoldu.tistory.com/885", _page(body="가" * 2130)),
        "티스토리 개별 글이 거부됨")

    # og:type=article 이면 본문이 짧아도 글로 인정한다(사이트가 직접 선언한 것).
    check(fetch_article.accept_as_article(
        "https://example.com/post/1", _page(og_type="article", body="짧음")),
        "og:type=article 이 거부됨")

    # 단, 선언이 있어도 루트·프로필이면 거부한다(선언은 경로 판정을 못 이긴다).
    check(not fetch_article.accept_as_article(
        "https://velog.io/@teo", _page(og_type="article", body="가" * 500)),
        "og:type=article 이 @프로필 판정을 덮어씀")

    check(fetch_article.MIN_ARTICLE_CHARS == 200, "MIN_ARTICLE_CHARS 가 200 이 아님")


def test_socket_timeout_restores() -> None:
    """타임아웃 컨텍스트는 전역 상태를 건드리므로 반드시 복원돼야 한다.

    복원에 실패하면 같은 프로세스의 collect.py 뉴스 수집까지 영향을 받는다.
    """
    import socket
    before = socket.getdefaulttimeout()
    with fetch_article._socket_timeout(3):
        check(socket.getdefaulttimeout() == 3, "컨텍스트 안에서 타임아웃이 안 걸림")
    check(socket.getdefaulttimeout() == before, "컨텍스트를 빠져나온 뒤 복원 안 됨")

    # 예외가 나도 복원돼야 한다.
    try:
        with fetch_article._socket_timeout(3):
            raise RuntimeError("의도된 예외")
    except RuntimeError:
        pass
    check(socket.getdefaulttimeout() == before, "예외 발생 시 복원 안 됨")

    check(fetch_article.SOURCE_BUDGET > 0, "SOURCE_BUDGET 이 설정 안 됨")


def test_discover_contract() -> None:
    """discover() 의 계약: 항상 (목록, 라벨) 쌍을 돌려준다.

    라벨 문자열은 collect.py 가 집계 키로 쓰므로 오타가 나면 통계가 조용히 갈라진다.
    """
    # 빈 입력·주석은 네트워크를 타지 않고 즉시 돌아와야 한다.
    for bad in ("", "   ", "# 주석입니다"):
        items, how = fetch_article.discover(bad)
        check(items == [], f"discover({bad!r}) 가 빈 목록이 아님")
        check(how == "빈입력", f"discover({bad!r}) 라벨이 {how!r}")

    # 하위 호환 래퍼가 목록만 돌려주는지
    check(fetch_article.discover_and_fetch("") == [],
          "discover_and_fetch 하위 호환이 깨짐")

    # 라벨 집합이 문서화된 8개와 일치하는지(collect.py 와의 계약)
    check(fetch_article.RESOLVE_LABELS == (
        "피드직접", "플랫폼규칙", "자동탐지", "경로추측",
        "단일글", "피드없음·목록페이지", "접속실패", "빈입력"),
        f"라벨 집합이 바뀜: {fetch_article.RESOLVE_LABELS}")


def run() -> None:
    test_resolve_feed()
    test_accept_as_article()
    test_socket_timeout_restores()
    test_discover_contract()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)}/{CHECKED} 실패")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK: {CHECKED} checks passed")


if __name__ == "__main__":
    run()
