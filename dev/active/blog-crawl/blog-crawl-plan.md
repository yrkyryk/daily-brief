# 블로그 글 수집 개선 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RSS 를 스스로 선언하지 않는 블로그(벨로그·미디엄·D2)를 `my_sources.txt` 에 넣어도 매일 브리핑에 정상 합류하게 하고, 목록 페이지가 '글 하나'로 둔갑해 유입되는 것을 막는다.

**Architecture:** `fetch_article.py` 의 폴백 체인을 5단계로 재정리하고, 판단 로직 두 개(`resolve_feed`, `accept_as_article`)를 네트워크를 타지 않는 순수 함수로 분리한다. 순수 함수라야 네트워크 없이 테스트할 수 있고, 이 계획의 테스트 전략 전체가 거기에 의존한다. 네트워크를 타는 `discover()` 는 (글 목록, 해석경로) 쌍을 돌려주고 `collect.py` 가 그 경로를 품질기록에 집계한다.

**Tech Stack:** Python 3.11+ · 표준 라이브러리 · feedparser (기존 의존성). **새 의존성 추가 없음**

**Spec:** `dev/active/blog-crawl/blog-crawl-design.md`

## Global Constraints

- 새 의존성 추가 금지. 표준 라이브러리 + `feedparser` 만 사용한다 (`requirements.txt` 는 `feedparser>=6.0` 한 줄).
- 테스트는 pytest 가 아니다. 이 레포는 **단독 실행 스크립트** 관례를 쓴다
  (`python tests/test_promo.py`, `check()` 로 실패를 모아 마지막에 한 번 출력, 실패 시 `sys.exit(1)`).
  CI 에는 테스트 단계가 없다. 새 테스트도 같은 형식을 따른다.
- 기본 테스트 실행은 **네트워크를 타지 않는다.** 네트워크 테스트는 `--network` 플래그로만 돈다.
- 주석·문자열·커밋 메시지는 한국어. 코드 식별자는 영어 (기존 파일 관례).
- 엠대시 사용 금지.
- 품질 게이트(`collect.py` 의 exit 1) 조건은 **바꾸지 않는다.** 내소스는 선택 기능이고 0건이 곧 장애는 아니다.
- 기존 공개 함수 `discover_and_fetch(url) -> list[dict]` 의 시그니처는 유지한다 (하위 호환).

## 파일 구조

| 파일 | 책임 | 변경 |
|---|---|---|
| `src/fetch_article.py` | 커스텀 소스 URL → 글 목록. 규칙표·가드·체인·타임아웃 | 수정 (주 변경) |
| `tests/test_fetch_blog.py` | 순수 함수 2개 검증 + `--network` 통합 검증 | 신규 |
| `src/collect.py` | 해석경로 집계 → `quality_*.json` | 수정 (약 12줄) |
| `my_sources.txt` | 지원 플랫폼 안내 주석 | 수정 (주석만) |
| `README.md` | '한계' 문단 갱신 | 수정 (문단 1개) |

`fetch_article.py` 는 현재 150줄로 작고 응집도가 높다. 분할하지 않는다.

## 작업 순서와 이유

Task 1~2 는 순수 함수라 네트워크 없이 완결된다. Task 3 은 타임아웃 도구를 깔고,
Task 4 가 그 셋을 엮어 체인을 재구성한다. Task 5 는 소비자(`collect.py`)를 맞춘다.
Task 6 이 실제 사이트로 완료 기준을 증명한다.

Task 4 전까지는 동작이 바뀌지 않는다. 즉 Task 1~3 은 언제든 안전하게 커밋된다.

---

### Task 1: 플랫폼 규칙표 `resolve_feed()`

**Files:**
- Modify: `src/fetch_article.py` (`BODY_CAP = 1500` 18행 바로 아래)
- Test: `tests/test_fetch_blog.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces: `resolve_feed(url: str) -> str | None`: 규칙표에 걸리면 피드 URL 문자열, 아니면 `None`. 네트워크를 타지 않는다. Task 4 가 체인 ② 단계에서 쓴다.
- Produces: `PLATFORM_FEEDS: list[tuple[re.Pattern, str]]`: Task 6 이 존재를 확인한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_fetch_blog.py` 를 새로 만든다. `tests/test_promo.py` 의 형식을 그대로 따른다.

