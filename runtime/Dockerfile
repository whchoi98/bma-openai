FROM public.ecr.aws/docker/library/python:3.12-slim

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /home/app/workspace /opt/bma/bin \
    && chown -R app:app /home/app
WORKDIR /opt/bma
COPY runtime/requirements.txt /opt/bma/requirements.txt
RUN python -m venv /opt/bma/venv \
    && /opt/bma/venv/bin/pip install --no-cache-dir -r /opt/bma/requirements.txt
COPY --chmod=0555 runtime/bin/codex /opt/bma/bin/codex
COPY --chmod=0444 runtime/lifecycle/server.py /opt/bma/lifecycle/server.py
COPY --chmod=0444 runtime/mcp_bridge.py /opt/bma/mcp_bridge.py
COPY --chmod=0444 runtime/LICENSE-AGENTCORE /opt/bma/licenses/LICENSE-AGENTCORE
COPY aws_inventory /opt/bma/aws_inventory
COPY skills /opt/bma/skills
RUN chmod -R a+rX /opt/bma && chmod -R go-w /opt/bma
ENV APP_REGION=us-east-1 TARGET_REGION=ap-northeast-2 AWS_REGION=us-east-1 \
    BMA_HOME_DIR=/home/app BMA_CODEX_HOME=/home/app/.codex \
    BMA_CODEX_BINARY=/opt/bma/bin/codex AGENT_OBSERVABILITY_ENABLED=false \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER app
EXPOSE 8080
CMD ["/opt/bma/venv/bin/python", "-u", "/opt/bma/mcp_bridge.py"]
