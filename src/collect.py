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

# 상세 홍보 판정(③): 가격·구매처·행사기간 세 축 중 2축 이상이 걸릴 때만 홍보로 본다.
# 각 축은 '상거래 문맥'이 붙을 때만 켜진다. 단순 금액·기업명·마감일 자체는 홍보 신호가 아니다.
#   "쿠팡 3분기 영업이익 1000억원 기록"   → 금액과 기업명뿐, 어느 축도 안 켜짐
#   "선착순 5000명에 교통비 10만원 지원"  → 기간축만, 통과
#   "정부, 10월 31일까지 유류세 인하"      → 마감일 뒤가 판매 동사가 아님, 통과
#   "9,900원에 판매, 공식몰 선착순"        → 3축, 제외
_MONEY = r"\d[\d,]*\s*(?:만|억|조)?\s*원"
_TRADE = r"판매|구매|구입|출시|증정|할인|주문|배송|적립|정가"
_SELL = r"진행|판매|할인|증정|응모|구매"

PROMO_AXES = [
    # 금액은 판매 동사와 12자 안에 붙어 있을 때만 가격축으로 센다.
    ("가격", re.compile(
        rf"\d+\s*%\s*(?:할인|세일|적립)|반값|무료\s*배송|배송비\s*무료"
        rf"|(?:{_TRADE})[^.]{{0,12}}?{_MONEY}"
        rf"|{_MONEY}[^.]{{0,12}}?(?:{_TRADE})")),
    # 유통 기업명은 실적·규제 기사에 상시 등장하므로 조사가 붙은 형태만 센다.
    ("구매처", re.compile(
        r"스마트스토어|공식몰|공식\s*스토어|자사몰|온라인몰"
        r"|(?:쿠팡|네이버쇼핑|지마켓|11번가)\s*에서"
        r"|예약\s*판매|에서\s*(?:구매|구입|판매)")),
    # 마감일 단독은 신호가 아니다("18일까지 참여자 모집" 같은 정책 기사가 걸린다).
    # 날짜는 뒤에 판매·행사 동사가 따라올 때만 기간축으로 인정한다.
    ("기간", re.compile(
        r"선착순|한정\s*수량|한정\s*판매|기간\s*한정"
        r"|이벤트\s*기간|행사\s*기간|소진\s*시\s*까지|마감\s*임박"
        rf"|(?:\d+월\s*)?\d+일\s*까지(?:만)?[^.]{{0,12}}?(?:{_SELL})")),
]
PROMO_AXIS_MIN = 2

PER_SOURCE = 12  # 소스당 상위 N건

# 뉴스 카테고리는 "최근 24시간" 것만 남긴다(밤사이 뉴스 위주).
# 기술블로그(실무)·내소스는 드물게 발행되므로 시간 필터를 걸지 않는다.
# 발행시각(published_parsed)이 있는 경우에만 필터하고, 없으면 유지한다
# (한겨레·경향 등 일부 RSS는 파싱 가능한 날짜를 안 주므로 과도한 누락 방지).
NEWS_CATS = {"경제", "사회", "연예"}
FRESH_HOURS = 24


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
    """홍보성이면 판정 사유를, 아니면 None 을 돌려준다."""
    text = f"{title} {summary}"
    low = text.lower()
    for kw in PROMO_KEYWORDS:
        if kw.lower() in low:
            return kw
    hit = [name for name, pat in PROMO_AXES if pat.search(text)]
    if len(hit) >= PROMO_AXIS_MIN:
        return f"상세홍보({'+'.join(hit)})"
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
    old_removed = 0
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=FRESH_HOURS)

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
                pub_dt = None
                if e.get("published_parsed"):
                    pub_dt = datetime.datetime(*e.published_parsed[:6], tzinfo=datetime.timezone.utc)
                # 뉴스 카테고리는 발행시각이 있고 24시간보다 오래된 기사면 제외
                if src["cat"] in NEWS_CATS and pub_dt is not None and pub_dt < cutoff:
                    old_removed += 1
                    continue
                pub = pub_dt.astimezone(KST).strftime("%m-%d %H:%M") if pub_dt else ""
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

    checklist = {
        "수집_소스": f"{ok_sources}/{len(SOURCES)} 성공",
        "총_수집건수": total,
        "홍보_제거건수": promo_removed,
        "중복_제거건수": dup_removed,
        "오래된뉴스_제외건수": old_removed,
        "카테고리_분포": by_cat,
    }
    gate_pass = not (total == 0 or ok_sources == 0)

    print("\n=== V3 품질 체크리스트 (수집 단계) ===")
    print(json.dumps(checklist, ensure_ascii=False, indent=2))
    print(f"저장: {out_path}")

    # V3 품질 기록을 영구 파일로 남긴다(커밋 대상). Actions 로그는 수십 일 뒤 삭제되므로,
    # 재현·추적 가능한 검증 근거를 git 히스토리에 보존한다. 하루 여러 번 실행되므로 배열로 누적.
    snapshot = {
        "실행시각_KST": datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        **checklist,
        "품질_게이트": "PASS" if gate_pass else "FAIL",
    }
    q_path = out_dir / f"quality_{TODAY}.json"
    history: list = []
    if q_path.exists():
        try:
            loaded = json.loads(q_path.read_text(encoding="utf-8"))
            history = loaded if isinstance(loaded, list) else [loaded]
        except Exception:
            history = []
    history.append(snapshot)
    q_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"품질 기록: data/{q_path.name} ({len(history)}번째 스냅샷)")

    # 자동 점검 게이트: 전부 실패하거나 0건이면 중단
    if not gate_pass:
        print("품질 게이트: FAIL (수집 0건 또는 전 소스 실패) → exit 1")
        return 1
    print("품질 게이트: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(collect())