```python
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
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `AttributeError: module 'fetch_article' has no attribute 'resolve_feed'`

- [ ] **Step 3: 최소 구현을 넣는다**

`src/fetch_article.py` 의 `BODY_CAP = 1500` (18행) 아래에 추가한다.

```python

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
```

`d2` 규칙은 캡처 그룹이 없어 `m.groups()` 가 빈 튜플이고, 템플릿에도 `{0}` 이 없으므로 `format()` 이 원문을 그대로 돌려준다.

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `OK: 9 checks passed`

- [ ] **Step 5: 커밋**

```bash
git add tests/test_fetch_blog.py src/fetch_article.py
git commit -m "feat: 블로그 플랫폼 피드 주소 규칙표 resolve_feed 추가"
```

---

### Task 2: 단일글 폴백 가드 `accept_as_article()`

**Files:**
- Modify: `src/fetch_article.py` (`fetch_text()` 정의 뒤. Step 3 참조)
- Test: `tests/test_fetch_blog.py`

**Interfaces:**
- Consumes: 기존 `_meta(page, prop) -> str` (38행), 기존 `fetch_text(url, page) -> str | None` (57행)
- Produces: `accept_as_article(url: str, page: str) -> bool`: `page` 를 넘겨받으므로 네트워크를 타지 않는다. Task 4 가 체인 ⑤ 단계에서 쓴다.
- Produces: `MIN_ARTICLE_CHARS: int` (= 200)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_fetch_blog.py` 의 `def run()` **앞**에 추가한다.

```python
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
```

`run()` 안에 호출을 추가한다.

```python
def run() -> None:
    test_resolve_feed()
    test_accept_as_article()
    if FAILURES:
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `AttributeError: module 'fetch_article' has no attribute 'accept_as_article'`

- [ ] **Step 3: 최소 구현을 넣는다**

`src/fetch_article.py` 의 `fetch_text()` 정의(57행) **뒤**에 추가한다.
`_meta` 와 `fetch_text` 를 쓰므로 읽는 순서를 맞추기 위해서다.

```python

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
```

`fetch_text(url, page=page)` 는 `page` 를 넘기므로 네트워크를 타지 않는다 (57행 구현 참조).

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `OK: 21 checks passed`

- [ ] **Step 5: 커밋**

```bash
git add tests/test_fetch_blog.py src/fetch_article.py
git commit -m "feat: 목록·프로필 페이지가 글로 둔갑하는 것을 막는 가드 추가"
```

---

### Task 3: 네트워크 시간 상한

**Files:**
- Modify: `src/fetch_article.py` (import 13행, 상수 블록, `_fetch_html` 21행, `_domain()` 73행 앞)

**Interfaces:**
- Consumes: 없음
- Produces: `_parse_feed(url: str)`: 타임아웃이 걸린 `feedparser.parse`. Task 4 가 체인의 모든 피드 파싱에 쓴다. 반환 타입은 `feedparser.parse` 와 동일.
- Produces: `_socket_timeout(sec: float)`: 컨텍스트 매니저
- Produces: `FETCH_TIMEOUT = 8`, `FEED_TIMEOUT = 8`, `SOURCE_BUDGET = 20`

**배경:** 실측에서 `www.oopy.io` 한 곳이 17초를 먹었다. 원인은 두 가지다.
`_fetch_html` 이 3회 재시도하며 2·4·8초를 쉬고, `feedparser.parse` 에는 타임아웃 인자가 아예 없다.
도달 불가 호스트로 실측하면 `feedparser` 기본값이 21.2초, `socket.setdefaulttimeout(3)` 을 걸면 3.4초였다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_fetch_blog.py` 의 `def run()` 앞에 추가한다.

```python
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
```

`run()` 에 `test_socket_timeout_restores()` 호출을 추가한다.

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `AttributeError: module 'fetch_article' has no attribute '_socket_timeout'`

- [ ] **Step 3: 최소 구현을 넣는다**

13행 import 를 바꾼다. 바꾸기 전 형태는 다음과 같다.

```python
import re, html, urllib.request, urllib.error, urllib.parse, time
```

바꾼 뒤 형태는 다음과 같다.

```python
import contextlib, re, html, socket, urllib.request, urllib.error, urllib.parse, time
```

`BODY_CAP = 1500` (18행) 아래, Task 1 이 넣은 `PLATFORM_FEEDS` 앞에 상수를 추가한다.

```python
FETCH_TIMEOUT = 8       # HTML 한 번 받는 데 쓰는 상한(초)
FEED_TIMEOUT = 8        # feedparser 한 번에 쓰는 상한(초)
SOURCE_BUDGET = 20      # 소스 하나에 쓰는 총 상한(초). 경로 추측 단계를 끊는 데 쓴다
```

