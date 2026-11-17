# LiveTeach backend: API + admin panel (/admin) + teacher panel (/teacher-panel)
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
# libatomic1: the PDF engine's installer needs it before it can install anything else
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY . .
# demo hosting keeps data in /tmp (wiped on restart); a real server sets DATABASE_PATH etc. to a lasting disk
ENV DATABASE_PATH=/tmp/liveteach.db NOTES_DIR=/tmp/notes AVATAR_DIR=/tmp/avatars PYTHONUNBUFFERED=1
CMD python seed.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'
