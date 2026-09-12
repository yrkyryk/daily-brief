# -*- coding: utf-8 -*-
"""
notion_publish.py — ★ 읽을 가치 픽을 Notion 데이터베이스에 카드로 저장 (6단계 Publish)

입력: data/picks_YYYY-MM-DD.json  (report.py 가 생성한 '읽을 가치' 픽 목록)
동작: 각 픽을 Notion DB 페이지(카드)로 업로드. Hash 로 중복을 막아 멱등하다.
인증: 환경변수
  - NOTION_TOKEN   : Notion 내부 통합 토큰 (ntn_... / secret_...)
  - NOTION_DB_ID   : 대상 데이터베이스 ID
토큰/DB 미설정 시 안내만 출력하고 그냥 넘어간다(파이프라인 중단 없음).

일회성 DB 생성:
  NOTION_TOKEN=... python src/notion_publish.py --create-db <parent_page_id>
  → 스키마대로 DB 를 만들고 DB ID 를 출력한다.

의존성 없음(표준 라이브러리 urllib 만 사용).
"""
import json, os, re, sys, time, pathlib, urllib.request, urllib.error, urllib.parse, datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).strftime("%Y-%m-%d")
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# 카드(=DB 페이지)의 속성 스키마. --create-db 와 발행에서 공통으로 쓴다.
DB_TITLE = "Daily Brief 카드뉴스"
CATEGORIES = ["경제", "사회", "연예", "실무"]


RETRY_STATUS = {429, 500, 502, 503, 504}


def _req(method: str, path: str, token: str, body: dict | None = None,
         attempts: int = 4) -> dict:
    """Notion REST 호출. 일시적 오류(연결 리셋·429·5xx)는 지수 백오프로 재시도."""
    url = path if path.startswith("http") else f"{API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Notion-Version", NOTION_VERSION)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUS and attempt < attempts:
                time.sleep(min(2 ** attempt, 10))
                continue
            detail = e.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"Notion API {method} {path} → {e.code}: {detail}") from None
        except urllib.error.URLError as e:  # 연결 리셋/타임아웃 등 일시 오류
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 10))
                continue
            raise RuntimeError(f"Notion API {method} {path} 연결 실패: {e.reason}") from None
    raise RuntimeError(f"Notion API {method} {path} 재시도 소진")


def _rt(text: str) -> list:
    """rich_text 속성 값 (2000자 제한 안전 절단)."""
    return [{"type": "text", "text": {"content": (text or "")[:1900]}}]


_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*>', re.I)
_CONTENT_RE = re.compile(r'content=["\']([^"\']+)["\']', re.I)


def fetch_og_image(article_url: str) -> str | None:
    """기사 페이지에서 og:image(없으면 twitter:image) URL 추출. 실패 시 None."""
    if not article_url:
        return None
    try:
        req = urllib.request.Request(article_url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; DailyBriefBot/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            head = resp.read(200_000).decode("utf-8", "replace")  # <head> 근처면 충분
        for tag in _OG_RE.findall(head):
            m = _CONTENT_RE.search(tag)
            if m:
                img = urllib.parse.urljoin(article_url, m.group(1).strip())
                if img.startswith("http"):
                    return img
    except Exception:
        pass
    return None


def create_db(token: str, parent_page_id: str) -> str:
    """부모 페이지 아래에 카드뉴스 DB 를 생성하고 DB ID 반환."""
    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": DB_TITLE}}],
        "properties": {
            "제목": {"title": {}},
            "카테고리": {"select": {"options": [{"name": c} for c in CATEGORIES]}},
            "출처": {"rich_text": {}},
            "링크": {"url": {}},
            "읽을이유": {"rich_text": {}},
            "요약": {"rich_text": {}},
            "날짜": {"date": {}},
            "월": {"rich_text": {}},
            "Hash": {"rich_text": {}},
        },
    }
    res = _req("POST", "/databases", token, body)
    return res["id"]


