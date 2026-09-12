# -*- coding: utf-8 -*-
"""
weekly.py — 최근 7일 통계(data/stats/*.json)를 집계해 주간 트렌드 리포트 생성.

출력: docs/weekly.html
- 카테고리별 주간 볼륨, 일자별 추이, 급상승 키워드(SVG 막대), 주간 흐름 요약(OAuth, 선택).
수집은 하지 않는다. report.py 가 매일 남긴 통계 스냅샷만 읽는다.
"""
import json, html, datetime, sys, pathlib
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import judge_ai

ROOT = pathlib.Path(__file__).resolve().parent.parent
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
CAT_ORDER = ["경제", "사회", "연예", "실무", "내소스"]
CAT_EMOJI = {"경제": "💹", "사회": "🏛️", "연예": "🎬", "실무": "🛠️", "내소스": "📌"}


def esc(s):
    return html.escape(str(s or ""))


CSS = """
:root{--bg:#0f1115;--card:#181b22;--line:#262b36;--tx:#e7eaf0;--mut:#8b93a5;--acc:#5b8cff;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font-family:'Pretendard','Malgun Gothic',system-ui,sans-serif;line-height:1.55}
.wrap{max-width:1000px;margin:0 auto;padding:28px 18px 60px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.5px}
.sub{color:var(--mut);font-size:14px;margin-bottom:6px}
a.back{color:var(--acc);text-decoration:none;font-size:13px}
.meta{display:flex;gap:18px;flex-wrap:wrap;margin:16px 0 22px;font-size:13px;color:var(--mut)}
.meta b{color:var(--tx)}
h2{font-size:16px;margin:26px 0 12px}
.synth{background:linear-gradient(180deg,rgba(91,140,255,.08),transparent);border:1px solid var(--line);border-left:3px solid var(--acc);border-radius:10px;padding:14px 16px;white-space:pre-line;font-size:14px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}
th{color:var(--mut);font-weight:600}
.bars{display:grid;gap:7px}
.barrow{display:grid;grid-template-columns:120px 1fr 40px;align-items:center;gap:10px;font-size:13px}
.bar{height:14px;background:var(--acc);border-radius:4px;min-width:2px}
.barrow .n{color:var(--mut);text-align:right}
.empty{color:var(--mut);font-size:14px}
footer{margin-top:34px;font-size:12px;color:var(--mut);text-align:center}
"""


def render(days):
    total_all = sum(d.get("total", 0) for d in days)
    picks_all = sum(d.get("pick_count", 0) for d in days)
    kw = defaultdict(int)
    for d in days:
        for k, v in (d.get("keywords") or {}).items():
            kw[k] += v
    top_kw = sorted(kw.items(), key=lambda x: -x[1])[:15]
    cat_tot = {c: sum(d.get("by_cat", {}).get(c, 0) for d in days) for c in CAT_ORDER}

    # 급상승 키워드 막대
    maxv = top_kw[0][1] if top_kw else 1
    kw_rows = "".join(
        f'<div class="barrow"><span>{esc(k)}</span>'
        f'<span class="bar" style="width:{max(2, round(v / maxv * 100))}%"></span>'
        f'<span class="n">{v}</span></div>'
        for k, v in top_kw) or '<p class="empty">아직 키워드 데이터가 부족합니다.</p>'

    # 카테고리 주간 합계 막대
    cmax = max(cat_tot.values()) if any(cat_tot.values()) else 1
    cat_rows = "".join(
        f'<div class="barrow"><span>{CAT_EMOJI.get(c, "")} {c}</span>'
        f'<span class="bar" style="width:{max(2, round(cat_tot[c] / cmax * 100))}%"></span>'
        f'<span class="n">{cat_tot[c]}</span></div>'
        for c in CAT_ORDER)

    # 일자별 추이 표
    head = "".join(f"<th>{CAT_EMOJI.get(c,'')}{c}</th>" for c in CAT_ORDER)
    trend = "".join(
        "<tr><td>" + esc(d["date"]) + "</td>"
        + "".join(f"<td>{d.get('by_cat',{}).get(c,0)}</td>" for c in CAT_ORDER)
        + f"<td><b>{d.get('total',0)}</b></td>"
        + f"<td>{d.get('pick_count',0)}</td></tr>"
        for d in days)

    # 주간 흐름 요약 (OAuth, 선택)
    synth = ""
    claude = judge_ai.find_claude()
    budget = {"in": 0, "out": 0, "calls": 0, "cost": 0.0}
    if claude:
        blobs = []
        for d in days:
            cache = ROOT / "data" / f"ai_cache_{d['date']}.json"
            if cache.exists():
                try:
                    c = json.loads(cache.read_text(encoding="utf-8"))
                    for cat, res in c.items():
                        s = res.get("summary") if isinstance(res, dict) else ""
                        if s:
                            blobs.append(f"[{d['date']} {cat}] {s}")
                except Exception:
                    pass
        if blobs:
            try:
                synth = judge_ai.weekly_synthesis(claude, "\n".join(blobs), budget)
            except Exception as e:
                print("주간 요약 실패:", e)
    synth_html = (f'<h2>🧠 이번 주 흐름 <span style="color:var(--acc)">AI</span></h2>'
                  f'<div class="synth">{esc(synth)}</div>') if synth else ""

    span = f"{days[0]['date']} ~ {days[-1]['date']}" if days else "데이터 없음"
    return f"""<!doctype html><html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly Trend — {span}</title>
<style>{CSS}</style></head><body><div class="wrap">
<a class="back" href="./index.html">← 오늘의 Daily Brief</a>
<h1>📈 주간 트렌드</h1>
<div class="sub">최근 {len(days)}일({esc(span)}) 누적 데이터 분석 · 생성 {NOW.strftime('%Y-%m-%d %H:%M')} KST</div>
<div class="meta"><span>🗂️ 총 수집 <b>{total_all}건</b></span><span>⭐ 총 읽을가치 <b>{picks_all}건</b></span><span>📅 집계일 <b>{len(days)}일</b></span></div>
{synth_html}
<h2>🔺 급상승 키워드 (주간 빈도)</h2>
<div class="bars">{kw_rows}</div>
<h2>🗂️ 카테고리별 주간 볼륨</h2>
<div class="bars">{cat_rows}</div>
<h2>📆 일자별 추이</h2>
<table><thead><tr><th>날짜</th>{head}<th>합계</th><th>★</th></tr></thead><tbody>{trend}</tbody></table>
<footer>Daily Brief 주간 트렌드 · 매일 통계 스냅샷 누적 → 주간 집계 · 데이터 분석가 포트폴리오</footer>
</div></body></html>"""


def main() -> int:
    stats_dir = ROOT / "data" / "stats"
    files = sorted(stats_dir.glob("*.json")) if stats_dir.exists() else []
    days = []
    for f in files[-7:]:
        try:
            days.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    out = ROOT / "docs" / "weekly.html"
    out.write_text(render(days), encoding="utf-8")
    print(f"주간 리포트 저장: {out} (집계 {len(days)}일)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