`_fetch_html` (21행) 의 기본 재시도를 줄인다. 바꾸기 전 형태는 다음과 같다.

```python
def _fetch_html(url: str, attempts: int = 3) -> str | None:
```

바꾼 뒤 형태는 다음과 같다.

```python
def _fetch_html(url: str, attempts: int = 2) -> str | None:
```

같은 함수 안의 타임아웃도 바꾼다. 바꾸기 전 형태는 다음과 같다.

```python
            with urllib.request.urlopen(req, timeout=15) as resp:
```

바꾼 뒤 형태는 다음과 같다.

```python
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
```

`_domain()` (73행) 앞에 타임아웃 도구를 추가한다.

```python

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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `OK: 25 checks passed`

- [ ] **Step 5: 커밋**

```bash
git add tests/test_fetch_blog.py src/fetch_article.py
git commit -m "feat: 커스텀 소스 수집에 네트워크 시간 상한 도입"
```

---

### Task 4: 해석 체인 재구성 `discover()`

**Files:**
- Modify: `src/fetch_article.py` (`discover_and_fetch` **함수 전체** 교체. Task 1~3 이 위쪽에 코드를 넣으므로 줄 번호로 찾지 말고 함수 이름으로 찾을 것)

**Interfaces:**
- Consumes: `resolve_feed()` (Task 1), `accept_as_article()` (Task 2), `_parse_feed()` · `SOURCE_BUDGET` (Task 3), 기존 `_from_feed()` (80행) · `_fetch_html()` · `_meta()` · `fetch_text()` · `_domain()`
- Produces: `discover(url: str) -> tuple[list[dict], str]`: (글 목록, 해석경로 라벨). 라벨은 `RESOLVE_LABELS` 의 8개 중 하나. Task 5 가 이 라벨을 집계 키로 쓴다.
- Produces: `RESOLVE_LABELS: tuple[str, ...]`: 라벨 집합. `collect.py` 와의 계약이다.
- Produces: `discover_and_fetch(url: str) -> list[dict]`: 하위 호환 래퍼. 시그니처 불변.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_fetch_blog.py` 의 `def run()` 앞에 추가한다.

```python
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
```

`run()` 에 `test_discover_contract()` 호출을 추가한다.

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `AttributeError: module 'fetch_article' has no attribute 'discover'`

- [ ] **Step 3: 최소 구현을 넣는다**

`discover_and_fetch` 함수 **전체**를 아래로 교체한다. Task 1~3 의 삽입으로 줄 번호가 밀렸으므로 함수 이름으로 찾는다.
기존 1.5절 네이버 특례는 Task 1 의 규칙표가 대체하므로 함께 사라진다.

```python
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `OK: 33 checks passed`

기존 테스트도 깨지지 않았는지 확인한다.

```bash
python tests/test_promo.py && python tests/test_slot.py
```

기대: 둘 다 `OK: ... checks passed`

- [ ] **Step 5: 커밋**

```bash
git add tests/test_fetch_blog.py src/fetch_article.py
git commit -m "refactor: 커스텀 소스 해석을 5단계 체인으로 재구성하고 경로를 반환"
```

---

### Task 5: `collect.py` 해석경로 집계

**Files:**
- Modify: `src/collect.py:167-201` (커스텀 소스 블록), `src/collect.py` 의 `checklist` dict

**Interfaces:**
- Consumes: `fetch_article.discover(url) -> tuple[list[dict], str]` (Task 4)
- Produces: `quality_*.json` 의 `내소스_해석경로` 키 (값은 `{라벨: 건수}` dict). Task 6 이 존재를 확인한다.

**배경:** Actions 로그는 수십 일 뒤 삭제되지만 `data/quality_*.json` 은 커밋돼 남는다.
"왜 이 블로그가 안 들어왔지" 를 로그 없이 품질기록만으로 진단할 수 있어야 한다.
README 의 V3 품질 철학, `diagnose-brief-send` 스킬과 같은 방향이다.

- [ ] **Step 1: 집계 변수를 추가한다**

`src/collect.py:169` 의 `custom_kept = 0` 바로 아래에 추가한다.

```python
    custom_paths: dict[str, int] = {}
