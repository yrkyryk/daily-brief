# 블로그 글 수집 개선 체크리스트

**Last Updated:** 2026-09-24
**상세 단계:** `dev/active/blog-crawl/blog-crawl-plan.md`

Task 1~3 은 동작을 바꾸지 않는다. Task 4 에서 체인이 실제로 교체된다.

## Task 1: 플랫폼 규칙표 `resolve_feed()`

- [ ] `tests/test_fetch_blog.py` 신규 + `test_resolve_feed()` 작성
- [ ] 실패 확인 (`AttributeError: resolve_feed`)
- [ ] `PLATFORM_FEEDS` + `resolve_feed()` 구현
- [ ] 통과 확인 (`OK: 9 checks passed`)
- [ ] 커밋

## Task 2: 단일글 폴백 가드 `accept_as_article()`

- [ ] `test_accept_as_article()` 작성 (실측 27·44·62·199·200·2130자 경계)
- [ ] 실패 확인
- [ ] `MIN_ARTICLE_CHARS` + `accept_as_article()` 구현
- [ ] 통과 확인 (`OK: 21 checks passed`)
- [ ] 커밋

## Task 3: 네트워크 시간 상한

- [ ] `test_socket_timeout_restores()` 작성 (정상 복원 + 예외 시 복원)
- [ ] 실패 확인
- [ ] import 에 `contextlib`, `socket` 추가
- [ ] `FETCH_TIMEOUT` / `FEED_TIMEOUT` / `SOURCE_BUDGET` 상수 추가
- [ ] `_fetch_html` 재시도 3→2, `timeout=15`→`FETCH_TIMEOUT`
- [ ] `_socket_timeout()` + `_parse_feed()` 구현
- [ ] 통과 확인 (`OK: 25 checks passed`)
- [ ] 커밋

## Task 4: 해석 체인 재구성 `discover()`

- [ ] `test_discover_contract()` 작성 (빈입력 + 라벨 집합 계약)
- [ ] 실패 확인
- [ ] `RESOLVE_LABELS` + `discover()` 구현, `discover_and_fetch()` 는 래퍼로
- [ ] 네이버 하드코딩 특례가 사라졌는지 확인
- [ ] 통과 확인 (`OK: 33 checks passed`)
- [ ] 기존 테스트 회귀 확인 (`test_promo.py`, `test_slot.py`)
- [ ] 커밋

## Task 5: `collect.py` 해석경로 집계

- [ ] `custom_paths` 변수 추가
- [ ] `discover_and_fetch()` → `discover()` 호출 교체
- [ ] 로그에 라벨 출력 + 에러 경로 집계
- [ ] `checklist` 에 `내소스_해석경로` 조건부 추가
- [ ] `python src/collect.py` 실행해 라벨 출력 확인
- [ ] `quality_*.json` 에 실제로 기록됐는지 확인
- [ ] 커밋

## Task 6: 완료 기준 증명 + 문서

- [ ] `NETWORK_CASES` + `test_network()` 작성
- [ ] `run()` 에 `--network` 플래그 분기 추가
- [ ] 네트워크 없이 통과 확인 (`OK: 33 checks passed`)
- [ ] `python tests/test_fetch_blog.py --network` 로 완료 기준 증명
- [ ] `my_sources.txt` 주석 갱신
- [ ] `README.md` '한계' 문단 갱신
- [ ] 전체 테스트 + `collect.py` 회귀 확인
- [ ] 커밋

## 완료 기준 (스펙 7절)

- [ ] 7개 대상 중 6개 목록 수집, `www.oopy.io` 는 0건 + 사유 라벨
- [ ] 쓰레기 단일글 3건이 브리핑에 안 들어옴
- [ ] 소스당 최악 17초 → 10초 이내
- [ ] `python tests/test_fetch_blog.py` 가 네트워크 없이 통과
- [ ] `data/quality_*.json` 에 `내소스_해석경로` 기록됨

## 마무리

- [ ] `code-reviewer` 에이전트 실행
- [ ] `dev/active/blog-crawl/` → 완료 시 정리
