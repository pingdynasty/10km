# Ten Thousand Monkeys loop. No ports are exposed: the loop only runs local
# processes. Mount /loop (worktrees) and /data (database) as volumes.
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      bash ca-certificates git jq procps python3 sqlite3 tini tzdata util-linux \
 && rm -rf /var/lib/apt/lists/*

# Install the agent harnesses you use, for example:
# RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
#  && npm install -g @anthropic-ai/claude-code && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 monkey \
 && mkdir -p /loop /data && chown monkey:monkey /loop /data
COPY --chown=monkey:monkey . /opt/10km

USER monkey
ENV LOOP_ROOT=/loop MSM_DB=/data/loop.db PATH=/opt/10km/bin:$PATH \
    GIT_AUTHOR_NAME=monkey GIT_AUTHOR_EMAIL=monkey@localhost \
    GIT_COMMITTER_NAME=monkey GIT_COMMITTER_EMAIL=monkey@localhost
VOLUME ["/loop", "/data"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/10km/bin/run-loop"]
