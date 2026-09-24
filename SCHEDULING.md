# 발송 시각 운영 — 외부 스케줄러

Daily Brief 는 하루 3회(**08:30 / 13:00 / 18:00 KST**) 텔레그램으로 나간다.
이 시각을 결정하는 것은 GitHub 의 cron 이 아니라 **외부 스케줄러**다.

## 왜 GitHub cron 을 안 쓰나

실행 이력 65건을 측정한 결과다.

| 트리거 | 표본 | 지연 |
| --- | --- | --- |
| `schedule` — 23:30 UTC (08:30 KST 목표) | 12건 | 중앙값 **+2h00m** |
| `schedule` — 04:07 UTC (13:07 KST 목표) | 6건 | 중앙값 **+5h07m** |
| `schedule` — 09:07 UTC (18:07 KST 목표) | 6건 | 중앙값 **+5h02m** |
| `workflow_dispatch` | 24건 | **전부 0초** |

- 65건 전부 `createdAt == startedAt`, 즉 **러너 대기는 0초**다. 러너가 부족한 게 아니라
  GitHub 이 cron 이벤트 자체를 늦게 만든다. 레포 안에서 고칠 방법이 없다.
- cron 이 1개뿐이던 초기(09-11, 09-12)에도 아침 슬롯은 +1h45m 늦었다. 하루 3회로
  바꾼 것이 원인이 아니라, 04:07·09:07 UTC 가 더 혼잡한 구간이라 체감이 나빠진 것이다.
- 반면 `workflow_dispatch` 는 예외 없이 즉시 실행된다. 그래서 외부에서 호출한다.

## 설정: cron-job.org

무료이고 POST + 커스텀 헤더 + 요청 바디를 지원한다. 계정 하나면 된다.

### 1. GitHub 토큰 발급

GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**

| 항목 | 값 |
| --- | --- |
| Repository access | Only select repositories → `yrkyryk/daily-brief` |
| Permissions → Repository permissions → **Actions** | **Read and write** |
| Expiration | 원하는 기간 (만료되면 발송이 멈추니 캘린더에 갱신 알림을 걸어둘 것) |

다른 권한은 전부 필요 없다. 발급된 `github_pat_...` 문자열을 복사해 둔다.

> 토큰은 이 레포의 Actions 를 실행시킬 수 있는 열쇠다. cron-job.org 외에 어디에도 붙여넣지 말 것.

### 2. cron-job.org 에 작업 3개 등록

[cron-job.org](https://cron-job.org/) 가입 후 **Create cronjob** 으로 아래를 **3번** 만든다.
세 작업의 차이는 실행 시각뿐이고 나머지는 전부 동일하다.

**공통 설정**

| 항목 | 값 |
| --- | --- |
| URL | `https://api.github.com/repos/yrkyryk/daily-brief/actions/workflows/daily.yml/dispatches` |
| Request method | `POST` |
| Timezone | `Asia/Seoul` |

**Headers** (Advanced → Headers)

```
Accept: application/vnd.github+json
Authorization: Bearer <1번에서 발급한 토큰>
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

**Request body**

```json
{"ref":"main"}
```

**실행 시각** — 작업 3개를 각각 아래로 설정

| 작업 | 시각 (Asia/Seoul) | 발송 내용 |
| --- | --- | --- |
| 1 | 매일 08:30 | 전체 브리핑 (AI 요약) |
| 2 | 매일 13:00 | 새로 뜬 헤드라인만 |
| 3 | 매일 18:00 | 새로 뜬 헤드라인만 |

아침/점심/저녁 구분은 cron-job.org 가 정하지 않는다. `src/slot.py` 가 실행 시각과
`data/brief_{날짜}.json` 마커를 보고 판정하므로, 세 작업의 설정은 시각 말고 완전히 같아도 된다.

### 3. 확인

성공하면 GitHub 이 **204 No Content** 를 돌려준다. cron-job.org 실행 이력에서 204 를 확인하고,
`Actions` 탭에 `workflow_dispatch` 실행이 즉시 뜨는지 본다.

```bash
gh run list --workflow=daily.yml --limit 5 --json event,createdAt,conclusion
```

`event` 가 `schedule` 이 아니라 `workflow_dispatch` 로 찍히면 정상이다.

## 안전망 cron

`.github/workflows/daily.yml` 에 cron 2개가 남아 있다. **외부 스케줄러가 멈춘 날을 위한 백업**이다.

| cron (UTC) | 실제 도착 (측정값) | 안전망 발송 |
| --- | --- | --- |
| `30 23 * * *` | 10:30 KST 전후 | 전체 브리핑 (AI 요약) |
| `7 4 * * *` | 18:15 KST 전후 | 새로 뜬 헤드라인 |

목표 시각이 아니라 **실제로 도착하는 시각**을 기준으로 고른 값이다. 이 두 슬롯은 지연되더라도
10:20~10:41 / 17:44~18:23 범위에 들어온다.

`gate` 잡이 중복을 막는다. 판정 기준은 `src/slot.py` 의 `safety_net_suppressed()` 한 곳이다.

- 트리거가 `workflow_dispatch` → **항상 진행** (외부 스케줄러가 정한 시각이 곧 발송 시각)
- 트리거가 `schedule` + 마지막 발송이 **6시간 이내** → **조용히 중단** (외부 스케줄러 정상)
- 트리거가 `schedule` + 마지막 발송이 **6시간 초과 또는 없음** → **진행** (백업 동작)

"마지막 발송 시각"은 `data/seen_{날짜}.json` 의 `updated` 다. `telegram_notify.py` 가 메시지를
**전량 발송 성공했을 때만** 기록하므로 실제 발송 이력과 일치한다.

결과:

| 상황 | 하루 발송 횟수 |
| --- | --- |
| 외부 스케줄러 정상 | **3회** (08:30 / 13:00 / 18:00) — 안전망은 전부 스킵 |
| 외부 스케줄러 사망 | **2회** (10:30 전체 브리핑 / 18:15 헤드라인) |
| 외부가 아침만 성공 후 사망 | **2회** (08:30 브리핑 / 18:15 헤드라인) |

## 문제가 생기면

- 발송이 이상할 때의 진단 절차는 `diagnose-brief-send` 스킬에 있다.
- 토큰 만료가 가장 흔한 원인이다. cron-job.org 실행 이력에 **401** 이 찍히면 1번을 다시 한다.
- 발송이 아예 멈췄는데 10:30 쯤 브리핑 하나만 온다면 = 외부 스케줄러가 죽고 안전망만 도는 상태다.
