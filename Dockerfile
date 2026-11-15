# Ten Thousand Monkeys loop. No ports are exposed: the loop only runs local
# processes. Mount a host directory on /loop/central, so the central worktrees
# (the loop repo and the project repos) live on the host, and a volume on /data
# for the database. On first start the loop repo is created from this image.
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      bash ca-certificates git jq procps python3 sqlite3 tini tzdata util-linux \
 && rm -rf /var/lib/apt/lists/*

# Install the agent harnesses you use, for example:
# RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
#  && npm install -g @anthropic-ai/claude-code && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 monkey \
 && mkdir -p /loop/central /data && chown -R monkey:monkey /loop /data
COPY --chown=monkey:monkey . /opt/10km

USER monkey
ENV LOOP_ROOT=/loop MSM_DB=/data/loop.db PATH=/loop/central/loop/bin:/opt/10km/bin:$PATH
VOLUME ["/loop/central", "/data"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/10km/bin/container-start"]
