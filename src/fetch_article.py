# -*- coding: utf-8 -*-
"""
fetch_article.py — 사용자 커스텀 소스(블로그 홈/개별 글) 수집.

discover_and_fetch(url):
  1) feedparser 로 파싱 시도(URL 자체가 RSS/Atom) → 최근 글 목록
  2) 없으면 HTML 에서 <link rel="alternate" type="application/rss+xml"> 피드 탐지 → 재시도
  3) 그래도 없으면 그 페이지를 '단일 글'로 취급 (og:title + 본문 발췌)

실패해도 예외를 밖으로 던지지 않고 빈 목록/None 을 돌려 파이프라인이 계속 진행되게 한다.
표준 라이브러리 + feedparser(기존 의존성)만 사용.
"""
import contextlib, re, html, socket, urllib.request, urllib.error, urllib.parse, time
import feedparser

UA = "Mozilla/5.0 (compatible; DailyBriefBot/1.0; +https://github.com/yrkyryk/daily-brief)"
PER_SOURCE = 5          # 피드/홈에서 가져올 최근 글 수
BODY_CAP = 1500         # 본문 발췌 최대 길이
FETCH_TIMEOUT = 8       # HTML 한 번 받는 데 쓰는 상한(초)
FEED_TIMEOUT = 8        # feedparser 한 번에 쓰는 상한(초)
SOURCE_BUDGET = 20      # 소스 하나에 쓰는 총 상한(초). 경로 추측 단계를 끊는 데 쓴다

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
    """타임아웃을 건 feedparser.parse."""
    with _socket_timeout(FEED_TIMEOUT):
        return feedparser.parse(url)


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


# discover() 가 돌려줄 수 있는 해석경로 라벨. collect.py 가 집계 키로 쓴다.
RESOLVE_LABELS = (
    "피드직접", "플랫폼규칙", "자동탐지", "경로추측",
    "단일글", "피드없음·목록페이지", "접속실패", "빈입력",
)


def discover(url: str) -> tuple[list[dict], str]:
    """URL 형태를 자동 판별해 (글 목록, 해석경로) 를 돌려준다.

    실패해도 예외를 밖으로 던지지 않는다. 소스 하나가 죽어도 파이프라인은 계속 간다.
    """
    url = url.strip()
    if not url or url.startswith("#"):
        return [], "빈입력"

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

    # ⑤ 를 위해 어차피 HTML 이 필요하므로 여기서 한 번만 받는다.
    page = _fetch_html(url)

    # ③ 사이트가 스스로 선언한 피드. 추측(④)보다 정확하므로 먼저 본다.
    if page:
        m = re.search(
            r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', page, re.I)
        if m:
            href = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.I)
            if href:
                df = _parse_feed(urllib.parse.urljoin(url, href.group(1)))
                if df.entries:
                    return _from_feed(df, _domain(url)), "자동탐지"

    # ④ 흔한 피드 경로 추측. 예전엔 루트 URL 에만 돌았는데, 그 조건 때문에
    #    d2.naver.com/home 같은 주소가 통째로 건너뛰어졌다. 이제 경로가 있어도 시도한다.
    #    다만 모든 URL 에 대해 5번을 두드리게 되므로 총 시간 예산으로 끊는다.
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    for suffix in ("/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml"):
        if time.monotonic() - started > SOURCE_BUDGET:
            break
        cf = _parse_feed(origin + suffix)
        if cf.entries:
            return _from_feed(cf, _domain(url)), "경로추측"

    # ⑤ 단일 글 폴백. 가드를 통과할 때만이다.
    if page and accept_as_article(url, page):
        title = _meta(page, "og:title")
        if not title:
            t = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            title = html.unescape(t.group(1)).strip() if t else _domain(url)
        body = fetch_text(url, page=page)
        return [{"title": title[:200], "link": url,
                 "summary": body or "", "pub": "", "source": _domain(url)}], "단일글"

    if page:
        return [], "피드없음·목록페이지"
    return [], "접속실패"


def discover_and_fetch(url: str) -> list[dict]:
    """하위 호환 래퍼. 해석경로가 필요 없는 호출부를 위해 목록만 돌려준다."""
    return discover(url)[0]
