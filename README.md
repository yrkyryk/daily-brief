# Daily Brief 자동화 파이프라인

매일 아침 뉴스·블로그를 자동 수집·정제해 **AI 요약이 붙은 Daily Brief**로 내보내는 무인 데이터 파이프라인. 데이터 분석가 지원 포트폴리오.

> 트렌드 수집기가 하루 2회(10:30·18:15 KST 전후) 스스로 돌아, 홍보가 제외된 핵심 뉴스와 실무 인사이트 글만 골라 리포트로 주고 텔레그램으로 전달한다.

![pipeline](docs/pipeline-diagram.html) <!-- 데이터 흐름 다이어그램: docs/pipeline-diagram.html -->

---

## 무엇을 증명하나

웹/외부 데이터 파이프라인 구축, 데이터 전처리, 지표 모니터링을 **처음부터 끝까지 무인으로** 운영한 사례.

- **데이터 파이프라인 설계**: 수집 → 적재 → 필터 → 판정 → 검증 → 발행
- **사람/기계/AI 경계 설계**: 결정론적 규칙으로 노이즈를 먼저 걷어내고, 애매한 판단만 AI에 위임 (토큰 비용 통제)
- **결정론적 품질 검증**: 매 실행 V3 체크리스트를 `data/quality_*.json`으로 커밋·보존하고 리포트에 노출, 이상 시 스스로 중단(exit 1) + 이슈 자동 생성
- **스케줄 운영 / 실패 복구**: GitHub Actions cron, 다음 실행 시 빠진 구간 재수집
- **운영 관측성**: cron best-effort로 인한 발송 지연·누락 원인을 로그·품질기록으로 진단하는 절차를 Claude Code 스킬(`diagnose-brief-send`)로 코드화
- **AI 연동**: Claude(OAuth) 보조 요약, 카테고리당 1회 호출로 비용 최소화

## 사람 / 기계 / AI 경계 (설계 핵심)

| 역할 | 담당 | 근거 |
|------|------|------|
| **기계**(Python) | 수집 · 파싱 · 중복제거 · 홍보 규칙 필터 · 카테고리 분류 · 품질검증 · 발행 | 결정론적, 무료, 재현 가능 |
| **AI 보조**(Claude) | 규칙 통과분의 흐름 요약 · 읽을 가치 판정 | 규칙으로 애매한 것만, 카테고리당 1회 |
| **사람**(나) | 무엇을 열어 읽을지 · 주간 회고로 규칙 개선 | 최종 판단은 사람 |

## 파이프라인

```
collect.py   RSS 12소스 수집 + 홍보/중복 규칙 필터 → data/raw_YYYY-MM-DD.jsonl
   │           (전 소스 실패 또는 0건이면 exit 1)
   │           V3 품질 지표 → data/quality_YYYY-MM-DD.json (커밋·보존)
report.py    카테고리별 AI 흐름요약·읽을가치 판정(Claude, OAuth) + 인터랙티브 HTML
   │           결과는 data/ai_cache 에 저장 → 재실행 시 재호출 없음(비용 0)
docs/        daily-brief-*.html + index.html (GitHub Pages)
   │
telegram_notify.py  (선택) 오늘자 브리핑을 텔레그램으로 발송 — 산출물 재활용, 재수집 없음
```

데이터 페이로드 변형: `WB`(웹) → `DB`(원본 JSONL) → `TB`(정제 테이블) → `FL`(리포트)

## 실행

로컬 (원클릭):
```bash
pip install -r requirements.txt
python src/run_daily.py
```
- AI 요약을 켜려면 Claude Code CLI 설치 후 `claude` 로그인(OAuth). 미설치 시 규칙 전용으로 폴백.
- 결과: `docs/index.html` (탭·카테고리·검색 인터랙티브 리포트)

## 무인 운영 (GitHub Actions)

`.github/workflows/daily.yml` 이 하루 2회 실행한다(10:30·18:15 KST 전후). 그날 첫 실행=전체 브리핑, 이후=새 헤드라인만.

발송 시각은 GitHub Actions 의 cron 이 정한다. 다만 이 레포의 cron 은 상시 2~5시간 지연되므로(실행 이력 65건 전부 러너 대기 0초, 트리거 생성 자체가 늦음) **목표 시각이 아니라 실제 도착 시각을 기준으로** cron 값을 골랐다. 측정 근거는 [SCHEDULING.md](SCHEDULING.md) 참조.

분 단위 정시 발송이 필요하면 외부 스케줄러가 `workflow_dispatch` 를 호출하도록 붙일 수 있다(선택). 그때 cron 2개는 `gate` 잡의 6시간 규칙에 걸려 자동으로 안전망이 되고, 중복 발송은 0이 된다.

발송이 이상할 때의 진단 절차는 `diagnose-brief-send` 스킬에 있다.

