from common import *

STANDARD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.naver.com/"
}

# --- [4. 데이터 수집 핵심 함수] ---
def fetch_api_data(symbol, url):
    """지수 및 일반 API 수집 (하이픈 데이터 및 리스트 구조 대응)"""
    try:
        resp = requests.get(url, headers=STANDARD_HEADERS, timeout=10)
        data = resp.json()
        item = None
        
        # 1. 데이터 소스(List/Dict) 결정
        if "datas" in data and len(data["datas"]) > 0:
            res_list = data["datas"]
        elif "result" in data:
            res_list = data["result"]
        elif isinstance(data, list):
            res_list = data
        else:
            res_list = []

        # 2. 리스트인 경우, 유효한 숫자 데이터가 나올 때까지 탐색 (KOR_RATE 대응)
        if isinstance(res_list, list):
            for entry in res_list:
                # 후보 키들 확인
                val = entry.get("closePrice") or entry.get("nowPrice") or entry.get("tradePrice") or entry.get("currentValue")
                # "-"가 아니고 데이터가 존재하면 선택
                if val and str(val).strip() != "-":
                    item = entry
                    break
        else:
            # 단일 딕셔너리 객체인 경우
            item = res_list

        if item:
            # 우선순위: closePrice(금리) -> nowPrice(국내) -> tradePrice(해외) 순
            price_val = item.get("closePrice") or item.get("nowPrice") or item.get("tradePrice") or item.get("currentValue") or item.get("closePriceRaw")
            
            # 가격 데이터가 하이픈이 아니고 존재할 때만 리턴
            if price_val and str(price_val).strip() != "-": 
                return {
                    "price": safe_float(price_val),
                    "volume": safe_float(item.get("accumulatedTradingVolume") or item.get("volume") or item.get("accumulatedTradingVolumeRaw") or 0),
                    "value": safe_float(item.get("accumulatedTradingValue") or item.get("tradingValue") or item.get("accumulatedTradingValueRaw") or 0)
                }
    except Exception as e:
        # print(f"❌ {symbol} 수집 에러: {e}") # 필요시 주석 해제하여 디버깅
        pass
    return None

def fetch_naver_table(symbol, url):
    """환율 HTML 테이블 파싱"""
    try:
        resp = requests.get(url, headers=STANDARD_HEADERS, timeout=10)
        resp.encoding = 'euc-kr'
        soup = BeautifulSoup(resp.text, "html.parser")
        row = soup.select_one('table.tbl_exchange tbody tr')
        if row:
            price = safe_float(row.select('td')[1].text)
            return {"price": price}
    except: return None

from datetime import datetime, timezone # 최상단에 반드시 필요

def fetch_fred_keyless(symbol, series_id):
    """DB 상태에 따라 [전체 복구] 또는 [최신 업데이트]를 자동으로 결정합니다."""
    try:
        # 1. DB에 해당 심볼의 데이터가 이미 있는지 확인
        check_query = f'''
            from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -10y)
            |> filter(fn: (r) => r.symbol == "{symbol}")
            |> last()
        '''
        existing_data = query_api.query(check_query)
        is_empty = len(existing_data) == 0

        # 2. FRED에서 전체 CSV 로드
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        resp = requests.get(url, timeout=15)
        if "<html" in resp.text.lower(): return None

        lines = resp.text.strip().split('\n')[1:] 
        points = []
        
        for line in lines:
            parts = line.split(',')
            if len(parts) < 2 or parts[1] == ".": continue
            
            dt_obj = datetime.strptime(parts[0], '%Y-%m-%d').replace(tzinfo=timezone.utc)
            val = safe_float(parts[1])
            
            p = Point("financial_metrics").tag("symbol", symbol).field("price", val).time(dt_obj, WritePrecision.S)
            points.append(p)
        
        if points:
            if is_empty:
                # 🚀 데이터가 아예 없으면 전체 복구 (최초 1회 실행)
                write_api.write(bucket=INFLUX_BUCKET, record=points)
                print(f"📊 {symbol}: 데이터가 비어있어 과거 {len(points)}건을 전체 복구했습니다.")
            else:
                # ⚡ 데이터가 이미 있으면 최신 1건만 업데이트
                write_api.write(bucket=INFLUX_BUCKET, record=points[-1])
            
            return {"price": points[-1]._fields['price']}
            
    except Exception as e:
        print(f"❌ FRED 수집 실패 ({symbol}): {e}")
        return None
        
