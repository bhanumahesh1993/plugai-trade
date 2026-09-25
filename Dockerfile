# PlugAI-Trade — docker run -p 8501:8501 -v plugai-data:/data ghcr.io/bhanumahesh1993/plugai-trade
FROM python:3.12-slim
ENV PLUGAI_TRADE_HOME=/data \
    PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=http://host.docker.internal:11434
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[yahoo]" keyrings.alt
# Containers have no OS keychain: keys go to a keyring file inside the /data volume.
ENV PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring \
    XDG_DATA_HOME=/data/keyring
VOLUME ["/data"]
EXPOSE 8501
CMD ["plugai-trade", "start", "--headless"]
