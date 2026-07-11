/*
 * RobinHood bot — live quote proxy (Cloudflare Worker, FREE tier: 100k req/day).
 *
 * WHY: the dashboard can't poll faster than ~5 min because raw.githubusercontent
 * caches for 300s. This Worker holds your Alpaca key SERVER-SIDE, fetches live
 * IEX quotes on demand, and returns them CORS-enabled with no-cache — so the
 * browser gets genuine ~15-30s live prices with the key never exposed.
 *
 * DEPLOY (one-time, ~10 min, free):
 *  1. Create a free account at https://workers.cloudflare.com
 *  2. `npm i -g wrangler` then `wrangler login`
 *  3. In this folder: `wrangler deploy`
 *  4. Set the Alpaca key as Worker secrets (never in code):
 *       wrangler secret put ALPACA_KEY
 *       wrangler secret put ALPACA_SECRET
 *  5. Copy the deployed URL (…workers.dev) and tell Claude — it wires the
 *     dashboard to poll it instead of the cached prices.json.
 *
 * Call: GET https://<your-worker>.workers.dev/?symbols=AVO,LRMR,WRAP
 */
export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-store, max-age=0",
      "Content-Type": "application/json",
    };
    const url = new URL(request.url);
    const symbols = (url.searchParams.get("symbols") || "").trim();
    if (!symbols) return new Response(JSON.stringify({ error: "?symbols= required" }), { headers: cors, status: 400 });

    try {
      const r = await fetch(
        "https://data.alpaca.markets/v2/stocks/trades/latest?feed=iex&symbols=" + encodeURIComponent(symbols),
        { headers: { "APCA-API-KEY-ID": env.ALPACA_KEY, "APCA-API-SECRET-KEY": env.ALPACA_SECRET } }
      );
      if (!r.ok) return new Response(JSON.stringify({ error: "alpaca " + r.status }), { headers: cors, status: 502 });
      const data = await r.json();
      const prices = {};
      for (const [t, trade] of Object.entries(data.trades || {})) if (trade.p) prices[t] = trade.p;
      return new Response(JSON.stringify({
        generated: new Date().toISOString(),
        source: "alpaca-worker",
        prices,
      }), { headers: cors });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e) }), { headers: cors, status: 500 });
    }
  },
};
