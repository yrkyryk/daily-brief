# -*- coding: utf-8 -*-
"""
run_daily.py — 로컬 원클릭 오케스트레이터

collect.py(수집+필터) → report.py(AI 요약+HTML) 를 순서대로 실행한다.
수집 게이트가 FAIL(exit 1)이면 리포트 생성을 건너뛰고 중단한다.

사용:
  python src/run_daily.py
"""
import subprocess, sys, pathlib, os, datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).strftime("%Y-%m-%d")

def step(name: str, script: str) -> None:
    print(f"\n{'='*48}\n▶ {name}\n{'='*48}")
    rc = subprocess.run([sys.executable, str(SRC / script)], cwd=str(ROOT)).returncode
    if rc != 0:
        print(f"\n[중단] {script} 가 exit {rc} 로 실패 → 파이프라인 정지")
        sys.exit(rc)


def soft_step(name: str, script: str) -> None:
    """부가 기능(전달 등) — 실패해도 파이프라인을 멈추지 않는다."""
    print(f"\n{'='*48}\n▶ {name}\n{'='*48}")
    rc = subprocess.run([sys.executable, str(SRC / script)], cwd=str(ROOT)).returncode
    if rc != 0:
        print(f"[경고] {script} 가 exit {rc} — 계속 진행(부가 기능)")

if __name__ == "__main__":
    # 로컬에서 node(세션종료 훅) 경로 보강 — 있으면 추가, 없으면 무시
    node_dir = r"C:\Program Files\nodejs"
    if os.path.isdir(node_dir) and node_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = os.environ["PATH"] + os.pathsep + node_dir
    # 발송 모드는 slot.py 가 단일 판정(아침 이후 첫 요약=brief, 새벽/발송후=headlines).
    sys.path.insert(0, str(SRC))
    import slot
    is_brief = slot.decide_mode(TODAY) == "brief"
    step("1) 수집 + 규칙 필터", "collect.py")
    if is_brief:
        step("2) AI 요약 + 리포트 생성 (아침 전체 브리핑)", "report.py")
    else:
        print("\n[안내] 오늘 요약은 이미 보냈거나 새벽 구간 → AI 생략, 새 헤드라인만 발송(비용 0)")
    soft_step("3) 텔레그램 발송 (토큰 있을 때만)", "telegram_notify.py")
    print("\n✅ 완료: docs/ 에 오늘자 리포트가 생성되었습니다.")
    print("   Notion 카드는 리포트에서 원하는 카드를 골라 선택 발행하세요:")
    print("   1) docs/index.html 에서 카드 [선택] 체크 → '선택한 카드 내보내기' → selected.json 저장")
    print("   2) python src/notion_publish.py --from selected.json  (NOTION_TOKEN/NOTION_DB_ID 필요)")
