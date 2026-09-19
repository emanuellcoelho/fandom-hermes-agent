# Fandom -- a sports-fandom agent, built FROM the plow-hermes-agent base.
#
# No boot, no gateway config, no model wiring here: those are the base's, and
# arrive as a digest bump. This repo adds one thing -- the persona and skills
# of one assistant -- plus the process timezone. The Agent Index reporter is the base's.
#
# The tag is an immutable base-<sha> naming one commit of
# plow-pbc/plow-hermes-agent, resolved to a digest, so a moving tag can never
# substitute different bytes under a running agent.
FROM public.ecr.aws/e1h7x4a2/plow-cloud-agents:base-ef0019372ff8bca593611b31ebd2e08f9f1458ff@sha256:a8a2f97ad78b8192d80a984dce81d3bf5a9a883d18cb7b677704913a09b56aee

# Which agent this is on the Agent Index. Compose sets this too, and a Plow
# cloud deploy does not: the provisioner only knows AGENT_ID for the variants
# it lists, and a self-published image is not one of them. Without it the
# base's reporter refuses to guess -- its agent-index service stands down
# on `sleep 86400` and this agent silently stops reporting usage. It is a fact
# of this variant, not a secret, so it belongs in the image; a host that sets
# its own still wins, because the container environment outranks image ENV.
ENV AGENT_ID=fandom

# Where this image comes from, who may use it, and what it is. GHCR reads the
# source label and links the package to the repository, so the Index entry,
# the code and the pinned image are one chain a stranger can walk; MIT is a
# condition of ranking on the leaderboard, and the digest is what Plow pins.
LABEL org.opencontainers.image.source="https://github.com/emanuellcoelho/fandom-hermes-agent" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.description="Your teams, your news: football, NBA, NFL and e-sports scores with a morning digest, over iMessage."

# Identity: only what is specific to this agent. plow-init composes the home's
# SOUL.md on every boot as the base persona followed by this file. Never COPY
# anything to /var/lib/hermes/SOUL.md -- the boot overwrites it.
COPY --chmod=0644 persona.md /opt/hermes/plow-seed/persona.md
COPY LICENSE NOTICE /usr/share/doc/fandom/

# Shipped at /opt/hermes/skills, outside every home, so the base runtime's
# reconcile seeds them into a home that lacks them and still reaches a home
# whose owner has not customised them. A skill the agent deleted stays
# deleted; one it edited stays edited.
COPY skills/ /opt/hermes/skills/

# Normalize whatever modes the checkout carried, preserving the executable
# bit: SKILL.md files invoke scripts, so a blanket 0644 would break them. The
# skills root itself is the base's; -mindepth 1 keeps its mode intact.
RUN find /opt/hermes/skills -mindepth 1 -type d -exec chmod 0755 {} + \
 && find /opt/hermes/skills -mindepth 1 -type f ! -perm -u+x -exec chmod 0644 {} + \
 && find /opt/hermes/skills -mindepth 1 -type f -perm -u+x -exec chmod 0755 {} +

# The process timezone, resolved from this agent's config before any service
# starts. The base sets none; every cron schedule this agent registers fires
# in whatever this leaves behind.
COPY --chmod=0755 image/cont-init.d/10-fandom-timezone /etc/cont-init.d/10-fandom-timezone

# The instance directory the skills read and onboarding writes: followed
# teams, the news cache, config. Empty until first boot; owned by the agent's
# uid.
RUN install -d -o 10000 -g 10000 -m 0700 /var/lib/hermes/fandom