```

- [ ] **Step 2: 호출을 `discover()` 로 바꾼다**

`src/collect.py` 의 `discover_and_fetch` 호출부(176행 부근)를 바꾼다. 바꾸기 전 형태는 다음과 같다.

```python
            try:
                kept = 0
                for a in fetch_article.discover_and_fetch(url):
```

바꾼 뒤 형태는 다음과 같다.

```python
            try:
                kept = 0
                items, how = fetch_article.discover(url)
                for a in items:
```

- [ ] **Step 3: 로그와 집계에 라벨을 넣는다**

`src/collect.py` 의 내소스 로그 출력부(197행 부근)를 바꾼다. 바꾸기 전 형태는 다음과 같다.

```python
                custom_kept += kept
                print(f"[내소스] {url[:38]:38s} 수집 {kept}건")
            except Exception as ex:
                print(f"[내소스 에러] {url[:38]} {ex}")
```

바꾼 뒤 형태는 다음과 같다.

```python
                custom_kept += kept
                custom_paths[how] = custom_paths.get(how, 0) + 1
                print(f"[내소스] {url[:38]:38s} 수집 {kept}건 ({how})")
            except Exception as ex:
                custom_paths["에러"] = custom_paths.get("에러", 0) + 1
                print(f"[내소스 에러] {url[:38]} {ex}")
