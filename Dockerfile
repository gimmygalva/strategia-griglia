FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 WEB_MODE=1 PORT=8080 DATA_DIR=/data
WORKDIR /app
COPY jevbot-bundle/chunk-* /tmp/
COPY jevbot-bundle/app_server.py.gz.b64 /tmp/app_server.py.gz.b64
RUN cat /tmp/chunk-* > /tmp/jevbot-source.tar.gz.b64 \
    && base64 -d /tmp/jevbot-source.tar.gz.b64 > /tmp/jevbot-source.tar.gz \
    && tar -xzf /tmp/jevbot-source.tar.gz -C /app \
    && base64 -d /tmp/app_server.py.gz.b64 | gzip -d > /app/app/app_server.py \
    && echo "347e9cfd907bebb63927fb33f664f1765e6652ef66b70953a7f8fea8fa65f1dd  /app/app/app_server.py" | sha256sum -c - \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && rm -f /tmp/chunk-* /tmp/jevbot-source.tar.gz* /tmp/app_server.py.gz.b64
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "/app/app/app_server.py"]