def fetch_investor_trends():
    try:
        today_str = get_now_kst().strftime('%Y%m%d')
        url = f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={today_str}&sosok="
        
        resp = requests.get(url, headers=STANDARD_HEADERS, timeout=10)
        resp.encoding = 'euc-kr' 
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 🛡️ 모든 tr 중 데이터가 있는 tr만 필터링합니다.
        trs = soup.select('table.type_1 tr')
        valid_data = None
        
        for tr in trs:
            cols = tr.find_all('td')
            # 첫 번째 td가 날짜 형식(XX.XX)이고 데이터가 충분한 줄을 찾습니다.
            if len(cols) >= 4 and '.' in cols[0].text:
                valid_data = cols
                break
        
        if not valid_data:
            print("⚠️ 유효한 데이터 줄을 찾지 못했습니다.")
            return None

        # 🎯 데이터 추출 (콤마 제거 및 공백 제거 필수)
        def clean_val(text):
            return float(text.replace(',', '').strip())

        res = {
            "KOR_NET_IND": {"price": clean_val(valid_data[1].text)}, # 개인
            "KOR_NET_FOR": {"price": clean_val(valid_data[2].text)}, # 외국인
            "KOR_NET_INST": {"price": clean_val(valid_data[3].text)} # 기관
        }
        
        return res
        
    except Exception as e:
        print(f"❌ 수급 수집 에러: {e}")
        return None

def fetch_market_funds():
    """예탁금/신용잔고 수집 복구"""
    try:
        resp = requests.get("https://finance.naver.com/sise/sise_deposit.naver", timeout=10); resp.encoding = 'euc-kr'
        tds = BeautifulSoup(resp.text, 'html.parser').find('td', class_='date').parent.find_all('td')
        return {"KOR_DEPOSIT": {"price": safe_float(tds[1].text)}, "KOR_CREDIT_LOAN": {"price": safe_float(tds[3].text)}}
    except: return None
    

def generate_auto_report(config_data, r_type="daily"):
    """
    [KST 및 JSON 대응 통합 보고서 엔진]
    """
    # 🎯 0. 기초 데이터 및 안전장치 확인
    if not os.path.exists(CONFIG_PATH):
        print(f"⏳ [대기] 설정 파일({CONFIG_PATH})이 없습니다.")
        return False

    try:
        # 🚀 common.py의 통합 리포트 생성 함수 호출
        report_content = generate_market_report(r_type, config_data)
        
        if report_content.startswith("❌"):
             raise Exception(report_content)
        
        # 사령관님의 save_report_to_file을 통해 폴더 분류 및 퍼지 실행
        save_report_to_file(report_content, r_type)
        print(f"[{get_now_kst()}] 🏛️ {r_type.upper()} 보고서 생성 완료")
        return True
    except Exception as e:
        print(f"🚨 [{r_type}] 생성 중단 원인: {str(e)}")
        return False


