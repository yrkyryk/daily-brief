# -*- coding: utf-8 -*-
"""
report.py — AI 요약을 얹은 Daily Brief HTML 리포트 생성 (5단계)

입력: data/raw_YYYY-MM-DD.jsonl (수집 증거)
처리: 카테고리별 AI '흐름 요약' + '읽을 가치 높음' 선별 (judge_ai)
출력: docs/daily-brief-YYYY-MM-DD.html

OAuth(claude CLI / CLAUDE_CODE_OAUTH_TOKEN) 없으면 규칙 전용 모드로 폴백하고 리포트에 명시한다.
"""
import json, html, datetime, sys, pathlib, re

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import judge_ai
import interests

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
TODAY = NOW.strftime("%Y-%m-%d")

CAT_ORDER = ["경제", "사회", "연예", "실무", "내소스"]
CAT_EMOJI = {"경제": "💹", "사회": "🏛️", "연예": "🎬", "실무": "🛠️", "내소스": "📌"}


def esc(s):
    return html.escape(s or "")


# --- 원본 로드 ---
raw_path = ROOT / "data" / f"raw_{TODAY}.jsonl"
if not raw_path.exists():
    print(f"[중단] 원본 수집 파일 없음: {raw_path}\n먼저 수집 스크립트를 실행하세요.")
    sys.exit(1)

items = [json.loads(l) for l in raw_path.read_text(encoding="utf-8").splitlines() if l.strip()]
by_cat = {}
for it in items:
    by_cat.setdefault(it["cat"], []).append(it)
total = len(items)

# --- AI 요약 (OAuth: Claude CLI 헤드리스) ---
claude_bin = judge_ai.find_claude()
ai_summaries = {}
budget = {"in": 0, "out": 0, "calls": 0, "cost": 0.0}
ai_mode = "규칙 전용 (claude CLI 없음)"

# AI 요약 캐시 (멱등성 + 비용 중복 방지): 카테고리별 결과를 즉시 저장하고
# 재실행 시 캐시된 카테고리는 재호출하지 않는다.
cache_path = ROOT / "data" / f"ai_cache_{TODAY}.json"
cache = {}
if cache_path.exists():
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}

if claude_bin:
    try:
        print(f"AI 요약 시작 (OAuth · {claude_bin} · model={judge_ai.MODEL}) …")
        for cat in CAT_ORDER:
            if cat == "내소스":  # 커스텀 소스는 AI 요약·픽 제외 (원문 카드만)
                continue
            cat_items = by_cat.get(cat, [])
            if not cat_items:
                continue
            if cat in cache:  # 캐시 재사용 (호출·비용 없음)
                ai_summaries[cat] = cache[cat]
                print(f"  [{cat}] 캐시 재사용 (picks={len(cache[cat].get('picks', []))})")
                continue
            res = judge_ai.summarize_category(claude_bin, cat, cat_items, budget)
            ai_summaries[cat] = res
            cache[cat] = res
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            tk = res.get("_tokens", {})
            print(f"  [{cat}] in={tk.get('in')} out={tk.get('out')} picks={len(res.get('picks', []))}")
        ai_mode = f"AI 보조 · OAuth ({judge_ai.MODEL})"
    except Exception as ex:
        print(f"[경고] AI 호출 실패, 있는 캐시까지만 사용하고 나머지는 규칙 전용: {ex}")
        ai_mode = f"부분 AI (호출 실패: {type(ex).__name__})" if ai_summaries else f"규칙 전용 (AI 호출 실패: {type(ex).__name__})"
elif cache:
    ai_summaries.update({k: v for k, v in cache.items() if k != "내소스"})
    ai_mode = f"AI 보조 · 캐시 ({judge_ai.MODEL})"
    print(f"[안내] claude CLI 없음 → 캐시된 AI 요약 {len(cache)}건 재사용")
