# CloakBrowser on AWS Lambda — derived from the official CloakHQ image.
#
# `FROM cloakhq/cloakbrowser:<tag>` is an official distribution channel under
# the CloakBrowser Binary License — pulling it isn't redistribution. We just
# layer Lambda glue on top: the Lambda Runtime Interface Client (awslambdaric),
# the Lambda Runtime Interface Emulator (for local `docker run` testing), the
# dual-mode entrypoint, and the handler module.
#
# This directory is self-contained — copy/clone it anywhere and build from
# inside it. No files outside this directory are referenced.
#
# ─── Lambda invocation (default CMD) ──────────────────────────────────────────
#   # From inside this directory:
#   docker buildx build --platform linux/arm64 -t cloakbrowser-lambda:arm64 --load .
#
#   # Or from a parent dir, pointing at this directory as the build context:
#   docker buildx build --platform linux/arm64 \
#     -f path/to/aws_lambda/Dockerfile -t cloakbrowser-lambda:arm64 --load \
#     path/to/aws_lambda
#
#   docker run --rm -p 9000:8080 cloakbrowser-lambda:arm64
#   curl -XPOST http://localhost:9000/2015-03-31/functions/function/invocations \
#     -d '{"url":"https://example.com"}'
#
# ─── Same as the canonical CloakHQ image (CMD overridden) ─────────────────────
#   docker run --rm -it cloakbrowser-lambda:arm64 python                          # REPL
#   docker run --rm cloakbrowser-lambda:arm64 python examples/basic.py            # examples
#   docker run --rm -p 9222:9222 cloakbrowser-lambda:arm64 cloakserve --port=9222 # CDP server
#   docker run --rm cloakbrowser-lambda:arm64 cloaktest                           # stealth tests
#   docker run --rm -it cloakbrowser-lambda:arm64 node                            # JS wrapper
#   docker run --rm -it cloakbrowser-lambda:arm64 bash                            # shell
#
# Pin a specific tag (e.g. cloakhq/cloakbrowser:0.3.25) for reproducible builds;
# `latest` floats with CloakHQ's release cadence.

FROM cloakhq/cloakbrowser:latest

# ─── Lambda Runtime Interface Client ──────────────────────────────────────────
RUN pip install --no-cache-dir awslambdaric

# ─── Lambda Runtime Interface Emulator (local `docker run` testing) ───────────
# Bundled into the image so users can hit the standard local-invoke endpoint
# without mounting the RIE separately. TARGETARCH is provided by buildx.
ARG TARGETARCH
ADD https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/latest/download/aws-lambda-rie-${TARGETARCH} \
    /usr/local/bin/aws-lambda-rie
RUN chmod +x /usr/local/bin/aws-lambda-rie

# ─── Lambda glue ──────────────────────────────────────────────────────────────
# Dual-mode entrypoint replaces the canonical bin/docker-entrypoint.sh: same
# Xvfb startup, plus routing for `module.func` CMDs through awslambdaric.
COPY lambda-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Handler sits at /app (already on Python's import path in the canonical image,
# WORKDIR=/app), imports cloakbrowser as a normal library.
COPY lambda_handler.py /app/lambda_handler.py

# ─── Lambda non-root readability fix ──────────────────────────────────────────
# The canonical image bakes the Chromium binary at /root/.cloakbrowser/ (root's
# HOME at build time). Lambda runs the container as a non-root user that can't
# read /root by default (mode 750). Make the whole binary tree world-readable
# and traversable. Also restore the .welcome_shown marker the canonical image
# rm's (Lambda's read-only runtime FS can't recreate it, so the welcome would
# print to CloudWatch on every cold start otherwise).
RUN touch /root/.cloakbrowser/.welcome_shown \
    && chmod -R o+rX /root /root/.cloakbrowser

# ─── Lambda runtime env ───────────────────────────────────────────────────────
# HOME=/tmp gives Chromium a writable scratch dir (Lambda only allows writes
# under /tmp). CLOAKBROWSER_CACHE_DIR points at the baked binary location since
# HOME=/tmp would otherwise make get_cache_dir() resolve to /tmp/.cloakbrowser
# (empty). Auto-update is disabled because the runtime FS is read-only.
ENV HOME=/tmp \
    CLOAKBROWSER_CACHE_DIR=/root/.cloakbrowser \
    CLOAKBROWSER_AUTO_UPDATE=false

ENTRYPOINT ["/entrypoint.sh"]
CMD ["lambda_handler.handler"]
