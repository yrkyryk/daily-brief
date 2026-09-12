// Vercel 서버리스 함수: 리포트에서 고른 카드를 Notion에 저장한다.
// 환경변수(Vercel): NOTION_TOKEN, NOTION_DB_ID, APP_KEY
// 요청: POST JSON { cards: [ {title,link,source,cat,summary,why,hash,date}, ... ] }
//       헤더 x-app-key: APP_KEY  (무단 호출 차단)
// 비밀은 서버 환경변수에만 있고 공개 페이지/레포에는 없다.

const NOTION = "https://api.notion.com/v1";
const NOTION_VERSION = "2022-06-28";
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "*";  // 포크 시 env로 자기 도메인 지정(기본 전체 허용, APP_KEY로 보호)

function rt(text) {
  return [{ type: "text", text: { content: String(text || "").slice(0, 1900) } }];
}

async function notion(path, token, method, body) {
  const res = await fetch(NOTION + path, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Notion-Version": NOTION_VERSION,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`Notion ${method} ${path} ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res.json();
}

async function existingHashes(token, db, dates) {
  const seen = new Set();
  for (const d of dates) {
    let cursor;
    do {
      const body = { filter: { property: "날짜", date: { equals: d } }, page_size: 100 };
      if (cursor) body.start_cursor = cursor;
      const r = await notion(`/databases/${db}/query`, token, "POST", body);
      for (const p of r.results || []) {
        const h = p.properties?.Hash?.rich_text?.[0]?.plain_text;
        if (h) seen.add(h);
      }
      cursor = r.has_more ? r.next_cursor : null;
    } while (cursor);
  }
  return seen;
}

async function ogImage(url) {
  try {
    const res = await fetch(url, { headers: { "User-Agent": "DailyBriefBot/1.0" } });
    const html = (await res.text()).slice(0, 200000);
    const m = html.match(/<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)["'][^>]*>/i);
    if (m) {
      const c = m[0].match(/content=["']([^"']+)["']/i);
      if (c && c[1].startsWith("http")) return c[1];
    }
  } catch (e) {}
  return null;
}

async function createCard(token, db, c) {
  const props = {
    "제목": { title: [{ type: "text", text: { content: String(c.title || "").slice(0, 1900) } }] },
    "카테고리": { select: { name: c.cat || "내소스" } },
    "출처": { rich_text: rt(c.source) },
    "읽을이유": { rich_text: rt(c.why) },
    "요약": { rich_text: rt(c.summary) },
    "날짜": { date: { start: c.date } },
    "월": { rich_text: rt(String(c.date || "").slice(0, 7)) },
    "Hash": { rich_text: rt(c.hash) },
  };
  if (c.link) props["링크"] = { url: c.link };
  const body = { parent: { database_id: db }, properties: props };
  const img = c.link ? await ogImage(c.link) : null;
  if (img) body.cover = { type: "external", external: { url: img } };
  await notion("/pages", token, "POST", body);
}

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", ALLOW_ORIGIN);
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "content-type, x-app-key");
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });

  const { NOTION_TOKEN, NOTION_DB_ID, APP_KEY } = process.env;
  if (!NOTION_TOKEN || !NOTION_DB_ID || !APP_KEY)
    return res.status(500).json({ error: "server env not configured" });
  if ((req.headers["x-app-key"] || "") !== APP_KEY)
    return res.status(401).json({ error: "invalid app key" });

  let body = req.body;
  if (typeof body === "string") { try { body = JSON.parse(body); } catch (e) { body = null; } }
  const cards = body && Array.isArray(body.cards) ? body.cards : null;
  if (!cards || !cards.length) return res.status(400).json({ error: "no cards" });

  try {
    const dates = [...new Set(cards.map((c) => c.date).filter(Boolean))];
    const seen = await existingHashes(NOTION_TOKEN, NOTION_DB_ID, dates);
    let created = 0, skipped = 0;
    for (const c of cards) {
      if (c.hash && seen.has(c.hash)) { skipped++; continue; }
      await createCard(NOTION_TOKEN, NOTION_DB_ID, c);
      if (c.hash) seen.add(c.hash);
      created++;
    }
    return res.status(200).json({ created, skipped, total: cards.length });
  } catch (e) {
    return res.status(502).json({ error: String(e.message || e) });
  }
};
