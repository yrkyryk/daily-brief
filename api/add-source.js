// Vercel 서버리스: Daily Brief 페이지에서 커스텀 소스(my_sources.txt)를 관리한다.
// 환경변수: GITHUB_TOKEN(레포 contents R/W + actions:write), APP_KEY
// 요청: POST { action: "list" | "add" | "remove" | "refresh", url? }  + 헤더 x-app-key
const REPO = process.env.GH_REPO || "yrkyryk/daily-brief";  // 포크 시 env로 자기 레포 지정 (예: user/daily-brief)
const FILE = "my_sources.txt";
const BRANCH = "main";
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "*";

async function gh(path, token, method, body) {
  const res = await fetch("https://api.github.com" + path, {
    method: method || "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "DailyBriefBot",
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok && res.status !== 404)
    throw new Error(`GitHub ${method || "GET"} ${path} ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return res;
}

function sourcesOf(text) {
  return text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith("#"));
}

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", ALLOW_ORIGIN);
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "content-type, x-app-key");
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });

  const { GITHUB_TOKEN, APP_KEY } = process.env;
  if (!GITHUB_TOKEN || !APP_KEY) return res.status(500).json({ error: "server env not configured" });
  if ((req.headers["x-app-key"] || "") !== APP_KEY) return res.status(401).json({ error: "invalid app key" });

  let body = req.body;
  if (typeof body === "string") { try { body = JSON.parse(body); } catch (e) { body = {}; } }
  const action = (body && body.action) || "list";
  const url = (body && body.url ? String(body.url).trim() : "");

  try {
    if (action === "refresh") {
      await gh(`/repos/${REPO}/actions/workflows/daily.yml/dispatches`, GITHUB_TOKEN, "POST", { ref: BRANCH });
      return res.status(200).json({ ok: true, refreshed: true });
    }

    // 현재 파일 읽기
    const getRes = await gh(`/repos/${REPO}/contents/${FILE}?ref=${BRANCH}`, GITHUB_TOKEN);
    let text = "", sha;
    if (getRes.status === 200) {
      const j = await getRes.json();
      sha = j.sha;
      text = Buffer.from(j.content, "base64").toString("utf8");
    }

    if (action === "list")
      return res.status(200).json({ sources: sourcesOf(text) });

    if (action === "add") {
      if (!url) return res.status(400).json({ error: "no url" });
      if (!sourcesOf(text).includes(url)) {
        text = text.replace(/\s*$/, "") + "\n" + url + "\n";
        await gh(`/repos/${REPO}/contents/${FILE}`, GITHUB_TOKEN, "PUT", {
          message: `chore: add source ${url}`, branch: BRANCH,
          content: Buffer.from(text, "utf8").toString("base64"), sha,
        });
      }
      return res.status(200).json({ sources: sourcesOf(text) });
    }

    if (action === "remove") {
      if (!url) return res.status(400).json({ error: "no url" });
      const kept = text.split(/\r?\n/).filter((l) => l.trim() !== url);
      text = kept.join("\n");
      await gh(`/repos/${REPO}/contents/${FILE}`, GITHUB_TOKEN, "PUT", {
        message: `chore: remove source ${url}`, branch: BRANCH,
        content: Buffer.from(text, "utf8").toString("base64"), sha,
      });
      return res.status(200).json({ sources: sourcesOf(text) });
    }

    return res.status(400).json({ error: "unknown action" });
  } catch (e) {
    return res.status(502).json({ error: String(e.message || e) });
  }
};
