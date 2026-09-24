# -*- coding: utf-8 -*-
"""
fetch_article.py: 사용자 커스텀 소스(블로그 홈/개별 글) 수집.

discover(url) -> (글 목록, 해석경로) 가 5단계 체인으로 URL 을 해석한다.
  1) URL 자체가 피드인지 시도
  2) 안 되면 플랫폼 규칙표(resolve_feed)로 피드 주소를 추정해 재시도
  3) 안 되면 HTML 에서 <link rel="alternate" type="application/rss+xml"> 자동탐지해 재시도
  4) 안 되면 그 페이지를 '단일 글'로 취급 (가드: accept_as_article)
  5) 마지막으로 흔한 피드 경로(/rss, /feed 등)를 추측

해석경로는 RESOLVE_LABELS 아홉 값 중 하나로 돌아와 품질 기록에 집계된다.
실패해도 예외를 밖으로 던지지 않고 빈 목록/라벨을 돌려 파이프라인이 계속 진행되게 한다.
표준 라이브러리 + feedparser(기존 의존성)만 사용.
"""
import contextlib, re, html, socket, urllib.request, urllib.error, urllib.parse, time
import feedparser

UA = "Mozilla/5.0 (compatible; DailyBriefBot/1.0; +https://github.com/yrkyryk/daily-brief)"
PER_SOURCE = 5          # 피드/홈에서 가져올 최근 글 수
BODY_CAP = 1500         # 본문 발췌 최대 길이
FETCH_TIMEOUT = 8       # HTML 한 번 받는 데 쓰는 상한(초)
FEED_TIMEOUT = 8        # feedparser 한 번에 쓰는 상한(초)
# SOURCE_BUDGET 은 ③ 자동탐지·⑤ 경로 추측 단계를 돌릴지만 결정하는 예산이다.
# ①·② 의 _parse_feed(각 최대 8초), HTML 요청 _fetch_html(재시도 포함 최대 18초)은
# 이 예산에 걸리지 않는다. 예산을 처음 검사하는 시점에는 이미 이 셋이 다 끝난
# 뒤라, 최악의 경우 셋만으로 약 34초(8+8+18)가 먼저 든다.
SOURCE_BUDGET = 20      # 소스 하나당 예산(초). ③·⑤ 단계 실행 여부만 결정한다

# 피드를 스스로 선언하지 않는 블로그 플랫폼의 피드 주소 규칙.
# 네이버 블로그용 하드코딩 특례를 일반화한 것이다(Task 4 에서 특례를 제거한다).
# 규칙은 실측으로 확인한 것만 넣는다. 새 플랫폼은 한 줄 추가하면 된다.
#   브런치는 넣지 않는다: rss/@필명 은 0건이고(내부 ID 형태라야 한다),
#   HTML 자동탐지로 이미 해결된다.
PLATFORM_FEEDS = [
    (re.compile(r"blog\.naver\.com/(?:.*blogId=)?([\w-]+)"), "https://rss.blog.naver.com/{0}.xml"),
    (re.compile(r"velog\.io/@([\w.-]+)"),                    "https://v2.velog.io/rss/@{0}"),
    (re.compile(r"medium\.com/(@?[\w.-]+)"),                 "https://medium.com/feed/{0}"),
    (re.compile(r"d2\.naver\.com"),                          "https://d2.naver.com/d2.atom"),
]


def resolve_feed(url: str) -> str | None:
    """플랫폼 규칙표로 피드 URL 을 만든다. 네트워크를 타지 않는 순수 함수."""
    for pat, template in PLATFORM_FEEDS:
        m = pat.search(url)
        if m:
            return template.format(*m.groups())
    return None


