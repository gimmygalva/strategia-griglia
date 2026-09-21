FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 WEB_MODE=1 PORT=8080 DATA_DIR=/data
WORKDIR /app
COPY chunk-* /tmp/
RUN cat /tmp/chunk-* > /tmp/jevbot-source.tar.gz.b64 \
    && base64 -d /tmp/jevbot-source.tar.gz.b64 > /tmp/jevbot-source.tar.gz \
    && tar -xzf /tmp/jevbot-source.tar.gz -C /app \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && rm -f /tmp/chunk-* /tmp/jevbot-source.tar.gz*
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "/app/app/app_server.py"]
