// Edge Function: dcf-data
// Fetches a quote + fundamentals time series from Yahoo Finance server-side
// (no browser CORS limits, handles Yahoo's cookie/crumb) for dcf.html.
// GET /functions/v1/dcf-data?ticker=GOOGL[&only=price|fundamentals]

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
};
const TYPES = [
  "trailingFreeCashFlow", "annualFreeCashFlow",
  "quarterlyTotalDebt", "annualTotalDebt",
  "quarterlyCapitalLeaseObligations", "annualCapitalLeaseObligations",
  "quarterlyLongTermDebt", "annualLongTermDebt",
  "quarterlyCurrentDebt", "annualCurrentDebt",
  "quarterlyCashCashEquivalentsAndShortTermInvestments", "annualCashCashEquivalentsAndShortTermInvestments",
  "quarterlyOrdinarySharesNumber", "annualOrdinarySharesNumber",
  "quarterlyDilutedAverageShares", "annualDilutedAverageShares",
];

let session: { cookie: string; crumb: string; at: number } | null = null;

async function getSession(force = false) {
  if (!force && session && Date.now() - session.at < 30 * 60_000) return session;
  let cookie = "";
  try {
    const r = await fetch("https://fc.yahoo.com", { headers: { "User-Agent": UA }, redirect: "manual" });
    const sc = r.headers.get("set-cookie") || "";
    cookie = sc.split(/,(?=[^;]+=)/).map((c) => c.split(";")[0].trim()).filter(Boolean).join("; ");
    await r.body?.cancel();
  } catch (_) { /* ignore */ }
  let crumb = "";
  try {
    const r = await fetch("https://query2.finance.yahoo.com/v1/test/getcrumb", {
      headers: { "User-Agent": UA, Cookie: cookie },
    });
    const t = (await r.text()).trim();
    if (r.ok && t && !t.includes("<") && t.length < 64) crumb = t;
  } catch (_) { /* ignore */ }
  session = { cookie, crumb, at: Date.now() };
  return session;
}

async function yahoo(url: string, retry = true): Promise<any> {
  const s = await getSession();
  const u = s.crumb ? url + (url.includes("?") ? "&" : "?") + "crumb=" + encodeURIComponent(s.crumb) : url;
  const r = await fetch(u, { headers: { "User-Agent": UA, Cookie: s.cookie, Accept: "application/json" } });
  if ((r.status === 401 || r.status === 403) && retry) { await getSession(true); return yahoo(url, false); }
  const txt = await r.text();
  try { return JSON.parse(txt); } catch (_) { return { error: `HTTP ${r.status}` }; }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
  const url = new URL(req.url);
  const tk = (url.searchParams.get("ticker") || "").trim().toUpperCase();
  const only = url.searchParams.get("only") || "";
  if (!/^[A-Z0-9.\-=^]{1,20}$/.test(tk)) {
    return new Response(JSON.stringify({ error: "ticker inválido" }), {
      status: 400, headers: { ...CORS, "Content-Type": "application/json" },
    });
  }
  const e = encodeURIComponent(tk);
  const now = Math.floor(Date.now() / 1000), from = now - 7 * 365 * 86400;
  const [chart, timeseries] = await Promise.all([
    only === "fundamentals" ? null
      : yahoo(`https://query2.finance.yahoo.com/v8/finance/chart/${e}?range=1d&interval=1d`),
    only === "price" ? null
      : yahoo(`https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/${e}?symbol=${e}&type=${TYPES.join(",")}&period1=${from}&period2=${now}`),
  ]);
  return new Response(JSON.stringify({ ticker: tk, chart, timeseries }), {
    headers: { ...CORS, "Content-Type": "application/json", "Cache-Control": "public, max-age=60" },
  });
});
