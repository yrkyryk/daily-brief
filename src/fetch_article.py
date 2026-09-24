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
import re, html, urllib.request, urllib.error, urllib.parse, time
import feedparser

UA = "Mozilla/5.0 (compatible; DailyBriefBot/1.0; +https://github.com/yrkyryk/daily-brief)"
PER_SOURCE = 5          # 피드/홈에서 가져올 최근 글 수
BODY_CAP = 1500         # 본문 발췌 최대 길이

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


def _fetch_html(url: str, attempts: int = 3) -> str | None:
    """HTML 원문. 일시 오류는 지수 백오프로 재시도. 실패 시 None."""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
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


def discover_and_fetch(url: str) -> list[dict]:
    """URL 형태를 자동 판별해 글 목록 반환(홈/피드→여러 개, 아티클→1개)."""
    url = url.strip()
    if not url or url.startswith("#"):
        return []

    # 1) URL 자체가 피드인지
    feed = feedparser.parse(url)
    if feed.entries:
        return _from_feed(feed, _domain(url))

    # 1.5) 네이버 블로그: JS 렌더라 목록 URL은 안 되므로 RSS로 우회
    if "blog.naver.com" in url:
        m = re.search(r"blogId=([A-Za-z0-9_-]+)", url) or re.search(r"blog\.naver\.com/([A-Za-z0-9_-]+)", url)
        if m:
            nf = feedparser.parse(f"https://rss.blog.naver.com/{m.group(1)}.xml")
            if nf.entries:
                return _from_feed(nf, m.group(1))

    # 1.7) 홈 URL이면 흔한 피드 경로 시도 (티스토리 /rss, 워드프레스 /feed 등)
    parts = urllib.parse.urlsplit(url)
    if parts.path in ("", "/"):
        origin = f"{parts.scheme}://{parts.netloc}"
        for suffix in ("/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml"):
            cf = feedparser.parse(origin + suffix)
            if cf.entries:
                return _from_feed(cf, _domain(url))

    # 2) HTML 에서 피드 자동탐지
    page = _fetch_html(url)
    if page:
        m = re.search(
            r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', page, re.I)
        if m:
            href = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.I)
            if href:
                feed_url = urllib.parse.urljoin(url, href.group(1))
                feed = feedparser.parse(feed_url)
                if feed.entries:
                    return _from_feed(feed, _domain(url))

        # 3) 단일 글 폴백
        title = _meta(page, "og:title")
        if not title:
            t = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            title = html.unescape(t.group(1)).strip() if t else _domain(url)
        body = fetch_text(url, page=page)
        return [{"title": title[:200], "link": url,
                 "summary": body or "", "pub": "", "source": _domain(url)}]
    return []
