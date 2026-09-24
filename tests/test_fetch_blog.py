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


# 스펙 1절 실측 대상. (URL, 목록 수집을 기대하는가)
NETWORK_CASES = [
    ("https://blog.naver.com/adcsk",         True),
    ("https://jojoldu.tistory.com/",         True),
    ("https://brunch.co.kr/@svillustrated",  True),
    ("https://velog.io/@teo",                True),   # 이전: 쓰레기 1건
    ("https://medium.com/daangn",            True),   # 이전: 0건
    ("https://d2.naver.com/home",            True),   # 이전: 쓰레기 1건
    ("https://www.oopy.io",                  False),  # 피드가 실제로 없다. 0건이 정답
]


def test_network() -> None:
    """실제 사이트로 완료 기준을 증명한다. --network 플래그로만 돈다."""
    import time as _t
    for url, expect_list in NETWORK_CASES:
        t0 = _t.monotonic()
        items, how = fetch_article.discover(url)
        dt = _t.monotonic() - t0
        print(f"  {url[:40]:42s} {len(items):2d}건 ({how}, {dt:.1f}s)")

        # 완료 기준 3: 소스당 10초 이내
        check(dt < 10, f"{url} 가 {dt:.1f}초 소요 (10초 초과)")

        if expect_list:
            check(len(items) >= 2, f"{url} 가 목록을 못 가져옴 ({len(items)}건, {how})")
            # 완료 기준 2: 목록 페이지 자신이 글로 둔갑하면 안 된다
            check(all(it["link"].rstrip("/") != url.rstrip("/") for it in items),
                  f"{url} 가 자기 자신을 글로 반환 (쓰레기 단일글)")
        else:
            check(items == [], f"{url} 는 0건이어야 하는데 {len(items)}건 ({how})")
            check(how in ("피드없음·목록페이지", "접속실패"),
                  f"{url} 라벨이 {how!r}")


class _FakeFeed:
    """feedparser.parse() 가 돌려주는 결과의 최소 흉내.

    _from_feed() 가 실제로 건드리는 것만 갖춘다: entries 리스트와,
    feed.get("title") 를 호출할 수 있는 dict 형태의 feed 속성.
    """

    def __init__(self, entries: list[dict]) -> None:
        self.entries = entries
        self.feed = {"title": ""}


def _fake_entry(link: str = "https://example.com/x") -> list[dict]:
    return [{"title": "제목", "link": link, "summary": "요약"}]


def test_discover_order() -> None:
    """discover() 의 5단계 체인 순서를 고정한다.

    ①→②→③→④→⑤ 순서가 뒤바뀌면(예: ④·⑤ 가 스왑되면) 여기서 잡힌다.
    네트워크를 전혀 타지 않도록 _parse_feed 와 _fetch_html 을 가짜로 바꾼다.
    example.com 은 PLATFORM_FEEDS 어느 규칙과도 안 맞으므로 ② 에서 오검출되지
    않는다. d2.naver.com·velog.io·medium.com·blog.naver.com 은 반대로 쓴다.
    """
    orig_parse_feed = fetch_article._parse_feed
    orig_fetch_html = fetch_article._fetch_html

    feed_map: dict[str, list] = {}
    html_map: dict[str, str] = {}

    def fake_parse_feed(url: str):
        return _FakeFeed(feed_map.get(url, []))

    def fake_fetch_html(url: str, attempts: int = 2):
        return html_map.get(url)

    fetch_article._parse_feed = fake_parse_feed
    fetch_article._fetch_html = fake_fetch_html

    try:
        # ① URL 자체가 피드.
        feed_map.clear(); html_map.clear()
        feed_map["https://example.com/direct-feed"] = _fake_entry()
        items, how = fetch_article.discover("https://example.com/direct-feed")
        check(how == "피드직접", f"①이 {how!r} (기대: 피드직접)")
        check(len(items) == 1, f"①의 항목 수가 {len(items)} (기대: 1)")

        # ② 플랫폼 규칙표. 직접 파싱은 0건, 규칙이 가리키는 피드만 항목이 있다.
        feed_map.clear(); html_map.clear()
        feed_map["https://v2.velog.io/rss/@teo"] = _fake_entry()
        items, how = fetch_article.discover("https://velog.io/@teo")
        check(how == "플랫폼규칙", f"②가 {how!r} (기대: 플랫폼규칙)")

        # ③ 페이지가 선언한 피드(<link rel=alternate>). 선언된 URL만 항목이 있다.
        feed_map.clear(); html_map.clear()
        html_map["https://example.com/page"] = (
            '<html><head><link rel="alternate" type="application/rss+xml" '
            'href="https://example.com/declared.xml"></head><body></body></html>'
        )
        feed_map["https://example.com/declared.xml"] = _fake_entry()
        items, how = fetch_article.discover("https://example.com/page")
        check(how == "자동탐지", f"③이 {how!r} (기대: 자동탐지)")

        # ④ 단일 글: accept_as_article 을 통과하는 페이지.
        # origin 의 /rss 도 항목을 내주도록 심어 둔다. 그래도 ④가 이겨야 한다
        # (④가 ⑤보다 먼저 검사된다는 것을 고정하는 핵심 단언).
        feed_map.clear(); html_map.clear()
        html_map["https://example.com/post/1"] = (
            '<html><head><meta property="og:type" content="article"></head>'
            f'<body><article>{"가" * 300}</article></body></html>'
        )
        feed_map["https://example.com/rss"] = _fake_entry()
        items, how = fetch_article.discover("https://example.com/post/1")
        check(how == "단일글", f"④가 {how!r} (기대: 단일글, ④는 ⑤보다 먼저여야 함)")

        # ⑤ 경로 추측: accept_as_article 은 실패, origin 의 /rss 가 항목을 낸다.
        feed_map.clear(); html_map.clear()
        html_map["https://example.com/list"] = "<html><body>목록</body></html>"
        feed_map["https://example.com/rss"] = _fake_entry()
        items, how = fetch_article.discover("https://example.com/list")
        check(how == "경로추측", f"⑤가 {how!r} (기대: 경로추측)")

        # 아무 단계도 안 걸리고 HTML 요청마저 실패하면 접속실패.
        feed_map.clear(); html_map.clear()
        items, how = fetch_article.discover("https://example.com/dead")
        check(items == [] and how == "접속실패",
              f"실패 케이스가 ({items!r}, {how!r}) (기대: ([], 접속실패))")
    finally:
        fetch_article._parse_feed = orig_parse_feed
        fetch_article._fetch_html = orig_fetch_html


def run() -> None:
    test_resolve_feed()
    test_accept_as_article()
    test_socket_timeout_restores()
    test_discover_contract()
    test_discover_order()
    if "--network" in sys.argv:
        print("네트워크 통합 테스트 (실제 사이트 접속):")
        test_network()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)}/{CHECKED} 실패")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK: {CHECKED} checks passed")


if __name__ == "__main__":
    run()
