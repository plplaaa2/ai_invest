import json
import os
import re
import requests
import time
import math
import feedparser
from constants import *
from datetime import datetime, timedelta, date, timezone
from bs4 import BeautifulSoup
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

try:
    from pykrx import stock
    HAS_PYKRX = True
except ImportError:
    HAS_PYKRX = False


KST = timezone(timedelta(hours=9))

def get_now_kst():
    """현재 한국 시간을 반환합니다."""
    return datetime.now(KST)

# --- [0. 시스템 공통 경로 설정] ---
OPTIONS_PATH = "/data/options.json"
BASE_PATH = "/share/local_ai_analyst"
CONFIG_PATH = os.path.join(BASE_PATH, "rss_config.json")
PENDING_PATH = os.path.join(BASE_PATH, "pending")
REPORT_DIR = os.path.join(BASE_PATH, "reports")

def load_addon_config():
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, "r", encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

config = load_addon_config() 


# 지표 관련 변수 (HA Addon 구성에서 로드)
INFLUX_URL = config.get("influx_url", "http://192.168.1.105:8086")
INFLUX_TOKEN = config.get("influx_token", "")
INFLUX_ORG = "home_assistant"
INFLUX_BUCKET = "financial_data"

client = None
write_api = None
query_api = None

print(f"✅ InfluxDB 설정 로드 완료: {INFLUX_URL}")

if INFLUX_TOKEN:
    try:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        write_api = client.write_api(write_options=SYNCHRONOUS)
        query_api = client.query_api()
        print(f"✅ InfluxDB 연결 성공: {INFLUX_URL}")
    except Exception as e:
        print(f"❌ InfluxDB 연결 실패: {e}")


# 키가 있는지 확인하는 로직
openai_key = config.get("openai_api_key", "")
gemini_key = config.get("gemini_api_key", "")
headers = {"Content-Type": "application/json"}

# 🎯 2. Cloud LLM 모드 판정 로직 보완
if openai_key or gemini_key:
    if openai_key:
        headers["Authorization"] = f"Bearer {openai_key}"
    print(f"🚀 Cloud LLM 모드로 작동합니다. (OpenAI: {'OK' if openai_key else 'NO'}, Gemini: {'OK' if gemini_key else 'NO'})")
else:
    print("🏠 Local LLM 모드로 작동합니다 (API 키 없음).")
        

# --- [3. 유틸리티 함수] ---
def safe_float(v):
    if v is None or v == "" or v == "-": return 0.0
    try:
        clean_v = re.sub(r'[^\d.-]', '', str(v))
        return float(clean_v) if clean_v else 0.0
    except: return 0.0

def save_to_influx(symbol, data, current_time):
    point = Point("financial_metrics").tag("symbol", symbol)
    for f, v in data.items(): point.field(f, float(v))
    point.time(current_time)
    if write_api:
        try:
            write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
            return True
        except Exception as e:
            print(f"⚠️ InfluxDB 쓰기 에러 ({symbol}): {e}")
    return False
    
