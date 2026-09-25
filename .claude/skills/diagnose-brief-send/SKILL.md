---
name: diagnose-brief-send
description: Use when a daily-brief send is late, missing, duplicated, empty, or arrived at an unexpected time (e.g. "왜 22:46에 왔지?", "오늘 점심 브리핑이 안 왔어", "전체 브리핑이 와야 하는데 헤드라인만 왔어"). Diagnoses the news-automation pipeline by mapping GitHub Actions UTC crons to KST, checking actual run history, the mode/duplicate gate (src/slot.py), and the Telegram send step. Read-only investigation; proposes fixes but does not change schedules unless asked.
---

# Diagnose brief send

이 레포(자동화 뉴스 브리핑)의 텔레그램/리포트 발송이 이상할 때 원인을 결정론적으로 찾는 절차.
"왜 이 시각에 왔지 / 왜 안 왔지 / 왜 전체가 아니라 헤드라인만 왔지"를 추측 없이 로그로 판정한다.

## 배경: 발송 스케줄과 모드

발송 스케줄은 `.github/workflows/daily.yml` 의 cron 이 소스 오브 트루스다. **cron 은 UTC 기준이고, 표시는 KST(+9h)** 로 해야 한다. 현재 설정(변경됐을 수 있으니 항상 파일을 다시 확인할 것):

| cron (UTC)     | 목표 KST | 실제 도착 KST | 모드                              |
| -------------- | -------- | ------------- | --------------------------------- |
| `30 23 * * *`  | 08:30    | **10:30 전후** | 전체 브리핑(AI 요약)             |
| `7 4 * * *`    | 13:07    | **18:15 전후** | 새 헤드라인만(AI 생략)           |

핵심 사실 네 가지:
- **이 레포의 cron 은 상시 지연된다.** 실행 이력 65건에서 러너 대기는 전부 0초인데도 트리거 생성 자체가 늦다(23:30 UTC 슬롯 중앙값 +2h00m, 04:07/09:07 UTC 슬롯 +5h 전후). 그래서 cron 값은 **목표 시각이 아니라 실제 도착 시각 기준으로** 골라 뒀다. 위 표에서 목표 열과 도착 열이 다른 건 오설정이 아니다. 측정 근거는 `SCHEDULING.md`.
- **예정 시각과 실제 시각이 다른 건 대개 버그가 아니다.** 슬롯이 통째로 드롭되는 것도 best-effort 의 정상 범위다.
- **전체/헤드라인 분기는 `src/slot.py` 가 시각 기준으로 판정한다.** `data/brief_{YYYY-MM-DD}.json` 마커가 있으면(그날 요약 이미 발송) `headlines`, 없어도 지금이 KST 08시 이전이면 `headlines`(새벽 요약 차단), 그 외에 `brief`. daily.yml 의 `gate` 잡이 이 판정을 `mode` 출력으로 넘긴다. seen 파일이 아니라 **brief 마커**가 기준이라는 점에 주의할 것. seen 은 헤드라인 증분 추적용이라 헤드라인 발송 때도 갱신된다.
- **`gate` 잡은 중복 발송도 막는다.** 트리거가 `schedule` 이고 마지막 발송(= `data/seen_{날짜}.json` 의 `updated`)이 6시간 이내면 `proceed=false` 로 조용히 끝난다. 외부 스케줄러(`workflow_dispatch`)를 붙였을 때만 실제로 걸리는 장치이고, cron 2회(10:30/18:15)는 7시간 45분 간격이라 정상 운영에서는 억제되지 않는다.

## 절차

### 1. 사용자가 말한 "받은 시각(KST)"을 UTC 로 환산
KST − 9h = UTC. 예: 22:46 KST → 13:46 UTC. 이 UTC 시각이 어느 워크플로우 실행인지 찾는 앵커다.

### 2. 실제 실행 기록 조회 (추측 금지)
```bash
gh run list --workflow=daily.yml --limit 15 \
  --json databaseId,displayTitle,status,conclusion,createdAt,startedAt,updatedAt,event
```
- `createdAt` 이 1번에서 구한 UTC 시각과 맞는 실행을 찾는다. 그게 그 메시지를 보낸 실행이다.
- `event` 가 `schedule` 인지 `workflow_dispatch`(수동)인지 확인한다.
- 하루치 실행을 훑어 **어느 슬롯이 정시에 돌았고, 어느 슬롯이 지연/누락됐는지** 표로 정리한다.

