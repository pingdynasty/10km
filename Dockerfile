# Ten Thousand Monkeys loop. No ports are exposed: the loop only runs local
# processes. One volume on /home/monkey holds the loop (LOOP_ROOT: worktrees,
# database, logs, host.env), the harness and its login; a host directory may be
# mounted on /home/monkey/loop/central to see and edit the central worktrees. On
# start the harness AGENT names is installed in the volume if it isn't there
# (docker/install-agent.sh), and on first start the loop is created from this
# image's 10km (`10km create`). The image ships pi (MIT); the others are
# downloaded under their own licences.
#
#   docker build -t 10km .
#   docker run -d --name myloop -e AGENT=claude -e LOOP_NAME=myloop \
#     -v myloop-home:/home/monkey 10km
FROM node:22-bookworm-slim

# curl and unzip for the harness installers, libatomic1 for hermes's Node,
# ripgrep and fd for the harnesses' searches (or pi downloads them).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      bash ca-certificates curl fd-find git jq libatomic1 procps python3 ripgrep \
      sqlite3 tini tzdata unzip util-linux \
 && ln -s /usr/bin/fdfind /usr/local/bin/fd \
 && rm -rf /var/lib/apt/lists/*

# pi system-wide, so a new image brings a new version.
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent \
 && npm cache clean --force

# The node image's user has uid 1000: make way for monkey.
RUN userdel --remove node \
 && useradd --create-home --uid 1000 monkey \
 && mkdir -p /home/monkey/loop && chown -R monkey:monkey /home/monkey
# With its .git (full history), so loops can merge a later image's 10km.
COPY --chown=monkey:monkey . /opt/10km

USER monkey
ENV LOOP_ROOT=/home/monkey/loop \
    PATH=/home/monkey/loop/central/loop/bin:/opt/10km/bin:/home/monkey/.local/bin:$PATH
VOLUME ["/home/monkey"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/10km/bin/container-start"]
