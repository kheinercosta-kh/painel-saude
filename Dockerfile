FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sync_garmin.py .
RUN mkdir -p /data/garmin-token
ENV GARMIN_TOKEN_DIR=/data/garmin-token

CMD ["python", "sync_garmin.py", "--dias", "3"]