# --- [5. 메인 루프] ---
if __name__ == "__main__":
    last_prices = {} 
    last_collect_time = 0
    last_news_time = 0
    last_fred_time = 0 
    last_auto_report_date = ""
    last_weekly_report_date = "" 
    last_monthly_report_date = ""

    # 초기 설정 로드 (data 변수 에러 방지용)
    initial_config = load_data()
    print(f"🚀 [AI Analyst] 시스템 가동 - 기준 시각: {initial_config.get('report_gen_time', '08:00')} (KST)")

    while True:
        try:
            # 🎯 1. 기본 시각 및 설정 업데이트
            now_kst = get_now_kst()
            current_ts = time.time()
            current_config = load_data() 
            
            base_time_str = str(current_config.get("report_gen_time", "08:00")).strip()
            base_time = datetime.strptime(base_time_str, "%H:%M")
            
            # 순차 실행 시각 계산
            weekly_time_str = (base_time + timedelta(minutes=10)).strftime("%H:%M")
            monthly_time_str = (base_time + timedelta(minutes=20)).strftime("%H:%M")
            
            current_time_str = now_kst.strftime("%H:%M")
            auto_gen_enabled = current_config.get("report_auto_gen", False)

            # ---------------------------------------------------------
            # 🤖 [T1: 자동 보고서 생성 섹션]
            # ---------------------------------------------------------
            if auto_gen_enabled:
                # ① 일간 보고서 (매일)
                if current_time_str == base_time_str:
                    if last_auto_report_date != now_kst.strftime("%Y-%m-%d"):
                        print(f"🤖 [{now_kst.strftime('%H:%M:%S')}] (1/3) 일간 보고서 생성...")
                        if generate_auto_report(current_config, r_type="daily"):
                            last_auto_report_date = now_kst.strftime("%Y-%m-%d")

                # ② 주간 보고서 (일요일)
                elif current_time_str == weekly_time_str and now_kst.weekday() == 6:
                    daily_dir = os.path.join(REPORT_DIR, "01_daily")
                    daily_files = [f for f in os.listdir(daily_dir) if f.endswith(".txt") and f != "latest.txt"]
                    
                    if len(daily_files) >= 7:
                        current_week = now_kst.strftime("%Y-%U")
                        if last_weekly_report_date != current_week:
                            print(f"📅 [{now_kst.strftime('%H:%M:%S')}] (2/3) 주간 결산 리포트 생성...")
                            if generate_auto_report(current_config, r_type="weekly"):
                                last_weekly_report_date = current_week
                    else:
                        print(f"⚠️ 주간 리포트 스킵: 데이터 부족 ({len(daily_files)}/7)")

                # ③ 월간 보고서 (매월 1일)
                elif current_time_str == monthly_time_str and now_kst.day == 1:
                    daily_dir = os.path.join(REPORT_DIR, "01_daily")
                    daily_files = [f for f in os.listdir(daily_dir) if f.endswith(".txt") and f != "latest.txt"]
                    
                    if len(daily_files) >= 20:
                        current_month = now_kst.strftime("%Y-%m")
                        if last_monthly_report_date != current_month:
                            print(f"🏛️ [{now_kst.strftime('%H:%M:%S')}] (3/3) 월간 결산 리포트 생성...")
                            if generate_auto_report(current_config, r_type="monthly"):
                                last_monthly_report_date = current_month
                    else:
                        print(f"⚠️ 월간 리포트 스킵: 데이터 부족 ({len(daily_files)}/20)")

            # ---------------------------------------------------------
            # 📊 [T2: 실시간 지표 수집 (10분 주기)]
            # ---------------------------------------------------------
            if current_ts - last_collect_time >= 600:
                for sym, url in MARKET_CONFIG.items():
                    res = fetch_api_data(sym, url)
                    if res and res.get('price', 0) > 0: last_prices[sym] = res
                
                for sym, url in TABLE_CONFIG.items():
                    res = fetch_naver_table(sym, url)
                    if res: last_prices[sym] = res

                trends = fetch_investor_trends()
                if trends: last_prices.update(trends)
                funds = fetch_market_funds()
                if funds: last_prices.update(funds)

                updated = 0
                for sym, p_data in last_prices.items():
                    if sym not in FRED_CONFIG:
                        if save_to_influx(sym, p_data, now_kst): updated += 1
                
                print(f"📊 {now_kst.strftime('%H:%M:%S')} | 지표 갱신: {updated}건")
                last_collect_time = current_ts

            # ---------------------------------------------------------
            # 🏛️ [T4: FRED 매크로 지표 수집 (1시간 주기)]
            # ---------------------------------------------------------
            if current_ts - last_fred_time >= 3600:
                print(f"🏛️ {now_kst.strftime('%H:%M:%S')} | FRED 매크로 수집...")
                fred_updated = 0
                for sym, sid in FRED_CONFIG.items():
                    res = fetch_fred_keyless(sym, sid)
                    if res:
                        last_prices[sym] = res
                        if save_to_influx(sym, res, now_kst): fred_updated += 1
                print(f"✅ FRED 갱신 완료: {fred_updated}건")
                last_fred_time = current_ts
                
        except Exception as e: 
            print(f"❌ 루프 메인 에러: {e}")
            
        # 루프 과열 방지
        time.sleep(60)