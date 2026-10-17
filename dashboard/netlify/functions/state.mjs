// Tra ve trang thai moi nhat cua 2 bot (FX va crypto) doc tu repo GitHub.
// Bien moi truong Netlify: GITHUB_REPO (vd "tenban/repo"), GITHUB_TOKEN_READ (neu repo private), GITHUB_BRANCH (mac dinh main)
async function read(path) {
  const repo = process.env.GITHUB_REPO, branch = process.env.GITHUB_BRANCH || "main", token = process.env.GITHUB_TOKEN_READ;
  const headers = { Accept: "application/vnd.github.raw+json", "User-Agent": "dashboard" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(`https://api.github.com/repos/${repo}/contents/${path}?ref=${encodeURIComponent(branch)}`, { headers });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  return JSON.parse(await r.text());
}
export default async () => {
  const json = (b, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
  if (!process.env.GITHUB_REPO) return json({ error: "Chưa đặt biến GITHUB_REPO trên Netlify." }, 500);
  try {
    const [fx, crypto] = await Promise.all([read("data/fx_rank_state.json"), read("data/crypto_ma_state.json")]);
    return json({ fx, crypto });
  } catch (e) { return json({ error: String(e.message || e) }, 502); }
};
