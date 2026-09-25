# 발송 시각 운영

Daily Brief 는 GitHub Actions 의 `schedule`(cron) 로 하루 2회 텔레그램에 나간다.

| 실제 도착 (KST) | cron (UTC) | 발송 내용 |
| --- | --- | --- |
| **10:30 전후** (관측 10:20~10:41) | `30 23 * * *` | 전체 브리핑 (AI 요약) |
| **18:15 전후** (관측 17:44~18:23) | `7 4 * * *` | 새로 뜬 헤드라인 |

cron 값과 도착 시각이 두세 시간 어긋나 보이는 건 오타가 아니다. 아래 "왜 시각이 밀리나" 참조.

## 왜 시각이 밀리나

실행 이력 65건을 측정한 결과다.

| 트리거 | 표본 | 지연 |
| --- | --- | --- |
| `schedule` (23:30 UTC) | 12건 | 중앙값 **+2h00m** |
| `schedule` (04:07 UTC) | 6건 | 중앙값 **+5h07m** |
| `schedule` (09:07 UTC) | 6건 | 중앙값 **+5h02m** |
| `workflow_dispatch` | 24건 | **전부 0초** |

- 65건 전부 `createdAt == startedAt`, 즉 **러너 대기는 0초**다. 러너가 부족한 게 아니라
  GitHub 이 cron 이벤트 자체를 늦게 만든다. 레포 안에서 고칠 방법이 없다.
- cron 이 1개뿐이던 초기(09-11, 09-12)에도 아침 슬롯은 +1h45m 늦었다. 하루 여러 회로
  늘린 것이 원인이 아니다.

그래서 cron 은 **목표 시각이 아니라 실제 도착 시각을 기준으로** 골랐다.
아침 브리핑을 10:30 에 받는 설정이 `30 23 * * *` 인 이유다. 이 값을 08:30 목표로
되돌려봐야 도착 시각은 그대로 10:30 이다.

한때 18:07 KST 목표의 세 번째 cron(`7 9 * * *`)이 있었으나 실제로는 23시 무렵에
도착해 야간 알림이 됐다. 그래서 제거했고, 지금 하루 2회인 이유다.

## 모드 판정과 중복 방지

`gate` 잡이 `src/slot.py` 한 곳에 위임해 판정한다.

- **모드**: 아침(KST 08시 이후) + 그날 전체 요약 미발송 → `brief`(AI 요약).
  그 외 → `headlines`(AI 생략, 비용 0).
- **중복 방지**: 트리거가 `schedule` 이고 마지막 발송이 6시간 이내면 조용히 중단한다
  (`SEND_GAP_HOURS = 6`). 10:30 과 18:15 은 7시간 45분 간격이라 **정상 운영에서는
  억제되지 않는다.** 이 장치는 아래 "선택" 을 붙였을 때 중복을 0으로 만들기 위한 것이다.
- 트리거가 `workflow_dispatch` 면 항상 진행한다.

"마지막 발송 시각"은 `data/seen_{날짜}.json` 의 `updated` 다. `telegram_notify.py` 가
메시지를 **전량 발송 성공했을 때만** 기록하므로 실제 발송 이력과 일치한다.

## 선택: 분 단위 정시 발송이 필요하면

지금 운영에는 필요 없다. 08:30 / 13:00 / 18:00 처럼 **정확한 시각**을 원할 때만 붙인다.
`workflow_dispatch` 는 측정한 24건 전부 대기 0초였으므로 외부에서 호출하면 즉시 실행된다.

붙이고 나면 cron 2개는 위 6시간 규칙에 걸려 **자동으로 안전망이 된다**. 외부 스케줄러가
죽은 날에만 동작하므로 중복 발송은 0이다.

### 1. GitHub 토큰 발급

GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**

| 항목 | 값 |
| --- | --- |
| Repository access | Only select repositories → `yrkyryk/daily-brief` |
| Permissions → Repository permissions → **Actions** | **Read and write** |
| Expiration | 원하는 기간 (만료되면 발송이 멈추니 캘린더에 갱신 알림을 걸어둘 것) |

다른 권한은 전부 필요 없다. 발급된 `github_pat_...` 문자열을 복사해 둔다.

> 토큰은 이 레포의 Actions 를 실행시킬 수 있는 열쇠다. 스케줄러 외에 어디에도 붙여넣지 말 것.

### 2. cron-job.org 에 작업 등록

무료이고 POST + 커스텀 헤더 + 요청 바디를 지원한다. 가입 후 **Create cronjob** 으로
원하는 시각 수만큼 만든다. 작업 간 차이는 실행 시각뿐이고 나머지는 전부 동일하다.

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

아침/점심/저녁 구분은 스케줄러가 정하지 않는다. `src/slot.py` 가 실행 시각과
`data/brief_{날짜}.json` 마커를 보고 판정하므로, 작업들의 설정은 시각 말고 완전히 같아도 된다.

### 3. 확인

성공하면 GitHub 이 **204 No Content** 를 돌려준다. 실행 이력에서 204 를 확인하고,
`Actions` 탭에 `workflow_dispatch` 실행이 즉시 뜨는지 본다.

```bash
gh run list --workflow=daily.yml --limit 5 --json event,createdAt,conclusion
```

`event` 가 `workflow_dispatch` 로 찍히면 정상이다.

## 문제가 생기면

- 발송이 이상할 때(늦게 옴 / 안 옴 / 전체 대신 헤드라인만)의 진단 절차는
  `diagnose-brief-send` 스킬에 있다. 추측하지 말고 `gh run` 로그로 판정한다.
- 발송이 아예 멈췄다면 `automation-failure` 라벨 Issue 를 먼저 본다.
  수집 게이트 exit 1(전 소스 실패) 이거나 `CLAUDE_CODE_OAUTH_TOKEN` 만료가 흔한 원인이다.
- 외부 스케줄러를 붙인 경우, 호출 이력에 **401** 이 찍히면 GitHub 토큰 만료다.
