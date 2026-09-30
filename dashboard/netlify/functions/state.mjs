// Doc data/live_state.json moi nhat tu repo GitHub (bot commit moi gio).
// Bien moi truong dat trong Netlify > Site configuration > Environment variables:
//   GITHUB_REPO        vd "tenban/trading-bot"
//   GITHUB_TOKEN_READ  token chi co quyen DOC noi dung repo (bat buoc neu repo private)
//   GITHUB_BRANCH      mac dinh "main"
export default async () => {
  const repo = process.env.GITHUB_REPO;
  const branch = process.env.GITHUB_BRANCH || "main";
  const token = process.env.GITHUB_TOKEN_READ;
  const json = (body, status = 200) =>
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    });

  if (!repo) return json({ error: "Chưa đặt biến GITHUB_REPO trên Netlify." }, 500);

  const url = `https://api.github.com/repos/${repo}/contents/data/live_state.json?ref=${encodeURIComponent(branch)}`;
  const headers = { Accept: "application/vnd.github.raw+json", "User-Agent": "live-dashboard" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(url, { headers });
  if (res.status === 404) return json({ error: "Chưa có data/live_state.json — bot chưa chạy lần nào, hoặc sai GITHUB_REPO/token." }, 404);
  if (!res.ok) return json({ error: `GitHub trả về lỗi ${res.status}.` }, 502);
  return json(await res.text());
};
