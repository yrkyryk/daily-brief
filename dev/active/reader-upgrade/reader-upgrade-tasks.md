# reader-upgrade · Tasks

## Phase 1 — 커스텀 소스
- [ ] my_sources.txt (신규, 예시+주석)
- [ ] src/fetch_article.py: fetch_text(url), discover_and_fetch(url)
- [ ] src/collect.py: my_sources 수집 병합("내 소스" cat), 실패 폴백
- [ ] 로컬 검증: collect 로그에 내 소스 건수

## Phase 2 — 관심 키워드 섹션
- [ ] interests.txt (신규, 예시+주석)
- [ ] src/interests.py: load(), match(text, interests)
- [ ] src/report.py: 상단 관심 키워드 섹션 + "내 소스" 탭
- [ ] 로컬 검증: docs/index.html 섹션 렌더

## Phase 3 — Notion 수동 선택 발행
- [ ] src/report.py: 카드 체크박스 + 선택 JSON 내보내기 UI
- [ ] src/notion_publish.py: --from <file.json> 모드
- [ ] daily.yml: cron에서 Notion 단계 제거
- [ ] (선택) notion-publish.yml 수동 워크플로우
- [ ] 검증: selected.json → notion_publish --from, cron에 Notion 없음

## 마무리
- [ ] 커밋·푸시, Pages 확인
- [ ] README/포트폴리오 문구 반영 여부 판단
