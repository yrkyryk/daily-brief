# -*- coding: utf-8 -*-
"""
collect.py — 수집(2단계) + 규칙 필터(4단계 일부)

- RSS 소스에서 기사를 모아 홍보/중복을 규칙으로 제거하고 카테고리를 붙여
  data/raw_YYYY-MM-DD.jsonl 로 저장한다. (report.py 의 입력)
- 소스별 성공/실패, 홍보·중복 제거 건수를 V3 품질 지표로 출력한다.
- 소스가 모두 실패하거나 총 수집이 0건이면 exit 1 (자동 점검 게이트).

사람/기계 경계(계획서 2.1): 이 파일은 전부 '기계' 영역 (결정론적, 무료).
"""
import feedparser, hashlib, html, json, re, sys, datetime, urllib.parse, pathlib
import fetch_article

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).strftime("%Y-%m-%d")

# 소스 목록 (뉴스 경제/사회/연예 + 실무 인사이트 블로그)
SOURCES = [
    {"name": "연합뉴스 경제", "cat": "경제", "url": "https://www.yna.co.kr/rss/economy.xml"},
    {"name": "한겨레 경제", "cat": "경제", "url": "https://www.hani.co.kr/rss/economy/"},
    {"name": "경향신문 경제", "cat": "경제", "url": "https://www.khan.co.kr/rss/rssdata/economy_news.xml"},
    {"name": "연합뉴스 사회", "cat": "사회", "url": "https://www.yna.co.kr/rss/society.xml"},
    {"name": "한겨레 사회", "cat": "사회", "url": "https://www.hani.co.kr/rss/society/"},
    {"name": "경향신문 사회", "cat": "사회", "url": "https://www.khan.co.kr/rss/rssdata/society_news.xml"},
    {"name": "연합뉴스 연예", "cat": "연예", "url": "https://www.yna.co.kr/rss/entertainment.xml"},
    {"name": "경향신문 연예", "cat": "연예", "url": "https://www.khan.co.kr/rss/rssdata/culture_news.xml"},
    {"name": "우아한형제들 기술블로그", "cat": "실무", "url": "https://techblog.woowahan.com/feed/"},
    {"name": "토스 기술블로그", "cat": "실무", "url": "https://toss.tech/rss.xml"},
    {"name": "카카오 기술블로그", "cat": "실무", "url": "https://tech.kakao.com/feed/"},
    {"name": "LINE 기술블로그", "cat": "실무", "url": "https://techblog.lycorp.co.jp/ko/feed/index.xml"},
]

PROMO_KEYWORDS = [
    "협찬", "광고", "제휴", "sponsored", "[AD]", "(광고)", "이벤트 응모",
    "할인코드", "쿠폰", "특가", "무료체험", "프로모션", "[보도자료]", "보도자료",
    "출시 기념", "구매 링크", "최저가",
]

PER_SOURCE = 12  # 소스당 상위 N건


def norm_url(u: str) -> str:
    """UTM 등 트래킹 파라미터 제거 + 정규화."""
    try:
        p = urllib.parse.urlsplit(u)
        q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
             if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"),
                                        urllib.parse.urlencode(q), ""))
    except Exception:
        return u


def norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w가-힣]", "", (t or "").lower()))


def is_promo(title: str, summary: str) -> str | None:
    low = f"{title} {summary}".lower()
    for kw in PROMO_KEYWORDS:
        if kw.lower() in low:
            return kw
    return None


def clean_summary(s: str, limit: int = 180) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def collect() -> int:
    raw_items: list[dict] = []
    seen: set[str] = set()
    source_stats: list[tuple[str, str, str, int]] = []
    promo_removed = 0
    dup_removed = 0

    for src in SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            entries = feed.entries or []
            kept = 0
            for e in entries[:PER_SOURCE]:
                title = (e.get("title") or "").strip()
                link = norm_url(e.get("link") or "")
                summary = clean_summary(e.get("summary") or e.get("description") or "")
                if not title or not link:
                    continue
                h = hashlib.sha1((norm_title(title) + "|" + link).encode()).hexdigest()
                if h in seen:
                    dup_removed += 1
                    continue
                seen.add(h)
                if is_promo(title, summary):
                    promo_removed += 1
                    continue
                pub = ""
                if e.get("published_parsed"):
                    pub = datetime.datetime(*e.published_parsed[:6], tzinfo=datetime.timezone.utc)\
                        .astimezone(KST).strftime("%m-%d %H:%M")
                raw_items.append({
                    "title": title, "link": link, "summary": summary,
                    "source": src["name"], "cat": src["cat"], "pub": pub, "hash": h,
                })
                kept += 1
            status = "OK" if entries else "빈응답"
            source_stats.append((src["name"], src["cat"], status, kept))
            print(f"[{status}] {src['name']:22s} 수집 {kept}건")
        except Exception as ex:
            source_stats.append((src["name"], src["cat"], "에러", 0))
            print(f"[에러] {src['name']:22s} {ex}")

    # 커스텀 소스 (my_sources.txt): 사용자가 넣은 블로그 홈/피드/개별 글
    custom_path = ROOT / "my_sources.txt"
    custom_kept = 0
    if custom_path.exists():
        urls = [ln.strip() for ln in custom_path.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        for url in urls:
            try:
                kept = 0
                for a in fetch_article.discover_and_fetch(url):
                    title = (a.get("title") or "").strip()
                    link = norm_url(a.get("link") or "")
                    summary = clean_summary(a.get("summary") or "")
                    if not title or not link:
                        continue
                    h = hashlib.sha1((norm_title(title) + "|" + link).encode()).hexdigest()
                    if h in seen:
                        dup_removed += 1
                        continue
                    seen.add(h)
                    if is_promo(title, summary):
                        promo_removed += 1
                        continue
                    raw_items.append({
                        "title": title, "link": link, "summary": summary,
                        "source": a.get("source") or url, "cat": "내소스",
                        "pub": a.get("pub", ""), "hash": h,
                    })
                    kept += 1
                custom_kept += kept
                print(f"[내소스] {url[:38]:38s} 수집 {kept}건")
            except Exception as ex:
                print(f"[내소스 에러] {url[:38]} {ex}")
    if custom_kept:
        print(f"커스텀 소스 총 {custom_kept}건")

    # 저장
    out_dir = ROOT / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"raw_{TODAY}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for it in raw_items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    total = len(raw_items)
    ok_sources = sum(1 for *_, c in source_stats if c > 0)
    by_cat: dict[str, int] = {}
    for it in raw_items:
        by_cat[it["cat"]] = by_cat.get(it["cat"], 0) + 1

    print("\n=== V3 품질 체크리스트 (수집 단계) ===")
    print(json.dumps({
        "수집_소스": f"{ok_sources}/{len(SOURCES)} 성공",
        "총_수집건수": total,
        "홍보_제거건수": promo_removed,
        "중복_제거건수": dup_removed,
        "카테고리_분포": by_cat,
    }, ensure_ascii=False, indent=2))
    print(f"저장: {out_path}")

    # 자동 점검 게이트: 전부 실패하거나 0건이면 중단
    if total == 0 or ok_sources == 0:
        print("품질 게이트: FAIL (수집 0건 또는 전 소스 실패) → exit 1")
        return 1
    print("품질 게이트: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(collect())
