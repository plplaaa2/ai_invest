FROM python:3.11-slim-bullseye

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    streamlit \
    feedparser \
    requests \
    beautifulsoup4 \
    lxml

WORKDIR /app
COPY . .

RUN chmod a+x /app/run.sh
EXPOSE 8501
CMD [ "/app/run.sh" ]