```

- [ ] **Step 4: 품질 체크리스트에 노출한다**

`src/collect.py` 의 `checklist = {` 블록에서 `"카테고리_분포": by_cat,` 바로 아래에 추가한다.

```python
        **({"내소스_해석경로": custom_paths} if custom_paths else {}),
```

내소스가 없으면 키 자체를 넣지 않는다. 기존 품질기록 형태를 불필요하게 바꾸지 않기 위해서다.

- [ ] **Step 5: 실제로 돌려서 확인한다**

```bash
python src/collect.py
```

기대 출력에 라벨이 붙는다.

```
[내소스] https://blog.naver.com/adcsk       수집 5건 (플랫폼규칙)
```

기대 체크리스트에 키가 생긴다.

```json
"내소스_해석경로": {"플랫폼규칙": 1}
```

- [ ] **Step 6: 품질기록 파일에 실제로 쓰였는지 확인한다**

```bash
python -c "import json,glob; p=sorted(glob.glob('data/quality_*.json'))[-1]; print(json.load(open(p,encoding='utf-8'))[-1].get('내소스_해석경로'))"
```

기대: `{'플랫폼규칙': 1}` (`my_sources.txt` 내용에 따라 값은 달라진다). `None` 이 나오면 Step 4 가 안 먹은 것이다.

- [ ] **Step 7: 커밋**

```bash
git add src/collect.py
git commit -m "feat: 내소스 해석경로를 품질기록에 집계"
```

---

### Task 6: 실제 사이트로 완료 기준 증명 + 문서 갱신

**Files:**
- Modify: `tests/test_fetch_blog.py` (`--network` 통합 테스트 추가)
- Modify: `my_sources.txt` (주석)
- Modify: `README.md` ('한계' 문단)

**Interfaces:**
- Consumes: `fetch_article.discover()` (Task 4)
- Produces: 없음 (최종 검증)

- [ ] **Step 1: 통합 테스트를 쓴다**

`tests/test_fetch_blog.py` 의 `def run()` 앞에 추가한다.
대상과 기대값은 스펙 1절 실측표에서 그대로 가져온 것이다.

```python
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
```

`run()` 을 바꿔 플래그를 받게 한다.

```python
def run() -> None:
    test_resolve_feed()
    test_accept_as_article()
    test_socket_timeout_restores()
    test_discover_contract()
    if "--network" in sys.argv:
        print("네트워크 통합 테스트 (실제 사이트 접속):")
        test_network()
    if FAILURES:
```

- [ ] **Step 2: 네트워크 없이 먼저 통과하는지 확인한다**

```bash
python tests/test_fetch_blog.py
```

기대: `OK: 33 checks passed` (네트워크 테스트는 돌지 않음)

- [ ] **Step 3: 네트워크 테스트를 돌려 완료 기준을 증명한다**

```bash
python tests/test_fetch_blog.py --network
```

기대 출력:

```
네트워크 통합 테스트 (실제 사이트 접속):
  https://blog.naver.com/adcsk               5건 (플랫폼규칙, 0.8s)
  https://jojoldu.tistory.com/               5건 (자동탐지, 3.9s)
  https://brunch.co.kr/@svillustrated        5건 (자동탐지, 1.1s)
  https://velog.io/@teo                      5건 (플랫폼규칙, 1.6s)
  https://medium.com/daangn                  5건 (플랫폼규칙, 0.9s)
  https://d2.naver.com/home                  5건 (플랫폼규칙, 1.0s)
  https://www.oopy.io                        0건 (피드없음·목록페이지, ...)
OK: ... checks passed
```

실패하면 라벨을 보고 어느 단계에서 갈렸는지 판단한다. 라벨이 진단 정보다.

- [ ] **Step 4: `my_sources.txt` 주석을 갱신한다**

1-3행의 주석을 바꾼다. 바꾸기 전 형태는 다음과 같다.

```
# 내 커스텀 소스 — 한 줄에 하나씩 URL. (#로 시작하면 주석)
# 블로그/사이트 홈·RSS면 최근 글 자동 수집, 개별 글 링크면 그 글 하나.
# 네이버 블로그는 일반 주소를 넣어도 자동으로 RSS로 가져옵니다.
```

바꾼 뒤 형태는 다음과 같다 (엠대시를 쓰지 않는다).

```
# 내 커스텀 소스: 한 줄에 하나씩 URL. (#로 시작하면 주석)
# 블로그/사이트 홈·RSS면 최근 글 자동 수집, 개별 글 링크면 그 글 하나.
# 홈 주소만 넣어도 되는 곳: 네이버 블로그, 티스토리, 워드프레스,
#   브런치, 벨로그, 미디엄, 네이버 D2.
# 피드가 없는 사이트(노션 기반 등)는 0건으로 빠지고 사유가 로그에 남습니다.
```

- [ ] **Step 5: `README.md` 의 '한계' 문단을 갱신한다**

'## 한계 (명시)' 섹션의 두 번째 항목을 바꾼다. 바꾸기 전 형태는 다음과 같다.

```
- JS로만 렌더되고 RSS 없는 사이트는 제목+요약만(제한적). 네이버 블로그·티스토리·워드프레스 등은 홈 주소만 넣어도 자동 RSS 처리.
```

바꾼 뒤 형태는 다음과 같다.

```
- 홈 주소만 넣어도 되는 블로그: 네이버 블로그·티스토리·워드프레스·브런치·벨로그·미디엄·네이버 D2. 피드를 아예 제공하지 않는 사이트(노션 기반 등)는 0건으로 빠지며, 어느 단계에서 갈렸는지가 `data/quality_*.json` 의 `내소스_해석경로` 에 남는다.
```

- [ ] **Step 6: 전체 테스트와 파이프라인을 돌려 회귀가 없는지 확인한다**

```bash
python tests/test_promo.py && python tests/test_slot.py && python tests/test_fetch_blog.py && python src/collect.py
```

기대: 테스트 3개 전부 `OK`, `collect.py` 가 `품질 게이트: PASS` 로 끝난다.

- [ ] **Step 7: 커밋**

```bash
git add tests/test_fetch_blog.py my_sources.txt README.md
git commit -m "test: 실제 사이트 통합 검증 추가 및 지원 플랫폼 문서화"
```

---

## 완료 기준 대조 (스펙 7절)

| 스펙 완료 기준 | 검증하는 곳 |
|---|---|
| 1. 7개 대상 중 6개 목록 수집, oopy 는 0건 + 사유 | Task 6 Step 3 (`NETWORK_CASES`) |
| 2. 쓰레기 단일글 3건 차단 | Task 2 Step 4 (단위), Task 6 Step 3 (자기 자신 반환 금지) |
| 3. 소스당 17초 → 10초 이내 | Task 6 Step 3 (`check(dt < 10, ...)`) |
| 4. 네트워크 없이 테스트 통과 | Task 6 Step 2 |
| 5. `quality_*.json` 에 `내소스_해석경로` | Task 5 Step 6 |

## 스펙에서 달라진 점

**스펙 4.4 의 시간 예산이 ④ 단계 변경을 계산에 넣지 않았다.**
4.1 에서 ④ 의 `path in ("", "/")` 조건을 없애면 ④ 가 모든 미해결 URL 에 대해
접미사 5개를 두드리게 된다. 스펙이 말한 "소스당 약 5초" 가 깨질 수 있다.
Task 3 에서 `SOURCE_BUDGET = 20` 을 도입하고 Task 4 의 ④ 루프에서 끊는다.
완료 기준 3의 게이트(10초)는 Task 6 이 실측으로 강제한다.