else:
    print("[안내] claude CLI 없음 → 규칙 전용 모드. Node.js + Claude Code CLI 설치 후 `claude` 로그인하면 AI 요약이 켜집니다.")

cost = budget["cost"]
print(f"\n=== AI 비용 로그 (V3 6번) ===")
print(f"호출 {budget['calls']}회 · 입력 {budget['in']} tok · 출력 {budget['out']} tok · 추정 ${cost:.5f}")

# --- 카테고리별 '읽을 가치 높음' 인덱스 매핑 ---
pick_map = {}  # (cat, idx0) -> why
for cat, res in ai_summaries.items():
    for p in res.get("picks", []):
        try:
            pick_map[(cat, int(p["n"]) - 1)] = p.get("why", "")
        except Exception:
            pass

# --- 픽을 파일로 내보내기 (notion_publish.py 입력, 인덱스 드리프트 방지) ---
picks_out = []
for cat in CAT_ORDER:
    for i, it in enumerate(by_cat.get(cat, [])):
        why = pick_map.get((cat, i))
        if why is None:
            continue
        picks_out.append({
            "title": it["title"], "link": it["link"], "source": it["source"],
            "cat": cat, "pub": it.get("pub", ""), "why": why,
            "summary": it["summary"], "hash": it["hash"], "date": TODAY,
        })
(ROOT / "data" / f"picks_{TODAY}.json").write_text(
    json.dumps(picks_out, ensure_ascii=False), encoding="utf-8")
print(f"픽 내보내기: data/picks_{TODAY}.json ({len(picks_out)}건)")

# --- 일일 통계 스냅샷 (주간 트렌드 집계용, 커밋되어 축적) ---
STOP = {"기자", "연합뉴스", "경향신문", "한겨레", "제공", "오늘", "이번", "관련", "위해",
        "대한", "그리고", "이라고", "했다", "한다", "있다", "이다", "대해", "통해", "라고",
        "에서", "으로", "하는", "하고", "까지", "부터", "면서", "때문", "최근", "지난",
        "이날", "기사", "뉴스", "블로그", "기술", "예정", "밝혔다", "말했다"}


def _kw_freq(rows):
    freq = {}
    for it in rows:
        text = f"{it.get('title','')} {it.get('summary','')}"
        for tok in re.findall(r"[가-힣]{2,}|[A-Za-z]{2,}", text):
            t = tok.lower() if tok.isascii() else tok
            if len(t) < 2 or t in STOP:
                continue
            freq[t] = freq.get(t, 0) + 1
    return dict(sorted(freq.items(), key=lambda x: -x[1])[:40])


stats = {
    "date": TODAY, "total": total,
    "by_cat": {c: len(by_cat.get(c, [])) for c in CAT_ORDER},
    "pick_count": len(pick_map),
    "keywords": _kw_freq(items),
}
stats_dir = ROOT / "data" / "stats"
stats_dir.mkdir(parents=True, exist_ok=True)
(stats_dir / f"{TODAY}.json").write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
print(f"통계 스냅샷: data/stats/{TODAY}.json")

# --- HTML 조립 ---
default_keywords = interests.load()  # 최초 방문 시 브라우저에 시드될 기본 키워드


def card_html(it, cat, why):
    pick_badge = '<span class="pick">★ 읽을 가치</span>' if why is not None else ""
    why_html = f'<div class="why">💡 {esc(why)}</div>' if why else ""
    cardobj = {"title": it["title"], "link": it["link"], "source": it["source"],
               "cat": cat, "summary": it["summary"], "why": why or "",
               "hash": it["hash"], "date": TODAY}
    dc = esc(json.dumps(cardobj, ensure_ascii=False))
    return f"""
        <article class="card{' hot' if why is not None else ''}" data-cat="{esc(cat)}" data-text="{esc((it['title']+' '+it['summary']).lower())}" data-card="{dc}">
          <button class="savecard" type="button">☁️ Notion 저장</button>
          <div class="card-top"><span class="badge b-{esc(cat)}">{CAT_EMOJI.get(cat, '📌')} {esc(cat)}</span><span class="src">{esc(it['source'])}{(' · '+it['pub']) if it['pub'] else ''}</span></div>
          <h3><a href="{esc(it['link'])}" target="_blank" rel="noopener">{esc(it['title'])}</a>{pick_badge}</h3>
          <p>{esc(it['summary']) or '<span class=nosum>요약 없음</span>'}</p>
          {why_html}
        </article>"""


