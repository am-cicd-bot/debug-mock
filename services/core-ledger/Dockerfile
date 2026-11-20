FROM python:3.12-slim

WORKDIR /srv/core-ledger
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
ENV CORE_LEDGER_DB=/data/core_ledger.db
ENV PORT=8081
RUN mkdir -p /data

EXPOSE 8081
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