### 3. 지연/누락 판정
- 실행의 `createdAt` 을 KST 로 바꿔 예정 cron 과 비교 → 지연폭 계산.
- 예정 슬롯인데 실행 기록이 아예 없으면 = 그 슬롯 **스킵**(GitHub 이 드롭). 이것도 정상 범위의 best-effort 동작이다.
- 여러 슬롯이 몰려 늦게 실행됐다면 큐잉 지연이다.

### 4. 모드(전체 vs 헤드라인) 확인
문제의 실행 스텝 결과를 본다:
```bash
gh run view <RUN_ID> --json jobs \
  -q '.jobs[].steps[] | "\(.conclusion)\t\(.name)"'
```
- `Install Claude Code CLI` / `Generate report` 가 `skipped` → 그날 첫 실행이 아니어서 **헤드라인(증분) 모드**로 나간 것. "전체가 안 왔다"의 정상 원인.
- 판정 로그를 보려면:
  ```bash
  gh run view <RUN_ID> --log | grep -E "발송 진행|안전망 cron"
  ```
  `발송 진행 — 모드: brief (트리거: schedule)` 처럼 모드와 트리거가 한 줄로 찍힌다.
  `안전망 cron — 최근 발송이 있어 중단` 이면 그 실행은 아무것도 보내지 않았다(`gate` 가 막음).
- 마커 확인: `ls data/brief_*.json` (해당 KST 날짜 파일이 있으면 그날 전체 브리핑은 이미 나간 것).

### 5. 텔레그램 발송 여부 확인
- 위 스텝 목록에서 `Notify via Telegram` 의 conclusion 확인. `success` 면 발송됨.
- 이 스텝은 `continue-on-error: true` 라 실패해도 워크플로우는 성공으로 뜬다. **워크플로우 success ≠ 텔레그램 발송 성공.** 반드시 이 스텝만 따로 본다:
  ```bash
  gh run view <RUN_ID> --log | grep -iA5 "Notify via Telegram"
  ```
- 발송 로직/스킵 조건은 `src/telegram_notify.py` 참조 (시크릿 없으면 스스로 스킵, seen 으로 증분 판단).
- 발송이 전량 성공해야 seen 의 `updated` 가 갱신된다. 즉 seen 이 안 움직였으면 발송도 안 된 것이다.

## 흔한 원인 → 해석

| 증상 | 원인 | 해석/대응 |
| --- | --- | --- |
| 예정보다 몇 시간 늦게 옴 | GitHub Actions cron 지연 | 정상. 잦으면 cron 시각을 혼잡 시간대(정시/30분)에서 더 떼거나 외부 스케줄러로 `workflow_dispatch` 호출 |
| 특정 슬롯이 아예 안 옴 | GitHub 이 스케줄 드롭 | best-effort 특성. 치명적이면 외부 스케줄러 |
| 전체 브리핑 대신 헤드라인만 | `data/brief_{날짜}.json` 마커가 이미 있음 | 정상. 그날 먼저 돈 실행에서 전체가 나감 |
| 새벽에 실행됐는데 헤드라인만 | KST 08시 이전이라 `slot.py` 가 요약을 막음 | 정상. 저녁 슬롯이 자정을 넘겨 밀린 경우 |
| 실행은 됐는데 아무것도 안 보냄 | `gate` 가 `proceed=false` 로 중단 | 정상. 6시간 이내에 이미 발송이 있었다 |
| 워크플로우는 success인데 메시지 없음 | 텔레그램 스텝 `continue-on-error` | 4·5번으로 텔레그램 스텝 로그 직접 확인. 시크릿 만료/누락 의심 |
| 아무것도 안 옴 + 실패 | 수집 게이트 exit 1 (전 소스 실패/0건) 또는 OAuth 토큰 만료 | `automation-failure` 라벨 Issue 확인. 토큰이면 `claude setup-token` 재발급 후 시크릿 갱신 |

## 산출물

다음을 명확히 보고한다:
1. 그 메시지를 보낸 실제 실행 (RUN_ID, event, KST 실행 시각)
2. 예정 슬롯 대비 지연/누락 여부와 폭
3. 전체/헤드라인 모드와 그 이유(brief 마커 유무 / 실행 시각)
4. 텔레그램 스텝 성공 여부
5. 버그인지 정상 동작인지 결론 + (버그면) 근본 원인과 수정안

추측으로 답하지 말 것. 항상 `gh run` 로그로 확인한 뒤 결론 낸다.
