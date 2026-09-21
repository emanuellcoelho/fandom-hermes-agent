/**
 * The odds edge: it holds the key so the agent never has to.
 *
 * This agent's image is public and its home is a tree that carries no
 * credential, so the credential lives here, as a Worker secret, and the agent
 * calls a public URL exactly as it calls thesportsdb. The contract is that
 * this speaks the provider's v4 verbatim -- same paths, same JSON, same
 * x-requests-* headers -- minus the ?apiKey=. Anything else and the agent's
 * source file would have to know it is talking to a proxy, which is the one
 * thing this design buys.
 *
 * Two jobs beyond forwarding:
 *
 *   1. It is not an open proxy. Only the three paths the agent reads are
 *      served, only GET, and any apiKey a caller sends is dropped before the
 *      real one goes on -- a Worker that will forward anything is a key
 *      somebody else can spend.
 *
 *   2. It caches, and says so. One read serves every user of this edge, which
 *      is what keeps a free tier from scaling with the userbase. A cache hit
 *      reports `x-requests-last: 0`, because the agent's ledger believes that
 *      header and a hit really did cost nothing.
 */

const ORIGIN = "https://api.the-odds-api.com";

// The three paths the agent reads, and nothing else. /v4/sports and the
// events list are free at the provider; only the odds path spends.
const SERVED = [
  { pattern: /^\/v4\/sports\/?$/, ttl: 3600 },
  { pattern: /^\/v4\/sports\/[a-z0-9_]+\/events\/?$/, ttl: 600 },
  { pattern: /^\/v4\/sports\/[a-z0-9_]+\/odds\/?$/, ttl: 300 },
  { pattern: /^\/v4\/sports\/[a-z0-9_]+\/events\/[A-Za-z0-9_-]+\/odds\/?$/, ttl: 300 },
];

// Forwarded whatever the status is: a 429 is exactly where remaining reads 0,
// and the budget on the other side is counting on seeing it.
const QUOTA_HEADERS = ["x-requests-remaining", "x-requests-used", "x-requests-last"];

function problem(status, reason) {
  return new Response(JSON.stringify({ error: reason }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

function served(pathname) {
  return SERVED.find((route) => route.pattern.test(pathname));
}

/** The cache key: the request as asked, minus any credential, params sorted. */
function cacheKeyFor(url) {
  const key = new URL(url.origin + url.pathname);
  const names = [...url.searchParams.keys()]
    .filter((name) => name.toLowerCase() !== "apikey")
    .sort();
  for (const name of names) key.searchParams.set(name, url.searchParams.get(name));
  return new Request(key.toString(), { method: "GET" });
}

export default {
  async fetch(request, env, context) {
    if (request.method !== "GET") return problem(405, "method_not_allowed");

    const url = new URL(request.url);
    const route = served(url.pathname);
    if (!route) return problem(404, "path_not_served");
    if (!env.ODDS_API_KEY) return problem(503, "edge_not_configured");

    const cache = caches.default;
    const key = cacheKeyFor(url);
    const hit = await cache.match(key);
    if (hit) {
      const headers = new Headers(hit.headers);
      headers.set("x-requests-last", "0");
      headers.set("x-cache", "HIT");
      return new Response(hit.body, { status: hit.status, headers });
    }

    const upstream = new URL(ORIGIN + url.pathname);
    for (const [name, value] of url.searchParams) {
      if (name.toLowerCase() !== "apikey") upstream.searchParams.set(name, value);
    }
    upstream.searchParams.set("apiKey", env.ODDS_API_KEY);

    let answer;
    try {
      answer = await fetch(upstream.toString(), { headers: { accept: "application/json" } });
    } catch (error) {
      // Never interpolate the request: the URL in hand carries the key.
      return problem(502, "upstream_unreachable");
    }

    const headers = new Headers({
      "content-type": answer.headers.get("content-type") || "application/json",
      "x-cache": "MISS",
    });
    for (const name of QUOTA_HEADERS) {
      const value = answer.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    headers.set(
      "cache-control",
      answer.status === 200 ? `public, max-age=${route.ttl}` : "no-store",
    );

    const body = await answer.arrayBuffer();
    const response = new Response(body, { status: answer.status, headers });
    if (answer.status === 200) context.waitUntil(cache.put(key, response.clone()));
    return response;
  },
};
