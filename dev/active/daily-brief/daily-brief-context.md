# Daily Brief 프로젝트 컨텍스트

**Last Updated: 2026-09-10**

## 프로젝트 한 줄

뉴스·블로그를 매일 08:30 자동 수집·필터링해 Notion Daily Brief로 주는 데이터 파이프라인. 데이터 분석가 지원 포트폴리오.

## 핵심 의사결정 (확정)

| 결정 | 내용 | 근거 |
|------|------|------|
| 데이터 소스 | 뉴스 + 블로그 RSS만. **인스타그램 제외** | 공식 API 없음, 크롤링 약관/차단 리스크. v2 보류 |
| 판정 엔진 | **규칙 우선 + AI 보조** | A12 토큰 비용 붕괴 교훈. 수집은 스크립트, 애매한 것만 AI |
| 실행 환경 | GitHub Actions cron | A13 벤치마킹, 무료·무인 |
| 산출물 채널 | Notion DB + GitHub Pages 리포트 | 워크북 A-4(노션) + O3 |
| 시크릿 관리 | GitHub Actions Secrets, .env 커밋 금지 | A13 API 키 노출 교훈 |
| DB | DuckDB, `(url_hash, collected_date)` 유니크 | 멱등 적재 |

## 핵심 파일 (예정 구조)

```
자동화리포트_project/
├─ dev/active/daily-brief/        # 이 계획 문서 3종
├─ src/
│  ├─ collect.py                  # 2단계: RSS/HTML 수집 → JSONL
│  ├─ load.py                     # 3단계: DuckDB 멱등 적재
│  ├─ filter_rules.py             # 규칙 필터(홍보 제거·중복·분류)
│  ├─ judge_ai.py                 # AI 보조 판정·요약 (애매 항목만)
│  ├─ quality_check.py            # 4단계: V3 체크리스트, 실패 시 exit 1
│  ├─ report.py                   # 5단계: Notion 적재 + HTML 리포트
│  └─ sources.yaml                # 소스 목록(URL/RSS/카테고리)
├─ .claude/
│  ├─ commands/daily-brief.md     # 직접 만든 슬래시 커맨드
│  └─ skills/brief-qa/            # 직접 만든 품질 스킬
├─ .github/workflows/daily.yml    # 6단계: cron 스케줄 + 실패 시 이슈
├─ docs/                          # GitHub Pages 리포트
└─ tests/
```

## 의존성

- Python 3.11+: feedparser, httpx, selectolax(또는 beautifulsoup4), duckdb, anthropic
- 외부: Notion API, Claude API, GitHub Actions

## 사전 준비물 (착수 차단 요소)

- [ ] 소스 URL/RSS 목록 확정
- [ ] Notion 인테그레이션 토큰 + DB
- [ ] Claude API 키
- [ ] GitHub 레포 + Secrets

## 사람/기계 경계 (설계 핵심)

- 기계: 수집·파싱·중복제거·홍보 규칙 필터·카테고리 분류
- AI 보조: 규칙으로 애매한 항목의 읽을 가치 판정 + 요약
- 사람: 최종 무엇을 읽을지, 주간 회고로 규칙 개선

## 다음 액션

계획 승인 후 → 1단계(손으로 한 번) 착수. 사전 준비물부터 확보.

## 참고 링크

- 케이스북: https://seulkikaang.github.io/claude-skills/analyst-cases/
- A13(GitHub Actions 트렌드 리포트): https://www.gpters.org/nocode/post/ai-trend-automation-builder-yf1PUrHfjKt7PhU
- A12(컬리 데일리 브리핑): https://helloworld.kurly.com/blog/claude-code-redesign-my-day/
- A11(슬래시커맨드+크론): https://www.youtube.com/watch?v=l6V0u3ZIgDI