cards_html = []
for cat in CAT_ORDER:
    for i, it in enumerate(by_cat.get(cat, [])):
        cards_html.append(card_html(it, cat, pick_map.get((cat, i))))

# 카테고리별 AI 흐름 요약 블록
flow_blocks = []
for cat in CAT_ORDER:
    res = ai_summaries.get(cat)
    if res and res.get("summary"):
        flow_blocks.append(f"""
        <div class="flow" data-cat="{cat}">
          <div class="flow-h">{CAT_EMOJI[cat]} {cat} · 오늘의 흐름 <span class="ai-tag">AI</span></div>
          <p>{esc(res['summary'])}</p>
        </div>""")

tabs = [f'<button class="tab active" data-f="all">전체 ({total})</button>']
for cat in CAT_ORDER:
    n = len(by_cat.get(cat, []))
    if n:
        tabs.append(f'<button class="tab" data-f="{cat}">{CAT_EMOJI[cat]} {cat} ({n})</button>')

HTML = f"""<!doctype html><html lang="ko"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Brief — {TODAY}</title>
<style>
:root{{--bg:#0f1115;--card:#181b22;--line:#262b36;--tx:#e7eaf0;--mut:#8b93a5;--acc:#5b8cff;
--eco:#f5a623;--soc:#4fd1c5;--ent:#ff6b9d;--wrk:#9d7bff;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);font-family:'Pretendard','Malgun Gothic',system-ui,sans-serif;line-height:1.5}}
.wrap{{max-width:1000px;margin:0 auto;padding:28px 18px 60px}}
header h1{{font-size:26px;margin:0 0 4px;letter-spacing:-.5px}}
header .sub{{color:var(--mut);font-size:14px}}
.meta{{display:flex;gap:18px;flex-wrap:wrap;margin:16px 0 22px;font-size:13px;color:var(--mut)}}
.meta b{{color:var(--tx)}}
.search{{width:100%;padding:11px 14px;background:var(--card);border:1px solid var(--line);border-radius:10px;color:var(--tx);font-size:15px;margin-bottom:14px}}
.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}}
.tab{{background:var(--card);border:1px solid var(--line);color:var(--mut);padding:8px 14px;border-radius:20px;cursor:pointer;font-size:13px;transition:.15s}}
.tab:hover{{color:var(--tx)}}
.tab.active{{background:var(--acc);color:#fff;border-color:var(--acc)}}
.flows{{margin-bottom:22px;display:grid;gap:12px}}
.flow{{background:linear-gradient(180deg,rgba(91,140,255,.08),transparent);border:1px solid var(--line);border-left:3px solid var(--acc);border-radius:10px;padding:14px 16px}}
.flow-h{{font-weight:700;font-size:14px;margin-bottom:6px}}
.flow p{{margin:0;font-size:13px;color:var(--tx);white-space:pre-line}}
.ai-tag{{background:var(--acc);color:#fff;font-size:10px;padding:1px 7px;border-radius:8px;margin-left:6px;vertical-align:middle}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:680px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
.card.hot{{border-color:rgba(91,140,255,.5);box-shadow:0 0 0 1px rgba(91,140,255,.2)}}
.card-top{{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}}
.badge{{font-size:11px;padding:3px 9px;border-radius:12px;font-weight:600}}
.b-경제{{background:rgba(245,166,35,.15);color:var(--eco)}}
.b-사회{{background:rgba(79,209,197,.15);color:var(--soc)}}
.b-연예{{background:rgba(255,107,157,.15);color:var(--ent)}}
.b-실무{{background:rgba(157,123,255,.15);color:var(--wrk)}}
.src{{font-size:11px;color:var(--mut)}}
.card h3{{margin:0 0 6px;font-size:15px;line-height:1.35}}
.card h3 a{{color:var(--tx);text-decoration:none}}
.card h3 a:hover{{color:var(--acc)}}
.pick{{background:rgba(91,140,255,.18);color:#9db8ff;font-size:10px;padding:2px 7px;border-radius:8px;margin-left:6px;white-space:nowrap}}
.why{{margin-top:8px;font-size:12px;color:#9db8ff;background:rgba(91,140,255,.08);padding:6px 9px;border-radius:8px}}
.card p{{margin:0;font-size:13px;color:var(--mut)}}
.nosum{{font-style:italic;opacity:.6}}
footer{{margin-top:30px;font-size:12px;color:var(--mut);text-align:center}}
.cost{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;font-size:12px;color:var(--mut);margin-top:20px}}
.cost b{{color:var(--tx)}}
.b-내소스{{background:rgba(91,140,255,.15);color:#9db8ff}}
.kwbar{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 14px;padding:12px 14px;background:var(--card);border:1px solid var(--line);border-radius:12px}}
.kwbar-label{{font-size:13px;font-weight:600}}
.kwbar-hint{{font-size:11px;color:var(--mut);margin-left:auto}}
.chips{{display:flex;gap:6px;flex-wrap:wrap}}
.chip{{background:rgba(91,140,255,.15);color:#9db8ff;font-size:12px;padding:3px 9px;border-radius:14px;display:inline-flex;align-items:center;gap:6px}}
.chip b{{cursor:pointer;opacity:.65;font-weight:700}}
.chip b:hover{{opacity:1}}
.kwadd{{background:#0f1115;border:1px solid var(--line);border-radius:8px;color:var(--tx);font-size:13px;padding:6px 10px;min-width:150px}}
#tabInterest{{border-color:rgba(91,140,255,.4)}}
.srcbtn{{background:transparent;border:1px solid var(--line);color:var(--mut);border-radius:8px;font-size:12px;padding:5px 10px;cursor:pointer}}
.srcbtn:hover{{color:var(--tx);border-color:var(--acc)}}
.savecard{{float:right;background:rgba(91,140,255,.15);color:#9db8ff;border:1px solid rgba(91,140,255,.35);border-radius:8px;font-size:11px;padding:3px 9px;cursor:pointer}}
.savecard:hover{{background:rgba(91,140,255,.3)}}
.savecard.done{{color:#7bd88f;border-color:rgba(123,216,143,.45);background:rgba(123,216,143,.12);cursor:default}}
.notioncfg{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 14px;padding:10px 14px;background:var(--card);border:1px solid var(--line);border-radius:12px;font-size:13px}}
.notioncfg button{{background:var(--acc);color:#fff;border:0;padding:6px 12px;border-radius:8px;font-size:12px;cursor:pointer}}
.notioncfg .kwbar-hint{{margin-left:auto}}
.savemsg{{font-size:12px;color:#9db8ff}}
</style></head><body><div class="wrap">
<header>
  <h1>📰 Daily Brief</h1>
  <div class="sub">규칙 필터(홍보·중복 제거) + <b>AI 흐름 요약·읽을 가치 판정</b>을 거친 오늘의 브리핑 · <a href="./weekly.html" style="color:var(--acc);text-decoration:none">📈 주간 트렌드 →</a></div>
</header>
<div class="meta">
  <span>📅 <b>{NOW.strftime('%Y-%m-%d %H:%M')} KST</b></span>
  <span>🗂️ 수집 <b>{total}건</b></span>
  <span>🧠 판정 모드 <b>{esc(ai_mode)}</b></span>
  <span>⭐ 읽을 가치 <b>{len(pick_map)}건</b></span>
</div>

<div class="notioncfg">
  <span>☁️ <b>Notion 저장</b></span>
  <button id="cfgBtn" type="button">연결 설정</button>
  <span id="saveMsg" class="savemsg"></span>
  <span class="kwbar-hint">각 카드의 ☁️ Notion 저장 버튼으로 바로 보냄</span>
</div>
<div id="cfgModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:99;align-items:center;justify-content:center">
  <div style="background:#181b22;border:1px solid #262b36;border-radius:12px;padding:20px;width:min(440px,92%)">
    <h3 style="margin:0 0 14px;font-size:15px">☁️ Notion 연결 설정</h3>
    <div style="font-size:12px;color:#8b93a5;margin-bottom:4px">함수 URL</div>
    <input id="cfgUrl" autocomplete="off" placeholder="https://<내-프로젝트>.vercel.app/api/publish-notion" style="width:100%;padding:9px 11px;background:#0f1115;border:1px solid #262b36;border-radius:8px;color:#e7eaf0;font-size:13px;margin-bottom:12px">
    <div style="font-size:12px;color:#8b93a5;margin-bottom:4px">APP_KEY</div>
    <input id="cfgKey" type="password" autocomplete="new-password" placeholder="비밀 값 (가려짐)" style="width:100%;padding:9px 11px;background:#0f1115;border:1px solid #262b36;border-radius:8px;color:#e7eaf0;font-size:13px">
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
      <button id="cfgCancel" type="button" style="background:transparent;border:1px solid #262b36;color:#8b93a5;padding:8px 14px;border-radius:8px;cursor:pointer">취소</button>
      <button id="cfgSave" type="button" style="background:#5b8cff;border:0;color:#fff;padding:8px 16px;border-radius:8px;cursor:pointer">저장</button>
    </div>
  </div>
</div>
<div class="kwbar">
  <span class="kwbar-label">🔖 관심 키워드</span>
  <span class="chips" id="kwchips"></span>
  <input id="kwadd" class="kwadd" placeholder="키워드 추가 후 Enter">
  <span class="kwbar-hint">브라우저에 저장 · 개인별</span>
</div>
<div class="kwbar">
  <span class="kwbar-label">📌 내 소스</span>
  <span class="chips" id="srcchips"></span>
  <input id="srcadd" class="kwadd" placeholder="블로그/사이트 URL 추가 후 Enter">
  <button id="srcRefresh" type="button" class="srcbtn">🔄 지금 수집</button>
  <span id="srcMsg" class="savemsg"></span>
</div>
<input class="search" id="q" placeholder="🔍 제목·요약 검색…">
<div class="tabs"><button class="tab" data-f="interest" id="tabInterest">🔖 관심 <span id="kwcount"></span></button>{''.join(tabs)}</div>
<div class="flows" id="flows">{''.join(flow_blocks) or '<div class="flow"><p>AI 요약 미적용 (규칙 전용 모드). GitHub Actions에 CLAUDE_CODE_OAUTH_TOKEN 시크릿을 등록하거나, 로컬에서 `claude` 로그인 후 다시 실행하면 카테고리별 흐름 요약이 채워집니다.</p></div>'}</div>
<div class="grid" id="grid">{''.join(cards_html)}</div>

<div class="cost">
  🧠 AI 비용 로그 (V3 6번) · 모델 <b>{esc(judge_ai.MODEL)}</b> ·
  호출 <b>{budget['calls']}회</b> · 입력 <b>{budget['in']:,} tok</b> · 출력 <b>{budget['out']:,} tok</b> ·
  추정 비용 <b>${cost:.5f}</b>
  <br>규칙 필터가 137건을 먼저 정제했기에 AI 호출은 카테고리당 1회로 묶여 비용이 최소화됩니다 (항목별 호출 대비 약 1/34).
</div>

<footer>
  Daily Brief 자동화 파이프라인 · 규칙 우선 필터(기계) + AI 보조 판정 · 데이터 분석가 포트폴리오
</footer>
</div>
<script>
const q=document.getElementById('q'), grid=document.getElementById('grid'), flows=document.getElementById('flows');
let curF='all';
const DEFAULT_KW={json.dumps(default_keywords, ensure_ascii=False)};
let kws=loadKw();
function loadKw(){{ try{{const v=localStorage.getItem('db_keywords'); if(v) return JSON.parse(v);}}catch(e){{}} return DEFAULT_KW.slice(); }}
function saveKw(){{ try{{localStorage.setItem('db_keywords', JSON.stringify(kws));}}catch(e){{}} }}
function escg(s){{ return (s||'').replace(/[&<>"]/g, m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[m])); }}
function renderChips(){{
  const c=document.getElementById('kwchips'); if(!c) return;
  c.innerHTML=kws.map((k,i)=>'<span class="chip">'+escg(k)+'<b data-i="'+i+'">×</b></span>').join('');
  c.querySelectorAll('b').forEach(b=>b.onclick=()=>{{ kws.splice(+b.dataset.i,1); saveKw(); renderChips(); updateCount(); apply(); }});
}}
function matchesKw(c){{ if(!kws.length) return false; const t=c.dataset.text; return kws.some(k=>t.includes(k.toLowerCase())); }}
function updateCount(){{ let n=0; grid.querySelectorAll('.card').forEach(c=>{{ if(matchesKw(c)) n++; }}); const el=document.getElementById('kwcount'); if(el) el.textContent='('+n+')'; }}
function apply(){{
  const t=q.value.trim().toLowerCase();
  grid.querySelectorAll('.card').forEach(c=>{{
    const okCat = curF==='all' ? true : (curF==='interest' ? matchesKw(c) : c.dataset.cat===curF);
    const okTxt = !t || c.dataset.text.includes(t);
    c.style.display=(okCat&&okTxt)?'':'none';
  }});
  flows.querySelectorAll('.flow').forEach(f=>{{
    if(!f.dataset.cat) return;
    f.style.display=(curF==='all'||f.dataset.cat===curF)?'':'none';
  }});
}}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{{
  document.querySelector('.tab.active').classList.remove('active');
  b.classList.add('active'); curF=b.dataset.f; apply();
}});
q.oninput=apply;
const kwadd=document.getElementById('kwadd');
if(kwadd) kwadd.addEventListener('keydown',e=>{{
  if(e.key==='Enter'){{ const v=kwadd.value.trim(); if(v && !kws.includes(v)){{ kws.push(v); saveKw(); renderChips(); updateCount(); apply(); }} kwadd.value=''; }}
}});
renderChips(); updateCount();
const msg=document.getElementById('saveMsg');
function getCfg(){{ return {{url:localStorage.getItem('db_fnurl')||'', key:localStorage.getItem('db_appkey')||''}}; }}
function openCfg(){{ const c=getCfg(); const u=document.getElementById('cfgUrl'), k=document.getElementById('cfgKey'); if(u)u.value=c.url; if(k)k.value=c.key; const m=document.getElementById('cfgModal'); if(m)m.style.display='flex'; }}
function closeCfg(){{ const m=document.getElementById('cfgModal'); if(m)m.style.display='none'; }}
const cfgBtn=document.getElementById('cfgBtn');
if(cfgBtn) cfgBtn.onclick=openCfg;
const cfgSave=document.getElementById('cfgSave');
if(cfgSave) cfgSave.onclick=()=>{{ localStorage.setItem('db_fnurl',(document.getElementById('cfgUrl').value||'').trim()); localStorage.setItem('db_appkey',(document.getElementById('cfgKey').value||'').trim()); closeCfg(); if(msg) msg.textContent='연결 설정 저장됨'; }};
const cfgCancel=document.getElementById('cfgCancel');
if(cfgCancel) cfgCancel.onclick=closeCfg;
async function saveCard(btn){{
  let cfg=getCfg(); if(!cfg.url||!cfg.key){{ openCfg(); if(msg) msg.textContent='먼저 연결 설정을 하세요'; return; }}
  const card=JSON.parse(btn.closest('.card').dataset.card);
  const old=btn.textContent; btn.textContent='저장 중…'; btn.disabled=true;
  try{{
    const r=await fetch(cfg.url,{{method:'POST',headers:{{'Content-Type':'application/json','x-app-key':cfg.key}},body:JSON.stringify({{cards:[card]}})}});
    const j=await r.json().catch(()=>({{}}));
    if(r.ok){{ btn.textContent=j.created? '✓ 저장됨' : '이미 있음'; btn.classList.add('done'); }}
    else {{ btn.textContent=old; btn.disabled=false; if(msg) msg.textContent='오류: '+(j.error||r.status); }}
  }}catch(e){{ btn.textContent=old; btn.disabled=false; if(msg) msg.textContent='요청 실패: '+e; }}
}}
document.querySelectorAll('.savecard').forEach(b=>b.onclick=()=>saveCard(b));

// 내 소스 관리 (add-source 엔드포인트)
const srcMsg=document.getElementById('srcMsg');
function srcEndpoint(){{ const u=getCfg().url; return u? u.replace('publish-notion','add-source') : ''; }}
async function srcCall(action, url){{
  const ep=srcEndpoint(), key=getCfg().key;
  if(!ep||!key){{ openCfg(); if(srcMsg) srcMsg.textContent='먼저 연결 설정을 하세요'; return null; }}
  try{{
    const r=await fetch(ep,{{method:'POST',headers:{{'Content-Type':'application/json','x-app-key':key}},body:JSON.stringify({{action,url}})}});
    const j=await r.json().catch(()=>({{}}));
    if(!r.ok){{ if(srcMsg) srcMsg.textContent='오류: '+(j.error||r.status); return null; }}
    return j;
  }}catch(e){{ if(srcMsg) srcMsg.textContent='요청 실패: '+e; return null; }}
}}
function renderSrc(list){{
  const c=document.getElementById('srcchips'); if(!c) return;
  c.innerHTML=(list&&list.length)? list.map(s=>'<span class="chip">'+escg(s)+'<b data-u="'+encodeURIComponent(s)+'">×</b></span>').join('') : '<span class="kwbar-hint">등록된 소스 없음</span>';
  c.querySelectorAll('b').forEach(b=>b.onclick=async()=>{{ const j=await srcCall('remove',decodeURIComponent(b.dataset.u)); if(j){{ renderSrc(j.sources); if(srcMsg) srcMsg.textContent='삭제됨'; }} }});
}}
const srcadd=document.getElementById('srcadd');
if(srcadd) srcadd.addEventListener('keydown',async e=>{{ if(e.key==='Enter'){{ const v=srcadd.value.trim(); if(v){{ const j=await srcCall('add',v); if(j){{ renderSrc(j.sources); if(srcMsg) srcMsg.textContent='추가됨 · [지금 수집]을 눌러 반영'; }} }} srcadd.value=''; }} }});
const srcRefresh=document.getElementById('srcRefresh');
if(srcRefresh) srcRefresh.onclick=async()=>{{ const j=await srcCall('refresh'); if(j&&srcMsg) srcMsg.textContent='수집 실행됨 · 1~2분 뒤 새로고침'; }};
if(getCfg().url&&getCfg().key) srcCall('list').then(j=>{{ if(j) renderSrc(j.sources); }});
</script>
</body></html>"""

out = ROOT / "docs" / f"daily-brief-{TODAY}.html"
out.write_text(HTML, encoding="utf-8")
# GitHub Pages 루트가 항상 최신 리포트를 가리키도록 index.html 로도 저장
index = ROOT / "docs" / "index.html"
index.write_text(HTML, encoding="utf-8")
print(f"\n리포트 저장: {out}")
print(f"최신본(index): {index}")