def save_report_to_file(content, section_name):
    # 1. 경로 설정 및 폴더 세분화
    base_dir = REPORT_DIR
    dir_map = {
        'daily': '01_daily', 'weekly': '02_weekly', 
        'monthly': '03_monthly', 'yearly': '04_yearly'
    }
    # section_name이 맵에 없으면 기본 폴더 사용
    subdir = dir_map.get(section_name.lower(), "05_etc")
    report_dir = os.path.join(base_dir, subdir)
    os.makedirs(report_dir, exist_ok=True)
    
    # 2. 파일명 생성 및 저장 (기록용)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"{timestamp}_{section_name.replace(' ', '_')}.txt"
    filepath = os.path.join(report_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    # 3. 🎯 AI 참조용 Latest 파일 갱신 (고정 경로)
    latest_path = os.path.join(report_dir, "latest.txt")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(content)

    # 4. 🧹 계층형 자동 정제 (Purge) 로직
    # 규칙: Daily(7일), Weekly(30일), Monthly(365일) 보관
    purge_rules = {'01_daily': 9, '02_weekly': 35, '03_monthly': 370}
    if subdir in purge_rules:
        limit_days = purge_rules[subdir]
        threshold = time.time() - (limit_days * 86400)
        for f in os.listdir(report_dir):
            if f == "latest.txt": continue # 최신 맥락은 보호
            f_p = os.path.join(report_dir, f)
            if os.path.isfile(f_p) and os.path.getmtime(f_p) < threshold:
                os.remove(f_p)
                
    return filepath
    
def load_historical_contexts():
    """파일이 없어도 에러 없이 작동하며, AI에게 현재 상황을 설명합니다."""
    base_dir = REPORT_DIR
    
    # 1. 최근 3일간의 일간 리포트 로드 (DAILY_LOG 확장)
    daily_context = ""
    daily_dir = os.path.join(base_dir, '01_daily')
    
    if os.path.exists(daily_dir):
        # latest.txt 제외하고 날짜 역순 정렬
        files = sorted([f for f in os.listdir(daily_dir) if f.endswith(".txt") and f != "latest.txt"], reverse=True)
        recent_files = files[:3] # 최근 3개
        
        if recent_files:
            daily_context += "\n<RECENT_DAILY_LOGS (Last 3 Days)>\n"
            for fname in recent_files:
                fpath = os.path.join(daily_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                        # 너무 길면 잘라서 토큰 절약 (각 1000자)
                        daily_context += f"--- [ {fname} ] ---\n{content[:1000]}...\n\n"
                except: pass
        else:
            daily_context += "\n<DAILY_LOG>: 아직 생성된 일간 보고서가 없습니다.\n"
    else:
        daily_context += "\n<DAILY_LOG>: 일간 보고서 폴더가 없습니다.\n"

    # 2. 상위 주기 리포트 (주간, 월간, 연간)
    # latest.txt를 우선 참조하되, 없으면 폴더 내 가장 최신 파일을 찾습니다.
    period_map = {
        'WEEKLY_MOMENTUM': '02_weekly',
        'MONTHLY_THEME': '03_monthly',
        'YEARLY_STRATEGY': '04_yearly'
    }
    
    context_text = "### [ 역사적 맥락 참조 데이터 ]\n"
    context_text += daily_context
    
    for label, folder_name in period_map.items():
        folder_path = os.path.join(base_dir, folder_name)
        target_content = ""
        found_file = ""

        if os.path.exists(folder_path):
            # 1순위: latest.txt 시도
            latest_p = os.path.join(folder_path, 'latest.txt')
            if os.path.exists(latest_p):
                try:
                    with open(latest_p, "r", encoding="utf-8") as f:
                        target_content = f.read()
                        found_file = "latest.txt"
                except: pass
            
            # 2순위: 실패 시 가장 최신 날짜 파일 검색
            if not target_content:
                try:
                    files = sorted([f for f in os.listdir(folder_path) if f.endswith(".txt") and f != "latest.txt"], reverse=True)
                    if files:
                        with open(os.path.join(folder_path, files[0]), "r", encoding="utf-8") as f:
                            target_content = f.read()
                            found_file = files[0]
                except: pass
        
        # 내용 추가
        if len(target_content.strip()) > 10:
            # 너무 길면 잘라서 토큰 절약 (주간/월간은 중요하므로 2000자 정도)
            context_text += f"\n<{label} - {found_file}>\n{target_content[:2000]}\n"
        else:
            context_text += f"\n<{label}>: 해당 주기의 분석 데이터가 아직 없습니다.\n"
            
    return context_text
    
def load_data():
    """서비스 설정(RSS, AI 모델 등)을 로드하고 미존재 시 기본 설정을 생성합니다."""
    default_structure = {
        "feeds": [], 
        "update_interval": 10, 
        "view_range": "실시간", 
        "retention_days": 7,
        "report_news_count": 100, 
        "report_auto_gen": True, 
        "report_gen_time": "08:00", 
        "report_days": 3,
        
        # 🎯 뉴스 판독 모델 설정 (Filter)
        "filter_model": {
            "provider": "Local",
            "name": "openai/gpt-oss-20b",
            "url": "http://192.168.1.105:11434/v1",
            "key": "",
            "temperature": 0.1,  # 💡 판독은 일관성이 중요하므로 낮게 설정
            "prompt": "투자 분석가입니다. 뉴스가 거시경제나 유동성에 중요한지 판독하여 0~5점을 매기세요."
        },
        
        # 🏛️ 투자 보고서 모델 설정 (Analyst)
        "analyst_model": {
            "provider": "Local",
            "name": "openai/gpt-oss-20b",
            "url": "http://192.168.1.105:11434/v1",
            "key": "",
            "temperature": 0.3,  # 💡 보고서는 약간의 통찰력이 필요하므로 0.3~0.5 권장
            "prompt": "당신은 전문 투자 전략가입니다. 지표와 뉴스를 분석하여 수익 전략을 제시하세요."
        }
    }
    
    # 1. 파일이 없으면 기본 설정 생성 (자동 복구)
    if not os.path.exists(CONFIG_PATH):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(default_structure, f, indent=4, ensure_ascii=False)
            print(f"✅ 기본 설정 파일 생성 완료: {CONFIG_PATH}")
            return default_structure
        except:
            return default_structure

    # 2. 파일이 있으면 로드 및 누락된 키 보정
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
            # 새로운 기능(온도 등)이 추가되어 키가 없을 경우를 대비해 기본값 병합
            for key, val in default_structure.items():
                if key not in loaded: 
                    loaded[key] = val
                elif isinstance(val, dict): # 중첩된 딕셔너리(모델 설정) 내부 키 보정
                    for sub_key, sub_val in val.items():
                        if sub_key not in loaded[key]:
                            loaded[key][sub_key] = sub_val
            return loaded
    except:
        return default_structure

# 공통 데이터 객체 (모든 모듈에서 공유)
data = load_data()

# common.py 에 추가
def calculate_and_save_sgi(write_api, bucket, sgi_data_dict):
    """
    SGI 2.0 물리 모델 계산 및 InfluxDB 저장 모듈
    """
    # 1. 물리량 계산
    delta_idx = sgi_data_dict['KOSPI']['curr'] - sgi_data_dict['KOSPI']['prev']
    safe_delta = delta_idx if abs(delta_idx) > 0.1 else (0.1 if delta_idx >= 0 else -0.1)

    g_f = max(-100, min(100, sgi_data_dict['KOR_NET_FOR']['curr'] / safe_delta))
    g_i = max(-100, min(100, sgi_data_dict['KOR_NET_INST']['curr'] / safe_delta))
    g_r = max(-100, min(100, sgi_data_dict['KOR_NET_RETAIL']['curr'] / safe_delta))
    
    # 3개월 평균 환율 기반 오메가 산출
    fx_hist = sgi_data_dict['USD_KRW']['hist']
    curr_fx = sgi_data_dict['USD_KRW']['curr']
    avg_fx_3m = sum([curr_fx] + fx_hist) / (len(fx_hist) + 1) if fx_hist else 1440.0
    omega = max(0.5, min(1.5, avg_fx_3m / curr_fx)) if curr_fx > 0 else 1.0
    
    sgi_score = ((g_f * 0.6) + (g_i * 0.3) - (g_r * 0.1)) * omega

# --- [common.py 내부: 250라인 부근 저장 로직 교정] ---
    # point 변수부터 write_api까지 앞부분 공백을 동일하게 맞추는 것이 핵심입니다.

    point = Point("market_physics") \
        .tag("symbol", "KOSPI_SGI") \
        .field("sgi_score", float(sgi_score)) \
        .field("g_foreign", float(g_f)) \
        .field("g_inst", float(g_i)) \
        .field("g_retail", float(g_r)) \
        .field("omega", float(omega)) \
        .field("avg_fx_3m", float(avg_fx_3m)) \
        .time(datetime.utcnow(), WritePrecision.S) 
    
    if write_api:
        write_api.write(bucket=bucket, record=point)
    
    return sgi_score, g_f, g_i, g_r, omega, avg_fx_3m
    
def get_sgi_inertia(query_api, bucket, days=5):
    """
    InfluxDB에서 과거 n일치 SGI 데이터를 불러와 '관성(Inertia)'을 측정합니다.
    [2026-02-07] 장이 열리지 않는 날을 고려하여 최근 n일의 평균 에너지 합을 산출합니다.
    """
    # 🎯 쿼리 설명: 최근 'days'일 동안의 sgi_score 필드를 가져와 일별 평균을 낸 뒤 합산합니다.
    query = f'''
    from(bucket: "{bucket}")
    |> range(start: -{days}d)
    |> filter(fn: (r) => r._measurement == "market_physics" and r._field == "sgi_score")
    |> aggregateWindow(every: 1d, fn: mean, createEmpty: false)
    '''
    
    try:
        result = query_api.query(query)
        # 모든 테이블과 레코드를 순회하며 값을 리스트에 담습니다.
        scores = []
        for table in result:
            for record in table.records:
                val = record.get_value()
                if val is not None:
                    scores.append(val)
        
        # 🎯 관성 산출: 누적된 에너지의 총합
        # 데이터가 하나도 없을 경우 0.0을 반환하여 UI 에러를 방지합니다.
        inertia_val = sum(scores) if scores else 0.0
        return inertia_val
        
    except Exception as e:
        # DB 연결 실패 등 예외 발생 시 로그를 남기고 0.0 반환
        print(f"SGI 관성 추출 실패: {e}")
        return 0.0

def get_metric_data(symbol, days=2):
    """
    InfluxDB에서 특정 심볼의 과거 데이터를 조회합니다.
    UI(app.py)와 백엔드(stock_collector.py)에서 공통으로 사용됩니다.
    """
    try:
        # common.py 전역 query_api 사용
        if query_api is None:
            return {}, [], "N/A", None

        # 1. 수급/금리/지수 성격에 따른 필터 최적화
        # 금리(RATE)나 매크로(MACRO) 지표는 주로 price 필드만 사용합니다.
        field_filter = 'r._field == "price" or r._field == "value" or r._field == "volume"'
        if "RATE" in symbol or "UNRATE" in symbol or "CPI" in symbol:
            field_filter = 'r._field == "price"'

        query = (
            f'from(bucket: "{INFLUX_BUCKET}") '
            f'|> range(start: -{days}d) '
            f'|> filter(fn: (r) => r.symbol == "{symbol}") '
            f'|> filter(fn: (r) => {field_filter}) '
            f'|> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'
        )
        
        result = query_api.query(query)
        p_history, m, l_time = [], {}, "N/A"
        p_records = [record for table in result for record in table.records]
        
        now_kst = datetime.utcnow() + timedelta(hours=9)
        today_kst = now_kst.date()
        
        # 미국 시장 지표 여부 판단
        is_us_market = any(x in symbol for x in ["NASDAQ", "DJI", "SP500", "SOX", "US_", "USA_", "FED_", "RRP", "TGA"])
        prev_val = None
        
        for record in p_records:
            r_time_kst = record.get_time().replace(tzinfo=None) + timedelta(hours=9)
            
            # 2. 데이터 추출 (수급 데이터는 보통 'value'에, 지수 데이터는 'price'에 저장됨)
            p_val = record.values.get('price')
            if p_val is None:
                p_val = record.values.get('value')
                
            if p_val is not None:
                p_history.append(p_val)
                
                # 전일 종가(기준가) 판정
                if is_us_market:
                    if r_time_kst < (now_kst - timedelta(hours=3)):
                        prev_val = p_val
                else:
                    if r_time_kst.date() < today_kst:
                        prev_val = p_val
                
                # 전체 레코드 복사 (volume, value 등 포함)
                m = record.values.copy()
                if 'price' not in m: m['price'] = p_val # UI 호환성 유지
                    
                l_time = r_time_kst.strftime('%m-%d %H:%M')

        # 3. 기준가 확정
        final_prev = prev_val if prev_val is not None else (p_history[0] if p_history else 0)
        m['prev_close'] = final_prev 
        
        return m, p_history, l_time, query_api

    except Exception as e:
        print(f"❌ {symbol} 데이터 로드 실패: {e}")
        return {}, [], "N/A", None

def clean_html(raw_html):
    if not raw_html: return "요약 내용 없음"
    soup = BeautifulSoup(raw_html, "html.parser")
    for s in soup(['style', 'script', 'span']): s.decompose()
    return re.sub(r'\s+', ' ', soup.get_text()).strip()

def is_filtered(title, g_inc, g_exc, l_inc="", l_exc=""):
    """제목(Title)만 검사하는 초경량 필터"""
    text = title.lower().strip()
    
    # 제외 필터 (Exclude)
    exc_tags = [t.strip().lower() for t in (g_exc + "," + l_exc).split(",") if t.strip()]
    if any(t in text for t in exc_tags): 
        return False
    
    # 포함 필터 (Include)
    g_inc_tags = [t.strip().lower() for t in g_inc.split(",") if t.strip()]
    if g_inc_tags and not any(t in text for t in g_inc_tags):
        return False
        
    l_inc_tags = [t.strip().lower() for t in l_inc.split(",") if t.strip()]
    if l_inc_tags and not any(t in text for t in l_inc_tags):
        return False
    
    return True

def save_data(new_data):
    """변경된 설정 데이터를 JSON 파일로 안전하게 저장합니다."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

def load_pending_files(range_type, target_feed=None, config_data=None):
    """JSON 저장 방식에 최적화된 로더 (설정 객체 주입 가능)"""
    news_list = []
    if not os.path.exists(PENDING_PATH): return news_list
    
    # 설정 소스 결정 (인자 우선, 없으면 전역 data)
    cfg = config_data if config_data else data
        
    now_kst = get_now_kst()
    today_date = now_kst.date()
    one_week_ago = now_kst - timedelta(days=7)
    
    all_files = sorted(os.listdir(PENDING_PATH), reverse=True)

    for filename in all_files:
        if not filename.endswith(".json"): continue
        try:
            with open(os.path.join(PENDING_PATH, filename), 'r', encoding='utf-8') as f:
                data_json = json.load(f)
                pub_dt = datetime.strptime(data_json['pub_dt'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=KST)
                
                if range_type == "오늘" and pub_dt.date() != today_date: continue
                if range_type == "일주일" and pub_dt < one_week_ago: continue
                
                l_inc = target_feed.get('include', "") if target_feed else ""
                l_exc = target_feed.get('exclude', "") if target_feed else ""
                
                if not is_filtered(data_json['title'], cfg.get("global_include", ""), cfg.get("global_exclude", ""), l_inc, l_exc):
                    continue
                
                news_list.append({
                    "title": data_json['title'], "link": data_json['link'], 
                    "published": data_json['pub_dt'], "summary": data_json['summary'], 
                    "pub_dt": pub_dt, "source": data_json['source']
                })
        except: continue
            
    news_list.sort(key=lambda x: x['pub_dt'], reverse=True)
    return news_list

def get_ai_summary(title, content, system_instruction=None, role="filter", config_data=None):
    """뉴스 판독 또는 요약을 위해 AI 모델을 호출합니다. (설정 객체 주입 가능)"""
    cfg_source = config_data if config_data else data
    now_time = get_now_kst().strftime('%Y-%m-%d %H:%M:%S')
    
    cfg = cfg_source.get("filter_model") if role == "filter" else cfg_source.get("analyst_model")
    base_url = cfg.get("url", "").rstrip('/')
    model_name = cfg.get("name")
    user_prompt = system_instruction if system_instruction else cfg.get("prompt", "")
    final_role = f"현재 시각: {now_time}\n분석 지침: {user_prompt}"

    is_direct_google = "googleapis.com" in base_url
    api_key = cfg.get("key")
    if not api_key:
        api_key = config.get("gemini_api_key", "") if (is_direct_google or "gemini" in model_name.lower()) else config.get("openai_api_key", "")

    if is_direct_google:
        url = f"{base_url}/v1beta/models/{model_name}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": f"시스템 지침: {final_role}\n\n사용자 입력:\n제목: {title}\n본문: {content}"}]}],
            "generationConfig": {"temperature": cfg.get("temperature", 0.3)}
        }
    else:
        url = f"{base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key: headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": final_role},
                {"role": "user", "content": f"제목: {title}\n본문: {content}"}
            ],
            "temperature": cfg.get("temperature", 0.3)
        }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        result = resp.json()
        if "candidates" in result: return result['candidates'][0]['content']['parts'][0]['text']
        else: return result['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ [ERROR] AI 분석 실패: {str(e)}"

def get_trading_ranking(start_dt, end_dt):
    """pykrx를 이용해 외국인/기관 순매수/매도 상위 종목을 가져옵니다."""
    if not HAS_PYKRX: return ""
    
    try:
        s_str = start_dt.strftime("%Y%m%d")
        e_str = end_dt.strftime("%Y%m%d")
        
        # 1. 외국인 (전체 시장)
        df_for = stock.get_market_net_purchases_of_equities_by_ticker(s_str, e_str, "ALL", "외국인")
        if df_for.empty: return ""
        
        top_for_buy = df_for.sort_values(by='순매수거래대금', ascending=False).head(10)
        top_for_sell = df_for.sort_values(by='순매수거래대금', ascending=True).head(10)
        
        # 2. 기관 (전체 시장)
        df_inst = stock.get_market_net_purchases_of_equities_by_ticker(s_str, e_str, "ALL", "기관합계")
        top_inst_buy = df_inst.sort_values(by='순매수거래대금', ascending=False).head(10)
        top_inst_sell = df_inst.sort_values(by='순매수거래대금', ascending=True).head(10)
        
        def fmt(df):
            return ", ".join([f"{row['종목명']}({row['순매수거래대금']/1e8:+.1f}억)" for _, row in df.iterrows()])

        res = f"### [ 수급 주도주 Top 10 ({start_dt.strftime('%m-%d')} ~ {end_dt.strftime('%m-%d')}) ]\n"
        res += f"- 외국인 순매수: {fmt(top_for_buy)}\n"
        res += f"- 외국인 순매도: {fmt(top_for_sell)}\n"
        res += f"- 기관 순매수: {fmt(top_inst_buy)}\n"
        res += f"- 기관 순매도: {fmt(top_inst_sell)}\n"
        return res + "\n"
    except Exception as e:
        print(f"⚠️ pykrx 수집 실패: {e}")
        return ""

def generate_market_report(r_type, config_data):
    """
    통합 보고서 생성 엔진
    UI(app.py)와 백엔드(stock_collector.py)에서 공통으로 사용합니다.
    """
    now_kst = get_now_kst()
    
    # 1. 기간 설정
    # 지표: 추세를 보기 위해 넉넉하게 잡음
    metric_lookback_map = {"daily": 7, "weekly": 30, "monthly": 365}
    m_days = metric_lookback_map.get(r_type, 7)
    
    # 뉴스: 해당 주기 동안의 뉴스만 필터링
    news_lookback_days = 3 if (r_type == "daily" and now_kst.weekday() in [5, 6, 0]) else 1
    if r_type == "weekly": news_lookback_days = 7
    if r_type == "monthly": news_lookback_days = 30
    
    # 2. 데이터 수집
    # [A] 역사적 맥락
    historical_context = load_historical_contexts()
    
    # [B] 지표 데이터 (InfluxDB)
    metric_context = f"### [ 주요 시장 지표 분석 ({r_type.upper()}, 지난 {m_days}일 추세) ]\n"
    for sym in ALL_SYMBOLS:
        m_data, p_hist, _, _ = get_metric_data(sym, days=m_days + 1)
        if m_data and 'price' in m_data and len(p_hist) >= 2:
            curr = m_data['price']
            prev_close = p_hist[-2] # 전일 종가
            start_val = p_hist[0]   # 기간 시초가
            
            daily_diff = ((curr - prev_close) / prev_close * 100) if prev_close != 0 else 0
            period_diff = ((curr - start_val) / start_val * 100) if start_val != 0 else 0
            
            name = display_names.get(sym, sym)
            metric_context += f"- {name}: {curr:,.2f} (전일: {daily_diff:+.2f}%, 기간: {period_diff:+.2f}%)\n"

    # [C] 수급 랭킹 (pykrx)
    ranking_context = ""
    if HAS_PYKRX:
        target_date = now_kst - timedelta(days=news_lookback_days)
        ranking_context = get_trading_ranking(target_date, now_kst)

    # [D] 뉴스 데이터
    raw_news = load_pending_files("일주일" if r_type != "monthly" else "전체", config_data=config_data)
    target_dt = now_kst - timedelta(days=news_lookback_days)
    
    recent_news = [n for n in raw_news if n['pub_dt'] >= target_dt]
    recent_news.sort(key=lambda x: x['pub_dt'], reverse=True)
    
    news_limit = config_data.get("report_news_count", 100)
    final_news = recent_news[:news_limit]
    
    news_context = f"### [ 최근 {news_lookback_days}일 주요 뉴스 ]\n"
    for n in final_news:
        t_str = n['pub_dt'].strftime('%Y-%m-%d %H:%M')
        summary = clean_html(n.get('summary', ''))[:150]
        news_context += f"[{t_str}] {n['title']}\n   > {summary}\n"

    # 3. 프롬프트 구성 (app.py의 고도화된 프롬프트 채용)
    council_instruction = config_data.get("council_prompt", "당신은 전문 금융 애널리스트입니다.")
    
    if r_type == "daily":
        # [일간] 실전 매매 및 즉각적 대응 중심
        role_desc = (
            f"{council_instruction}\n"
            "당신은 '실전 투자 전략가'입니다. 오늘 시장이 과거의 흐름(주간/월간 맥락)에서 벗어났는지, "
            "아니면 추세를 강화했는지 판단하고 내일의 구체적인 행동 지침을 제시해야 합니다."
        )
        analysis_guideline = (
            "### [ 자료 분석 지침 (Daily) ]\n"
            "1. 수치 절대 우선: 뉴스 톤보다 '원천 수급 지표'의 수치를 최우선 팩트로 삼으세요.\n"
            "2. 연속성 검증: '과거 분석 기록'의 전망과 오늘 지표를 비교하여 예측 적중 여부를 평가하세요.\n"
            "3. 즉각적 대응: 내일 시초가 공략, 비중 축소 등 구체적인 액션 플랜을 제시하세요.\n"
        )
        structure_instruction = (
            "### [ 일간 보고서 작성 형식 ]\n"
            "1. 시황 브리핑\n"
            "2. 주요 뉴스 및 오피니언:경제적 영향력이 큰 뉴스나 주요인사 발언\n"
            "3. 유동성 분석: 유동성 관련 지표를 분석하여 현재 유동성 분석(예: 한국 -> 미국, 위험 -> 안전, AI -> 바이오)\n"
            "4. 증시 분석: 증시 각 산업별 0~5점 분석 및 요약\n"
            "5. 자산 분석: 증시 외 자산별 0~5점 분석 및 요약\n"
            "6. 현 주력산업 및 미래유망산업 전망\n"
            "7. 리스크 및 대응: 단기적 위험 요소와 회피 전략\n"
            "8. 포트폴리오 구성 및 투자 전략\n"
        )
    else:
        # [주간/월간] 흐름 기록 및 미래 예측을 위한 사료화
        period_label = "주간" if r_type == "weekly" else "월간"
        role_desc = (
            f"{council_instruction}\n"
            f"당신은 '경제 흐름 기록관'입니다. 이 {period_label} 보고서는 미래 시점에서 현재를 복기할 때 "
            "참고할 중요한 '사료(Historical Record)'가 됩니다. 단순 나열보다는 "
            "시장을 지배했던 '핵심 서사(Narrative)'와 '구조적 변화'를 중심으로 인과관계를 명확히 기록하세요."
        )
        analysis_guideline = (
            f"### [ 자료 분석 지침 ({r_type.title()}) ]\n"
            "1. 흐름 파악: 하루하루의 등락보다 기간 전체를 관통하는 추세를 읽어내세요.\n"
            "2. 변곡점 기록: 추세가 바뀌거나 강화된 결정적 사건(Event)을 찾아 기록하세요.\n"
            "3. 미래 예측의 근거: 이 흐름이 다음 주기로 어떻게 이어질지 논리적 근거를 남기세요.\n"
        )
        structure_instruction = (
            f"### [ {period_label} 보고서 작성 형식 ]\n"
            "1. 기간 핵심 요약: 이번 기간을 관통하는 한 문장 정의 및 총평\n"
            "2. 주요 타임라인: 시장의 방향을 결정지은 결정적 뉴스나 사건 복기\n"
            "3. 매크로 및 수급 변화: 기간 동안의 금리, 환율, 수급 주체의 태도 변화 분석\n"
            "4. 주도 섹터 및 소외 섹터: 자금이 쏠린 곳과 빠져나간 곳의 구조적 이유\n"
            "5. 다음 주기 전망: 현재 흐름을 바탕으로 예상되는 시나리오 (상승/하락/횡보)\n"
            "6. 중장기 대응 전략: 긴 호흡에서의 자산 배분 및 리스크 관리 조언\n"
        )

    full_instruction = (
        f"{role_desc}\n"
        f"현재 시각: {now_kst.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{analysis_guideline}\n"
        f"--- [ 1. 과거 분석 기록 ] ---\n{historical_context}\n\n"
        f"--- [ 2. 수급 및 뉴스 데이터 ] ---\n{ranking_context}\n{news_context}\n\n"
        f"--- [ 3. 원천 수급 지표 (최우선) ] ---\n{metric_context}\n\n"
        f"{structure_instruction}"
    )

    # 4. AI 호출
    return get_ai_summary(
        title=f"{r_type.upper()} Report", content=news_context, 
        system_instruction=full_instruction, role="analyst", config_data=config_data
    )