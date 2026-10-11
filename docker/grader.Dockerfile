# The grading image (D-092). Student code is imported by the hidden tests INSIDE a container built
# from this file; the host only reads the JUnit report that comes back.
#
#   build (from the project folder, needs network once). The build context is the docker/ folder
#   ONLY, so .env, backups/ and the rest of the repository are never sent to the Docker daemon:
#       docker build -f docker/grader.Dockerfile -t vdel-grader:1 docker
#   switch the grader to it:
#       $env:VDEL_GRADING_SANDBOX = "docker"      (PowerShell; unset it to go back)
#
# Nothing secret is in the image or its build context: no .env, no token, no database client.
# It is run by assessment/test_runner.py with --network none, --read-only, a tmpfs scratch, a pids,
# memory and cpu limit, --cap-drop ALL and no-new-privileges; see docs/OPERATIONS.md section 11.

# python:3.11-slim as pulled on 2026-10-11T19:05:28Z (Python 3.11.17, linux/amd64), pinned by digest
# so a rebuild cannot drift. 3.11 is the version CLAUDE.md names and the one the generated CI uses.
FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY grader-requirements.txt /tmp/grader-requirements.txt
RUN pip install -r /tmp/grader-requirements.txt && rm /tmp/grader-requirements.txt

# A user that owns nothing: no home directory, no shell. The runner also passes --user 10001:10001.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin grader
USER 10001:10001
WORKDIR /work

LABEL org.opencontainers.image.title="vdel-grader" \
      org.opencontainers.image.description="Runs VDEL hidden tests against student code; no network, no secrets"
