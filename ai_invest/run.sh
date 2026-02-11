#!/usr/bin/env bash
echo "🚀 AI Analyst 통합 서비스를 시작합니다..."
cd /app

# 0. 필수 패키지 설치 (추가) [cite: 2026-02-04]
echo "📦 필요한 라이브러리를 점검합니다..."
if ! python3 -c "import fpdf2" &> /dev/null; then
    echo "📦 fpdf2 설치 중..."
    pip install --no-cache-dir fpdf2
fi

# pykrx 설치 확인 (설치되어 있지 않은 경우에만 진행)
if ! python3 -c "import pykrx" &> /dev/null; then
    echo "📦 pykrx 설치 중..."
    pip install --no-cache-dir pykrx
fi

echo "폰트 정비 중..."
mkdir -p /app/fonts
# 🎯 curl 대신 python을 사용하여 나눔고딕 다운로드
if [ ! -f "/app/fonts/NanumGothic.ttf" ]; then
    python3 -c "import urllib.request; urllib.request.urlretrieve('https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf', '/app/fonts/NanumGothic.ttf')"
    echo "✅ 나눔고딕 다운로드 완료"
fi

# 1. RSS 수집기 실행 (-u 옵션 추가)
python3 -u /app/scraper.py &

# 2. 주가 지수 수집기 실행 (-u 옵션 추가)
python3 -u /app/stock_collector.py &

# 3. Streamlit 웹 UI 실행
python3 -m streamlit run /app/app.py \
    --server.port 8502 \
    --server.address 0.0.0.0