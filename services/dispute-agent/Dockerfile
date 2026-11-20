FROM python:3.12-slim

WORKDIR /srv/dispute-agent
COPY services/dispute-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY policies /srv/policies
COPY services/dispute-agent/app ./app

ENV POLICIES_DIR=/srv/policies
ENV DISPUTE_DB_PATH=/data/disputes.db
ENV CORE_LEDGER_URL=http://core-ledger:8081
ENV PORT=8080
RUN mkdir -p /data

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