1. GitHub 레포에 이 프로젝트 push
2. `claude setup-token` 으로 OAuth 토큰 발급 → 레포 **Settings → Secrets → Actions** 에 `CLAUDE_CODE_OAUTH_TOKEN` 등록
3. **Settings → Pages** 에서 소스를 `main` 브랜치 `/docs` 로 지정
4. (선택) 분 단위 정시 발송이 필요하면 [SCHEDULING.md](SCHEDULING.md) 대로 외부 스케줄러 등록
5. 매일 자동 실행 → `docs/index.html` 이 최신 Daily Brief로 갱신 (실패 시 Issue 자동 생성)

## 품질 체크리스트 (V3, 매 실행 기록·노출)

1. 소스별 수집 건수 (0건이면 차단 의심)
2. 홍보 필터 제거 건수/율
3. 중복 제거 건수
4. 빈 응답/전 소스 실패 감지 → **exit 1**
5. 카테고리 분포
6. AI 판정 호출 건수·토큰·추정 비용

> 이 지표는 `data/quality_{날짜}.json`으로 커밋돼 재현·추적 가능하고, 리포트 하단 '품질 검증 기록' 섹션에도 노출된다(기존엔 실행 로그에만 출력돼 수십 일 뒤 휘발).

## 스택

Python 3.11+ · feedparser · Claude(claude-haiku-4-5, OAuth CLI) · GitHub Actions · GitHub Pages · Telegram Bot API(선택, stdlib만)
다이어그램: `diagram-design` 스킬(Data flow) · 운영 진단: `diagnose-brief-send` 스킬(발송 지연·누락 원인 추적)

## 직접 내 것으로 쓰기 (Fork & Setup)

이 레포를 포크하면 **자기 계정으로 똑같이** 돌릴 수 있다. 개인값은 전부 시크릿/환경변수로 분리돼 있어 코드 수정은 거의 없다.

### 1. 기본 (리포트 자동 생성) — 필수
1. 이 레포 **Fork** (또는 Use this template)
2. `Settings → Pages` → Source를 `main` 브랜치 `/docs` 로 지정
3. AI 요약을 켜려면: 로컬에서 `claude setup-token` 발급 → `Settings → Secrets → Actions` 에 `CLAUDE_CODE_OAUTH_TOKEN` 등록
   - 없어도 규칙 전용으로 동작 (AI 요약만 빠짐)
4. `interests.txt`(관심 키워드), `my_sources.txt`(내 소스)를 자기 것으로 수정
5. `Actions` 탭에서 `daily-brief` 수동 실행 → `https://<나>.github.io/<repo>/` 에 리포트 생성

### 2. 원클릭 Notion 저장 / 페이지에서 소스 관리 — 선택
백엔드(Vercel 서버리스 함수)가 필요하다. `api/` 폴더를 Vercel에 배포:
1. Vercel에 이 레포 연결(또는 `api/` 배포) → 프로젝트 생성
2. **환경변수**(Production):
   - `APP_KEY` : 아무 비밀 문자열(페이지 연결 설정에 넣을 값)
   - Notion 저장용: `NOTION_TOKEN`, `NOTION_DB_ID`
   - 소스 관리용: `GITHUB_TOKEN`(fork 레포 contents R/W + actions), `GH_REPO`(예: `내아이디/daily-brief`)
   - (선택) `ALLOW_ORIGIN` : 자기 Pages 도메인(`https://<나>.github.io`). 기본은 전체 허용이고 `APP_KEY`로 보호됨.
3. Vercel **Deployment Protection 끄기** (공개 페이지가 함수를 호출해야 함)
4. 리포트 상단 **[연결 설정]** 에 함수 URL + `APP_KEY` 입력(브라우저에만 저장) → 카드 ☁️ 저장, 📌 소스 추가 사용

> 보안: Notion/GitHub 토큰은 **Vercel 환경변수와 내 브라우저에만** 있고 공개 레포·페이지엔 없다. 함수는 `APP_KEY` 없으면 401로 막힌다.

### 3. 텔레그램으로 매일 받아보기 — 선택
매일 만든 브리핑을 텔레그램으로 자동 발송한다(수집·AI 재호출 없이 산출물만 재활용).
1. `@BotFather` 로 봇 생성 → 토큰 발급
2. 봇과 대화 후 `https://api.telegram.org/bot<토큰>/getUpdates` 에서 `chat.id` 확인
3. `Settings → Secrets → Actions` 에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 등록 (선택: `Settings → Variables` 에 `SITE_URL`)
4. 미리보기: `python src/telegram_notify.py --dry-run` (발송 없이 메시지 확인)

> 시크릿이 없으면 발송만 조용히 스킵되고 리포트 생성은 그대로 동작한다.

## 한계 (명시)

- 인스타그램 제외 (공식 API 없음·약관 리스크)
- 홈 주소만 넣어도 되는 블로그: 네이버 블로그·티스토리·워드프레스·브런치·벨로그·미디엄·네이버 D2. 피드를 아예 제공하지 않는 사이트(노션 기반 등)는 0건으로 빠지며, 어느 단계에서 갈렸는지가 `data/quality_*.json` 의 `내소스_해석경로` 에 남는다.
- 키워드 트렌드는 형태소 분석기 없이 단순 토큰+불용어(투명·경량). 정교화는 후속 과제.