def existing_pages(token: str, db_id: str, date: str) -> dict:
    """해당 날짜에 이미 저장된 카드: Hash -> {page_id, has_cover}."""
    pages, cursor = {}, None
    while True:
        body = {
            "filter": {"property": "날짜", "date": {"equals": date}},
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor
        res = _req("POST", f"/databases/{db_id}/query", token, body)
        for page in res.get("results", []):
            props = page.get("properties", {})
            hp = props.get("Hash", {}).get("rich_text", [])
            h = hp[0].get("plain_text", "") if hp else ""
            if h:
                pages[h] = {
                    "page_id": page["id"],
                    "has_cover": bool(page.get("cover")),
                    "has_month": bool(props.get("월", {}).get("rich_text", [])),
                }
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return pages


def ensure_month_property(token: str, db_id: str) -> None:
    """기존 DB에 '월'(YYYY-MM) rich_text 속성이 없으면 추가(멱등)."""
    _req("PATCH", f"/databases/{db_id}", token, {"properties": {"월": {"rich_text": {}}}})


def _cover(image_url: str | None) -> dict | None:
    return {"type": "external", "external": {"url": image_url}} if image_url else None


def create_card(token: str, db_id: str, pick: dict, image_url: str | None) -> None:
    """픽 1건을 DB 페이지(카드)로 생성. image_url 있으면 페이지 커버로 설정."""
    props = {
        "제목": {"title": [{"type": "text", "text": {"content": pick["title"][:1900]}}]},
        "카테고리": {"select": {"name": pick["cat"]}},
        "출처": {"rich_text": _rt(pick.get("source", ""))},
        "읽을이유": {"rich_text": _rt(pick.get("why", ""))},
        "요약": {"rich_text": _rt(pick.get("summary", ""))},
        "날짜": {"date": {"start": pick.get("date", TODAY)}},
        "월": {"rich_text": _rt(pick.get("date", TODAY)[:7])},  # YYYY-MM
        "Hash": {"rich_text": _rt(pick.get("hash", ""))},
    }
    link = pick.get("link", "")
    if link:
        props["링크"] = {"url": link}
    body = {"parent": {"database_id": db_id}, "properties": props}
    cover = _cover(image_url)
    if cover:
        body["cover"] = cover
    _req("POST", "/pages", token, body)


def patch_page(token: str, page_id: str, image_url: str | None, month: str | None) -> None:
    """기존 카드에 커버/월 백필. 설정할 게 있으면 한 번의 PATCH."""
    body: dict = {}
    if image_url:
        body["cover"] = _cover(image_url)
    if month:
        body["properties"] = {"월": {"rich_text": _rt(month)}}
    if body:
        _req("PATCH", f"/pages/{page_id}", token, body)


def purge_today(token: str, db_id: str) -> int:
    """오늘(KST) 날짜의 카드를 모두 아카이브(삭제 처리). 반복 실행으로 생긴 잉여 정리용."""
    pages = existing_pages(token, db_id, TODAY)
    n = 0
    for info in pages.values():
        _req("PATCH", f"/pages/{info['page_id']}", token, {"archived": True})
        n += 1
    print(f"Notion 정리: {TODAY} 카드 {n}장 아카이브")
    return 0


def publish_from(token: str, db_id: str, path: str) -> int:
    """리포트에서 사용자가 고른 카드(JSON 배열 파일)만 Notion에 발행. Hash 멱등."""
    cards = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(cards, list) or not cards:
        print("선택된 카드가 없습니다."); return 0
    ensure_month_property(token, db_id)
    seen: set = set()
    for d in {c.get("date", TODAY) for c in cards}:
        seen |= set(existing_pages(token, db_id, d).keys())
    created = skipped = covered = 0
    for c in cards:
        if c.get("hash", "") in seen:
            skipped += 1
            continue
        img = fetch_og_image(c.get("link", ""))
        create_card(token, db_id, c, img)
        seen.add(c.get("hash", ""))
        created += 1
        if img:
            covered += 1
    print(f"Notion 선택 발행 완료: 생성 {created} · 커버 {covered} "
          f"· 중복 생략 {skipped} · 대상 {len(cards)}")
    return 0


def publish() -> int:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    db_id = os.environ.get("NOTION_DB_ID", "").strip()
    if not token or not db_id:
        print("[안내] Notion 미설정 (NOTION_TOKEN/NOTION_DB_ID 없음) → 카드 저장 생략. "
              "발급 후 시크릿/환경변수 등록하면 자동 저장됩니다.")
        return 0

    picks_path = ROOT / "data" / f"picks_{TODAY}.json"
    if not picks_path.exists():
        print(f"[안내] {picks_path.name} 없음 → 저장할 픽 없음 (report.py 를 먼저 실행).")
        return 0
    picks = json.loads(picks_path.read_text(encoding="utf-8"))
    if not picks:
        print("[안내] 읽을 가치 픽 0건 → 저장 생략.")
        return 0

    ensure_month_property(token, db_id)  # 기존 DB에 '월' 속성 보강(멱등)
    pages = existing_pages(token, db_id, TODAY)
    created = skipped = covered = backfilled = 0
    for pick in picks:
        h = pick.get("hash", "")
        month = pick.get("date", TODAY)[:7]
        existing = pages.get(h)
        if existing is None:
            img = fetch_og_image(pick.get("link", ""))
            create_card(token, db_id, pick, img)
            created += 1
            if img:
                covered += 1
        else:
            skipped += 1
            img = None if existing["has_cover"] else fetch_og_image(pick.get("link", ""))
            need_month = None if existing["has_month"] else month
            if img or need_month:
                patch_page(token, existing["page_id"], img, need_month)
                if img:
                    covered += 1
                if need_month:
                    backfilled += 1
    print(f"Notion 카드 저장 완료: 생성 {created} · 커버 {covered} · 월 백필 {backfilled} "
          f"· 중복 생략 {skipped} · 대상 {len(picks)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--create-db":
        tok = os.environ.get("NOTION_TOKEN", "").strip()
        if not tok:
            print("환경변수 NOTION_TOKEN 이 필요합니다."); sys.exit(1)
        new_id = create_db(tok, sys.argv[2].strip())
        print(f"DB 생성됨. NOTION_DB_ID={new_id}")
        sys.exit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "--purge-today":
        tok = os.environ.get("NOTION_TOKEN", "").strip()
        dbid = os.environ.get("NOTION_DB_ID", "").strip()
        if not tok or not dbid:
            print("NOTION_TOKEN/NOTION_DB_ID 가 필요합니다."); sys.exit(1)
        sys.exit(purge_today(tok, dbid))
    if len(sys.argv) >= 3 and sys.argv[1] == "--from":
        tok = os.environ.get("NOTION_TOKEN", "").strip()
        dbid = os.environ.get("NOTION_DB_ID", "").strip()
        if not tok or not dbid:
            print("NOTION_TOKEN/NOTION_DB_ID 가 필요합니다."); sys.exit(1)
        sys.exit(publish_from(tok, dbid, sys.argv[2]))
    sys.exit(publish())
