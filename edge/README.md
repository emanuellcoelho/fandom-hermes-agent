# fandom-odds-edge

The public face of the odds board. It holds the API key so the agent does not:
`fandom-hermes-agent` ships as a public image and keeps no credential under
its home, so the credential lives here as a Worker secret and the agent calls
a URL anyone could call.

It speaks the provider's v4 verbatim — same paths, same JSON, same
`x-requests-*` headers — minus the `?apiKey=`. That is the whole contract:
`fandom/sources/odds.py` does not know it is talking to a proxy.

## Deploy

    npm install -g wrangler        # or: npx wrangler@latest ...
    wrangler login                 # opens the browser, once per machine

    cd edge
    wrangler secret put ODDS_API_KEY     # paste the key at the prompt
    wrangler deploy

`wrangler deploy` prints the URL: `https://fandom-odds-edge.<subdomain>.workers.dev`.
That value goes into the agent's environment as `ODDS_EDGE_BASE` — in
`compose.yml` for a local run, in the cloud agent's environment otherwise.
Without it the agent answers `reason: "unconfigured"` and nothing breaks.

## Check it before wiring it

    curl -s "$EDGE/v4/sports/" | head -c 200          # free at the provider
    curl -si "$EDGE/v4/sports/soccer_brazil_campeonato/odds?regions=eu&markets=h2h" \
      | grep -i 'x-requests-\|x-cache'                 # spends one credit

Then the same path the agent uses, which is the only check that counts:

    FANDOM_LIVE_ODDS=1 ODDS_EDGE_BASE=$EDGE python3 -m pytest tests/test_odds_live.py -q

## What it refuses

Four paths, GET only, and any `apiKey` a caller sends is dropped before the
real one is attached. A Worker that forwards anything is a key somebody else
can spend.

## The cache is the point

The free tier is 500 credits a month per key, and it is one key for everyone
using this edge. Odds answers are cached 5 minutes, fixture lists 10, the
sports list an hour — so a hundred users asking about the same game at the
same time cost one credit, not a hundred.

A cache hit answers `x-requests-last: 0` and `x-cache: HIT`. The agent's
ledger believes that header, and a hit really did cost nothing.