def _fetch_html(url: str, attempts: int = 2) -> str | None:
    """HTML 원문. 일시 오류는 지수 백오프로 재시도. 실패 시 None."""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                raw = resp.read(1_000_000)
                return raw.decode(charset, "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 8))
                continue
            return None
    return None


def _meta(page: str, prop: str) -> str:
    """<meta property/name="prop" content="..."> 추출."""
    pat = re.compile(
        r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\'][^>]*>', re.I)
    m = pat.search(page)
    if not m:
        return ""
    c = re.search(r'content=["\']([^"\']*)["\']', m.group(0), re.I)
    return html.unescape(c.group(1)).strip() if c else ""


def _strip(text: str, limit: int) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def fetch_text(url: str, page: str | None = None) -> str | None:
    """기사 본문 발췌. <article>/<p> 우선, 없으면 og:description. 실패 시 None."""
    page = page if page is not None else _fetch_html(url)
    if not page:
        return None
    m = re.search(r"<article[^>]*>(.*?)</article>", page, re.I | re.S)
    if m and _strip(m.group(1), BODY_CAP):
        return _strip(m.group(1), BODY_CAP)
    paras = re.findall(r"<p[^>]*>(.*?)</p>", page, re.I | re.S)
    joined = _strip(" ".join(paras), BODY_CAP)
    if len(joined) >= 80:
        return joined
    desc = _meta(page, "og:description") or _meta(page, "description")
    return desc or (joined or None)


# 단일글 폴백 임계값. 실측 쓰레기 3건이 27~62자, 정상 글이 2130자로
# 한 자릿수 이상 벌어지므로 경계 사례가 없다. 정밀 튜닝은 불필요하다.
MIN_ARTICLE_CHARS = 200


def accept_as_article(url: str, page: str) -> bool:
    """이 페이지를 '글 하나'로 받아도 되는지. 네트워크를 타지 않는 순수 함수.

    폴백이 무조건 1건을 만들면 목록·프로필 페이지가 브리핑 카드로 둔갑한다.
    0건보다 나쁘다. 조용히 빠지는 게 아니라 품질 게이트를 통과한 채 리포트를 더럽힌다.
    """
    path = urllib.parse.urlsplit(url).path.rstrip("/")
    if not path:
        return False                                   # 루트 = 블로그 홈
    if path.rsplit("/", 1)[-1].startswith("@"):
        return False                                   # 프로필 페이지
    if _meta(page, "og:type").lower() == "article":
        return True                                    # 사이트가 직접 선언
    return len(fetch_text(url, page=page) or "") >= MIN_ARTICLE_CHARS


@contextlib.contextmanager
def _socket_timeout(sec: float):
    """소켓 기본 타임아웃을 한시적으로 건다.

    feedparser.parse() 에는 타임아웃 인자가 없어 전역 기본값을 쓸 수밖에 없다.
    전역 상태라 같은 프로세스의 다른 호출에도 영향을 주므로 반드시 복원한다.
    """
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(sec)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old)


def _parse_feed(url: str):
    """타임아웃을 건 feedparser.parse. 기형 주소면 빈 결과를 돌려준다.

    feedparser 는 내부에서 urlparse 를 써서 기형 주소에 ValueError 를 낸다.
    3단계의 자동탐지는 페이지 HTML 의 href 로 주소를 만들기 때문에,
    진입부 검증을 통과한 URL 이어도 여기서 기형이 될 수 있다.
    """
    try:
        with _socket_timeout(FEED_TIMEOUT):
            return feedparser.parse(url)
    except ValueError:
        return feedparser.parse("")  # entries 가 빈 FeedParserDict


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.replace("www.", "")
    except Exception:
        return url


def _from_feed(feed, source_hint: str) -> list[dict]:
    src = (feed.feed.get("title") if getattr(feed, "feed", None) else "") or source_hint
    items = []
    for e in (feed.entries or [])[:PER_SOURCE]:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        items.append({
            "title": title, "link": link,
            "summary": e.get("summary") or e.get("description") or "",
            "pub": "", "source": src,
        })
    return items


# discover() 가 돌려줄 수 있는 해석경로 라벨 8개. collect.py 가 집계 키로 쓰는데,
# collect.py 는 자체 예외 처리 경로에서 열 번째 키 "에러" 를 따로 더 쓴다.
RESOLVE_LABELS = (
    "피드직접", "플랫폼규칙", "자동탐지", "경로추측",
    "단일글", "피드없음·목록페이지", "접속실패", "빈입력", "잘못된주소",
)


