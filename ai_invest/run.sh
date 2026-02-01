#!/usr/bin/env bash
echo "🚀 AI Analyst 통합 서비스를 시작합니다..."
cd /app

# 1. RSS 수집기 실행 (-u 옵션 추가)
python3 -u /app/scraper.py &

# 3. Streamlit 웹 UI 실행
python3 -m streamlit run /app/app.py \
    --server.port 8501 \
    --server.address 0.0.0.0