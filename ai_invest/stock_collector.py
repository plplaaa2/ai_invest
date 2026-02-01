import requests
import json
import time
import math
import os
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# --- [1. 통합 지표 및 API 설정] ---
# A. 일반 지표 (m.stock API)
MARKET_CONFIG = {
    "KOSPI": "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI",
    "NASDAQ": "https://polling.finance.naver.com/api/realtime/worldstock/index/.IXIC",
    "USD_KRW": "https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode=FX_USDKRW",
    "JPY_KRW": "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_JPYKRW&page=1",
    "DXY": "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=.DXY&page=1",
    "US_GOLD": "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=GCcv1&page=1",
    "KOR_GOLD": "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=M04020000&page=1",
    "WTI": "https://m.stock.naver.com/front-api/marketIndex/prices?category=energy&reutersCode=CLcv1&page=1",
    "NAT_GAS": "https://m.stock.naver.com/front-api/marketIndex/prices?category=energy&reutersCode=NGcv1&page=1",
    "COPPER": "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=HGcv1&page=1",
    "BTC": "https://m.stock.naver.com/front-api/crypto/otherExchange?nfTicker=BTC&excludeExchange=UPBIT",
    "KOR_RATE": "https://m.stock.naver.com/front-api/marketIndex/standardInterest?category=standardInterest&reutersCode=KOR&page=1",
    "USA_RATE": "https://m.stock.naver.com/front-api/marketIndex/standardInterest?category=standardInterest&reutersCode=USA&page=1",
    "US_2Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=US2YT%3DRR&page=1",
    "US_10Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=US10YT%3DRR&page=1",
    "KR_2Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=KR2YT%3DRR&page=1",
    "KR_10Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=KR10YT%3DRR&page=1"
}

# B. 신규 API 지표 (api.stock.naver.com - SOX, S&P500)
API_INDEX_CONFIG = {
    "SOX": "https://api.stock.naver.com/index/.SOX/price?page=1&pageSize=1",
    "SP500": "https://api.stock.naver.com/index/.INX/price?page=1&pageSize=1"
}

# C. FRED 지표 (역레포 및 물가지수)
FRED_CONFIG = {
    "RRP": "RRPONTSYD",
    "VIX": "VIXCLS",
    "US_M2": "M2SL",         # [추가] 미국 M2 광의통화 (월간, 계절조정)
    "US_GDP": "GDPC1",
    "US_GDP_NOW": "GDPNOW",
    "FED_ASSETS": "WALCL",
    "US_UNRATE": "UNRATE",
    "US_JTSJOL": "JTSJOL",
    "US_RETAIL": "RETAILIRSA",
    "US_INFL_EXP": "T10YIE",
    "US_CPI": "CPIAUCSL",
    "US_CORE_CPI": "CPILFESL",
    "US_PCE": "PCEPI",
    "US_PPI": "PPIACO"
}

# --- [2. 설정 및 DB 연결] ---
def load_hass_options():
    options_path = "/data/options.json"
    if os.path.exists(options_path):
        with open(options_path, "r") as f: return json.load(f)
    return {}

config = load_hass_options()
INFLUX_URL = config.get("influx_url", "http://192.168.1.105:8086")
INFLUX_TOKEN = config.get("influx_token", "")
INFLUX_ORG = config.get("influx_org", "home_assistant")
INFLUX_BUCKET = config.get("influx_bucket", "financial_data")

try:
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
except Exception as e:
    print(f"❌ InfluxDB 연결 실패: {e}"); write_api = None

# --- [3. 유틸리티 및 수집 함수] ---
def safe_float(v):
    if v is None or v == "" or v == "-": return 0.0
    try:
        # [수정] 숫자, 소수점(.), 그리고 마이너스(-) 기호만 남깁니다.
        clean_v = re.sub(r'[^\d.-]', '', str(v))
        return float(clean_v) if clean_v else 0.0
    except: return 0.0

def fetch_api_data(symbol, url, is_new_api=False):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        # 💡 [신규 API 통합 처리] 리스트와 딕셔너리 구조 모두 대응
        if is_new_api:
            if isinstance(data, list) and len(data) > 0:
                # SOX, SP500 처럼 리스트로 오는 경우
                item = data[0]
            elif isinstance(data, dict):
                # 환율 처럼 딕셔너리로 바로 오거나 result 안에 담겨 오는 경우
                item = data.get("result", data)
                # 만약 result 안이 리스트라면 다시 첫 번째 항목 추출
                if isinstance(item, list) and len(item) > 0:
                    item = item[0]
            else:
                return None
            
            # 가용 필드(closePrice, nowPrice, calcPrice) 중 있는 것을 선택
            price = item.get("closePrice") or item.get("nowPrice") or item.get("calcPrice")
            return {"price": safe_float(price)} if price is not None else None

        # [기존 구형 API 및 Polling API 처리]
        if symbol in ["KOSPI", "NASDAQ"]:
            if "datas" in data:
                item = data["datas"][0]
                return {"price": safe_float(item.get("closePriceRaw"))}
        elif symbol == "BTC":
            res = data.get("result", [])
            if res: return {"price": safe_float(res[0].get("tradePrice"))}
        else:
            # 일반적인 result 리스트 구조 대응
            res = data.get("result", [])
            if isinstance(res, list) and len(res) > 0:
                return {"price": safe_float(res[0].get("closePrice"))}
            elif isinstance(res, dict):
                return {"price": safe_float(res.get("closePrice") or res.get("calcPrice"))}
                
    except Exception as e:
        print(f"❌ {symbol} 수집 실패: {e}")
    return None

