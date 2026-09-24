# -*- coding: utf-8 -*-
"""collect.is_promo 홍보 판정 테스트 (python tests/test_promo.py 로 실행).

핵심 규칙:
  - 기존 홍보 키워드(협찬/보도자료 등)는 단독으로 제외한다.
  - 상세 홍보(가격·구매처·행사기간)는 '2개 축 이상 동시 출현' 시에만 제외한다.
  - 각 축은 상거래 문맥이 붙을 때만 켜진다. 금액·기업명·마감일 자체는 신호가 아니다.
    (금액만으로 축을 켜면 2축 조건이 사실상 1축으로 무너져 경제·정책 기사가 대량 오탐된다.)

실패를 모아서 마지막에 한 번에 출력한다(규칙 튜닝 시 반복 실행을 줄이기 위해).
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
import collect  # noqa: E402

FAILURES: list[str] = []
CHECKED = 0


def check(cond: bool, msg: str) -> None:
    global CHECKED
    CHECKED += 1
    if not cond:
        FAILURES.append(msg)


def axis_hits(text: str) -> set[str]:
    return {name for name, pat in collect.PROMO_AXES if pat.search(text)}


# --- 기존 키워드 판정은 그대로 동작해야 한다 ---
KEYWORD_CASES = [
    ("[보도자료] 신제품 라인업 발표", "", "[보도자료]"),  # 목록 순서상 대괄호형이 먼저 잡힌다
    ("인플루언서 협찬 논란", "", "협찬"),
    ("여름 특가 기획전 개막", "", "특가"),
]

# --- 축이 1개 이하로 걸리는 정상 기사는 통과해야 한다 ---
PASS_CASES = [
    # 금액만 있는 경제 기사
    ("원달러 환율 1,400원 돌파", "수출 기업들이 비상 대응에 들어갔다."),
    ("서울 아파트 평균 매매가 12억원", "전월 대비 0.3% 상승했다."),
    ("소비자물가 3% 상승", "정부가 대책을 논의 중이다."),
    # 유통 기업명 + 금액 (실적·규제 기사)
    ("쿠팡, 3분기 영업이익 1000억원 기록", "물류 투자 효과가 나타났다는 분석이다."),
    ("네이버쇼핑 입점 수수료 500원 인하", "입점 소상공인 반발이 이어졌다."),
    # 선착순/사전예약 + 금액 (지자체 지원금·공공 예약)
    ("서울시, 선착순 5000명에 교통비 10만원 지원", "신청은 시청 홈페이지에서 받는다."),
    ("정부, 청년 월세 20만원 지원 선착순 접수", "예산 소진까지 이어질 전망이다."),
    ("코로나 백신 사전예약 시작", "본인부담금은 1인당 3만원이다."),
    ("전기차 보조금 900만원, 구매처별 차이", "지자체 예산에 따라 편차가 크다."),
    ("아파트 청약 선착순 모집", "분양가는 8억원대로 책정됐다."),
    # 마감일만 있는 정책 기사
    ("정부, 10월 31일까지 유류세 인하 연장", "세수 감소 우려도 제기된다."),
    # 실제 수집 데이터에서 나온 오탐(2026-09): 가격 + 모집 마감일로 2축이 걸렸던 정책 기사
    ("부산시, 빈 점포 월 1만원에 임대 참여자 모집",
     "부산시는 빈 점포를 활용하는 프로젝트의 1차 참여자를 18일까지 모집한다고 밝혔다."),
]

# --- 축 2개 이상이면 홍보로 제외해야 한다 ---
PROMO_CASES = [
    ("신상 텀블러 9,900원, 쿠팡에서 선착순 판매", ""),           # 가격+구매처+기간
    ("겨울 패딩 30% 할인", "11월 30일까지 진행됩니다."),          # 가격+기간
    ("공식몰 사전예약 시작", "한정수량 100개로 준비했습니다."),     # 구매처+기간
    ("스마트스토어 오픈 기념 5만원 적립", ""),                     # 가격+구매처
]

# --- 축 단위 검증: 날짜 표기 변형이 실제로 기간축을 켜는가 ---
PERIOD_ON = [
    "11월 30일까지 진행",
    "11월 30일까지 특별 할인 진행",   # 동사 앞에 공백이 끼는 실제 홍보 문구
    "30일까지만 판매",                # 월 생략 + 보조사 '만'
]
PERIOD_OFF = [
    "18일까지 참여자를 모집한다",
    "10월 31일까지 유류세 인하 연장",
    "12월 3일까지 의견을 접수한다",
]

# --- 축 단위 검증: 금액이 판매 문맥일 때만 가격축이 켜지는가 ---
PRICE_ON = ["9,900원에 판매", "정가 19,000원", "3만원 상당 증정", "반값 세일"]
PRICE_OFF = ["영업이익 1000억원 기록", "교통비 10만원 지원", "분양가 8억원대", "예산 3조원 편성"]


def run() -> None:
    for title, summary, kw in KEYWORD_CASES:
        r = collect.is_promo(title, summary)
        check(r == kw, f"키워드 판정 불일치: {title} → {r!r} (기대 {kw!r})")

    for title, summary in PASS_CASES:
        r = collect.is_promo(title, summary)
        check(not r, f"정상 기사 오탐: {title} → {r!r} / 축={axis_hits(title + ' ' + summary)}")

    for title, summary in PROMO_CASES:
        r = collect.is_promo(title, summary)
        check(bool(r), f"상세 홍보 미검출: {title} / 축={axis_hits(title + ' ' + summary)}")

    for t in PERIOD_ON:
        check("기간" in axis_hits(t), f"기간축 미검출: {t}")
    for t in PERIOD_OFF:
        check("기간" not in axis_hits(t), f"기간축 오탐: {t}")
    for t in PRICE_ON:
        check("가격" in axis_hits(t), f"가격축 미검출: {t}")
    for t in PRICE_OFF:
        check("가격" not in axis_hits(t), f"가격축 오탐: {t}")

    # 임계값 경계: 정확히 1축이면 통과, 2축이면 제외
    one_axis = "공식몰에서 판매를 시작했다"
    check(len(axis_hits(one_axis)) >= 1 and not collect.is_promo(one_axis, ""),
          f"1축인데 제외됨: {one_axis} / 축={axis_hits(one_axis)}")
    check(collect.PROMO_AXIS_MIN == 2, "PROMO_AXIS_MIN 이 2가 아님")

    # 빈 입력은 None
    check(collect.is_promo("", "") is None, "빈 입력이 홍보로 판정됨")

    if FAILURES:
        print(f"FAIL: {len(FAILURES)}/{CHECKED} 실패")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK: {CHECKED} checks passed")


if __name__ == "__main__":
    run()
