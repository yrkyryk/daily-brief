# Daily Brief 태스크 체크리스트

**Last Updated: 2026-09-10**

순서를 바꾸지 않는다. 각 단계 완료 기준을 만족해야 다음으로 넘어간다.

## 0단계: 사전 준비

- [ ] 수집 소스 확정 (뉴스 경제/사회/연예 + 관심 블로그 URL·RSS)
- [ ] 각 소스 RSS 존재 여부 확인, 없으면 파싱 대상 표시
- [ ] Notion 인테그레이션 토큰 발급 + Daily Brief DB 생성·공유
- [ ] Claude API 키 확보
- [ ] GitHub 레포 생성 + Actions Secrets 등록 (NOTION_TOKEN, ANTHROPIC_API_KEY)
- [ ] Python 프로젝트 초기화 (venv, requirements)

## 1단계: 손으로 한 번 (완료 기준: Brief 1건 수작업 완성)

- [ ] 소스에서 손으로 오늘치 기사 수집
- [ ] 홍보성 판별 기준을 실제로 적용해보며 필터 규칙 초안 작성
- [ ] 카테고리 분류 기준 확정
- [ ] 손으로 만든 Brief 1건 저장 (증거)

## 2단계: 수집 스크립트 (완료 기준: 명령 한 번 → 원본 JSONL)

- [ ] `sources.yaml` 작성
- [ ] `collect.py`: RSS 수집 (feedparser)
- [ ] RSS 없는 소스 정적 HTML 파싱 폴백
- [ ] 원본을 JSONL로 저장 + 수집 로그
- [ ] 테스트: 소스별 최소 1건 수집 확인

## 3단계: 적재 / 멱등성 (완료 기준: 2회 넣어도 안 깨짐)

- [ ] `load.py`: DuckDB 스키마 정의
- [ ] `(url_hash, collected_date)` 유니크 제약으로 중복 방지
- [ ] 같은 파일 2회 적재 → 행 수 동일 확인 (증거 로그)

## 4단계: 자동 점검 (완료 기준: 깨지면 스스로 멈춤)

- [ ] `filter_rules.py`: 홍보 제거·중복·카테고리 규칙
- [ ] `judge_ai.py`: 애매 항목만 Claude API 판정·요약
- [ ] `quality_check.py`: V3 체크리스트 6개 항목 출력
- [ ] 실패 임계(빈 응답·건수 급감) 시 exit 1
- [ ] 일부러 빈 데이터 넣어 실패 감지 확인 (증거)

## 5단계: 산출물 생성 (완료 기준: Notion + HTML 리포트)

- [ ] `report.py`: Notion API로 Daily Brief DB 적재
- [ ] 인터랙티브 HTML 리포트 생성 (탭·카테고리·검색)
- [ ] GitHub Pages 배포 설정
- [ ] Notion 페이지 + 리포트 URL 확인 (증거)

## 6단계: 스케줄 + 실패 알림 (완료 기준: 무인 운영 + 실패 통지)

- [ ] `.github/workflows/daily.yml`: cron `30 23 * * *` (08:30 KST)
- [ ] Secrets로 키 주입
- [ ] 실패 시 GitHub Issue 자동 생성
- [ ] 다음 실행 시 빠진 구간만 재수집 로직
- [ ] 2주 무인 운영 시작, 로그 축적

## 7단계: 포트폴리오 마감

- [ ] `/daily-brief` 커스텀 커맨드 + `brief-qa` 스킬 문서화
- [ ] README: 문제 → 설계 → 사람/기계 경계 → 검증 → 운영 기록
- [ ] before/after 시간, 실패→복구 사례 정리
- [x] `dev/active/` → `dev/completed/` 이동

## 직접 만들 스킬 (하이라이트)

- [ ] `.claude/skills/brief-qa/`: 입력 형식·실행 명령·결과 예시 3종 완비