def discover(url: str) -> tuple[list[dict], str]:
    """URL 형태를 자동 판별해 (글 목록, 해석경로) 를 돌려준다.

    실패해도 예외를 밖으로 던지지 않는다. 소스 하나가 죽어도 파이프라인은 계속 간다.
    """
    url = url.strip()
    if not url or url.startswith("#"):
        return [], "빈입력"

    # 주소 형식은 여기서 한 번만 검증한다. 기형이면(예: 닫히지 않은 IPv6 대괄호)
    # 어느 단계로 가도 파싱에서 터지므로, 뒤로 넘기지 않고 전용 라벨로 끊는다.
    # 라벨이 있어야 "my_sources.txt 의 그 줄이 오타다" 를 품질기록만 보고 안다.
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return [], "잘못된주소"

    started = time.monotonic()

    # ① URL 자체가 피드인가.
    #    반드시 규칙표(②)보다 먼저다. 사용자가 피드 주소를 그대로 넣었을 때
    #    규칙표가 거기에 피드 경로를 또 덧붙이는 것(medium.com/feed/feed)을 막는다.
    feed = _parse_feed(url)
    if feed.entries:
        return _from_feed(feed, _domain(url)), "피드직접"

    # ② 플랫폼 규칙표. 피드를 스스로 선언하지 않는 곳(벨로그·미디엄 등).
    guess = resolve_feed(url)
    if guess:
        pf = _parse_feed(guess)
        if pf.entries:
            return _from_feed(pf, _domain(url)), "플랫폼규칙"

    # ③·④ 를 위해 어차피 HTML 이 필요하므로 여기서 한 번만 받는다.
    page = _fetch_html(url)

    # SOURCE_BUDGET 을 처음 검사하는 지점이 여기다. ①·② 의 _parse_feed 두 번과
    # HTML 요청 한 번이 이미 다 끝난 뒤라, 이 시점까지 최악의 경우 약 34초
    # (8+8+18)가 예산과 무관하게 먼저 흐른다. 여기서부터는 ③ 자동탐지·⑤ 경로
    # 추측만 예산으로 건너뛰고, 남으면 바로 ④ 단일 글 판정으로 간다.
    budget_left = time.monotonic() - started <= SOURCE_BUDGET

    # ③ 사이트가 스스로 선언한 피드. 추측(⑤)보다 정확하므로 먼저 본다.
    if page and budget_left:
        m = re.search(
            r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', page, re.I)
        if m:
            href = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.I)
            if href:
                df = _parse_feed(urllib.parse.urljoin(url, href.group(1)))
                if df.entries:
                    return _from_feed(df, _domain(url)), "자동탐지"

    # ④ 단일 글 폴백. 경로 추측(⑤)보다 먼저 본다: 개별 글 URL 인데 그 페이지에
    # <link rel=alternate> 가 없는 경우, ⑤ 가 먼저 돌면 블로그 루트 피드를 찾아내
    # 사용자가 요청한 글 하나 대신 블로그 최근 글 목록을 돌려주는 오작동이 난다.
    # 가드(accept_as_article)를 통과할 때만 단일 글로 취급한다.
    if page and accept_as_article(url, page):
        title = _meta(page, "og:title")
        if not title:
            t = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            title = html.unescape(t.group(1)).strip() if t else _domain(url)
        body = fetch_text(url, page=page)
        return [{"title": title[:200], "link": url,
                 "summary": body or "", "pub": "", "source": _domain(url)}], "단일글"

    # ⑤ 흔한 피드 경로 추측. 예전엔 루트 URL 에만 돌았는데, 그 조건 때문에
    #    d2.naver.com/home 같은 주소가 통째로 건너뛰어졌다. 이제 경로가 있어도 시도한다.
    #    다만 모든 URL 에 대해 5번을 두드리게 되므로 총 시간 예산으로 끊는다.
    if budget_left:
        origin = f"{parts.scheme}://{parts.netloc}"
        for suffix in ("/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml"):
            if time.monotonic() - started > SOURCE_BUDGET:
                break
            cf = _parse_feed(origin + suffix)
            if cf.entries:
                return _from_feed(cf, _domain(url)), "경로추측"

    if page:
        return [], "피드없음·목록페이지"
    return [], "접속실패"


def discover_and_fetch(url: str) -> list[dict]:
    """하위 호환 래퍼. 해석경로가 필요 없는 호출부를 위해 목록만 돌려준다."""
    return discover(url)[0]