def fetch_fred_data(fred_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}"
    try:
        resp = requests.get(url, timeout=15)
        last_line = resp.text.strip().split('\n')[-1]
        _, val = last_line.split(',')
        return {"price": safe_float(val)} if val != '.' else None
    except: return None

def fetch_investor_trends():
    now = datetime.now()
    # 주말일 경우 가장 최근 금요일로 날짜 조정
    if now.weekday() == 5: # 토요일
        target_date = now - timedelta(days=1)
    elif now.weekday() == 6: # 일요일
        target_date = now - timedelta(days=2)
    else:
        target_date = now
    
    bizdate = target_date.strftime('%Y%m%d')
    # 💡 sosok=01 (코스피)를 명시해야 정확한 데이터가 응답됩니다.
    url = f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={bizdate}&sosok=01"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.naver.com/sise/investor.naver"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'euc-kr'
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 💡 'type_1' 클래스를 가진 테이블의 모든 행(tr)을 탐색합니다.
        rows = soup.select('table.type_1 tr')
        for row in rows:
            cols = row.select('td')
            # 데이터가 있는 행은 보통 9개 이상의 열(td)을 가집니다.
            if len(cols) >= 4:
                # 첫 번째 열에 날짜(.)가 포함되어 있는지 확인하여 유효 행 판별
                date_text = cols[0].get_text(strip=True)
                if '.' in date_text:
                    return {
                        "KOR_NET_IND": {"price": safe_float(cols[1].get_text(strip=True))},   # 개인
                        "KOR_NET_FOR": {"price": safe_float(cols[2].get_text(strip=True))},   # 외국인
                        "KOR_NET_INST": {"price": safe_float(cols[3].get_text(strip=True))}   # 기관
                    }
        print(f"⚠️ {bizdate} 날짜의 데이터를 테이블에서 찾지 못했습니다.")
    except Exception as e:
        print(f"❌ 투자자 동향 파싱 에러: {e}")
    return None
    
def fetch_market_funds():
    try:
        resp = requests.get("https://finance.naver.com/sise/sise_deposit.naver", timeout=10)
        resp.encoding = 'euc-kr'
        soup = BeautifulSoup(resp.text, 'html.parser')
        data_row = soup.find('td', class_='date').parent
        cells = data_row.find_all('td')
        return {
            "KOR_DEPOSIT": {"price": safe_float(cells[1].text)},
            "KOR_CREDIT_LOAN": {"price": safe_float(cells[3].text)}
        }
    except: return None

def is_different(old_val, new_val):
    if old_val is None: return True
    return not math.isclose(old_val, new_val, rel_tol=1e-5)

def save_to_influx(symbol, data, current_time):
    point = Point("financial_metrics").tag("symbol", symbol)
    for field, value in data.items():
        point.field(field, float(value))
    point.time(current_time)
    if write_api:
        try:
            write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            return True
        except: return False
    return False

# --- [4. 메인 실행 루프] ---
if __name__ == "__main__":
    last_prices = {} 
    print(f"🚀 [AI Analyst V3] 통합 수집기 가동 시작")

    while True:
        current_time = datetime.utcnow()
        to_process = []

        # A. 일반 API 수집
        for sym, url in MARKET_CONFIG.items():
            res = fetch_api_data(sym, url)
            if res: to_process.append((sym, res))

        # B. 신규 API 지수 수집 (SOX, SP500)
        for sym, url in API_INDEX_CONFIG.items():
            res = fetch_api_data(sym, url, is_new_api=True)
            if res: to_process.append((sym, res))

        # C. FRED 수집 (물가, 역레포)
        for sym, f_id in FRED_CONFIG.items():
            res = fetch_fred_data(f_id)
            if res: to_process.append((sym, res))

        # D. 수급 및 자금 수집
        trends = fetch_investor_trends()
        if trends: 
            for sym, val in trends.items(): to_process.append((sym, val))
        
        funds = fetch_market_funds()
        if funds:
            for sym, val in funds.items(): to_process.append((sym, val))

        # --- 중복 체크 및 저장 ---
        updated_count = 0
        for symbol, data in to_process:
            new_price = data.get("price")
            old_price = last_prices.get(symbol)

            if is_different(old_price, new_price):
                if save_to_influx(symbol, data, current_time):
                    last_prices[symbol] = new_price
                    updated_count += 1
        
        print(f"✅ {datetime.now().strftime('%H:%M:%S')} | 업데이트: {updated_count}건 | 대기중...")
        time.sleep(600)