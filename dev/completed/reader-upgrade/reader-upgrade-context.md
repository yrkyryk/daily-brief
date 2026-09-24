# reader-upgrade · Context

> ## 완료 기록 (2026-09-25)
>
> 3개 Phase 의 산출물이 모두 코드에 존재하는 것을 확인했다.
> 체크박스는 당시에 채우지 않았으나 실물로 검증했다.
>
> - Phase 1: `my_sources.txt`, `src/fetch_article.py`, `collect.py` 의 내소스 병합
> - Phase 2: `interests.txt`, `src/interests.py`(`load()`/`match()`), `report.py` 관심 섹션
> - Phase 3: `notion_publish.py --from`, `daily.yml` 에서 Notion 단계 제거됨
>
> 이후 `fetch_article.py` 는 blog-crawl 태스크에서 크게 개편됐다.
> 이 문서의 파일 설명은 2026-09-11 시점 기준이므로 현재 코드와 다르다.

Last Updated: 2026-09-11

## 목표
Daily Brief를 개인화 리더로 확장: 커스텀 소스 + 관심 키워드 섹션 + Notion 수동 선택 발행.
승인된 계획 전문: `~/.claude/plans/zany-cooking-wozniak.md`

## 핵심 파일
- `src/collect.py` — 수집+규칙필터 → data/raw_YYYY-MM-DD.jsonl. SOURCES 리스트, raw_items/seen dedup 로직.
- `src/report.py` — AI 요약+HTML 리포트. CAT_ORDER/by_cat, pick_map(src/report.py:91), 카드 조립(104-114), HTML 템플릿(133+), 하단 JS(220+). data/picks 내보내기.
- `src/judge_ai.py` — 카테고리당 1회 Claude 호출(OAuth CLI).
- `src/notion_publish.py` — Notion REST(표준 라이브러리). _req(재시도), create_card, existing_pages, ensure_month_property, fetch_og_image, purge_today, publish. __main__에 --create-db/--purge-today.
- `.github/workflows/daily.yml` — cron; "Publish cards to Notion" 단계 있음(수동 전환 대상). reset_today input.

## 의사결정
- 커스텀 소스: 둘 다(피드/홈→최근글, 아티클→그 글). RSS 자동탐지 후 단일글 폴백.
- 관심 키워드: interests.txt 키워드 목록 → 결정론적 매칭. 리포트 상단 전용 섹션.
- Notion: 자동 제거, 사용자가 리포트에서 고른 카드만 수동 발행(--from selected.json).
- 신규 파이썬 의존성 없음(feedparser 재사용). 실패 폴백=무회귀.

## 검증
로컬: my_sources.txt + interests.txt 작성 → collect → report → docs/index.html 브라우저 확인. Notion은 selected.json → notion_publish --from.
