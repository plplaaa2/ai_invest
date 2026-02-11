FROM python:3.11-slim-bullseye

# 시스템 라이브러리 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 라이브러리 설치 (lxml을 반드시 포함해야 합니다)
RUN pip install --no-cache-dir \
    streamlit \
    feedparser \
    requests \
    beautifulsoup4 \
    lxml \
    influxdb-client

WORKDIR /app
COPY . .

RUN chmod a+x /app/run.sh

# Streamlit 기본 포트 개방
EXPOSE 8501

CMD [ "/app/run.sh" ]