# Ten Thousand Monkeys loop. No ports are exposed: the loop only runs local
# processes. One volume on /home/monkey holds the loop (LOOP_ROOT: worktrees,
# database, logs, host.env) and the harnesses' logins; a host directory may be
# mounted on /home/monkey/loop/central to see and edit the central worktrees. On
# first start the loop is created from this image's 10km (`10km create`).
#
#   docker build --build-arg AGENTS="claude kiro" -t 10km .
#   docker run -d --name myloop -e AGENT=claude -e LOOP_NAME=myloop \
#     -v myloop-home:/home/monkey 10km
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      bash ca-certificates git jq procps python3 sqlite3 tini tzdata util-linux \
 && rm -rf /var/lib/apt/lists/*

# The harnesses to install (docker/install-agent.sh; tenkm/presets.py names them).
ARG AGENTS=claude
COPY docker/install-agent.sh /usr/local/sbin/install-agent
RUN install-agent $AGENTS

RUN useradd --create-home --uid 1000 monkey \
 && mkdir -p /home/monkey/loop && chown -R monkey:monkey /home/monkey
# With its .git (full history), so loops can merge a later image's 10km.
COPY --chown=monkey:monkey . /opt/10km

USER monkey
ENV AGENTS=$AGENTS LOOP_ROOT=/home/monkey/loop \
    PATH=/home/monkey/loop/central/loop/bin:/opt/10km/bin:$PATH
VOLUME ["/home/monkey"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/10km/bin/container-start"]
