
import json
import os
import re
import requests
import time
import math
import feedparser
from datetime import datetime, timedelta, date, timezone
from bs4 import BeautifulSoup

try:
    import yfinance as yf
except ImportError:
    yf = None

KST = timezone(timedelta(hours=9))

def get_now_kst():
    """현재 한국 시간을 반환합니다."""
    return datetime.now(KST)

# --- [0. 시스템 공통 경로 설정] ---
OPTIONS_PATH = "/data/options.json"
BASE_PATH = "/share/ai_analyst"
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
    dir_map = {
        'YEARLY_STRATEGY': '04_yearly/latest.txt',
        'MONTHLY_THEME': '03_monthly/latest.txt',
        'WEEKLY_MOMENTUM': '02_weekly/latest.txt',
        'DAILY_LOG': '01_daily/latest.txt'
    }
    
    context_text = "### [ 역사적 맥락 참조 데이터 ]\n"
    
    for label, rel_path in dir_map.items():
        full_path = os.path.join(base_dir, rel_path)
        
        # 🛡️ 파일이 실제로 존재하는지 체크
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
                # 데이터가 너무 짧으면 기록이 없는 것으로 간주
                if len(content.strip()) > 10:
                    context_text += f"\n<{label}>\n{content[:1000]}\n"
                else:
                    context_text += f"\n<{label}>: 해당 주기의 분석 데이터가 아직 비어 있습니다.\n"
        else:
            # 💡 파일이 없을 때 AI에게 줄 메시지
            # AI가 "과거 데이터가 없으니 오늘 수치에 더 집중해서 분석해라"라고 판단하게 유도합니다.
            context_text += f"\n<{label}>: 시스템 도입 초기 단계로, 아직 {label} 데이터가 생성되지 않았습니다. 현재 가용한 최신 데이터 중심으로 분석하십시오.\n"
            
    return context_text
    
def get_market_summary():
    """Pykrx를 활용해 KOSPI/KOSDAQ 지수를 가져옵니다."""
    summary = ""
    try:
        from pykrx import stock
        now = get_now_kst()
        # 최근 5일 조회 (주말/휴일 대비)
        start_dt = (now - timedelta(days=5)).strftime("%Y%m%d")
        end_dt = now.strftime("%Y%m%d")
        
        # 1001: KOSPI, 2001: KOSDAQ
        df_k = stock.get_index_ohlcv(start_dt, end_dt, "1001")
        df_kq = stock.get_index_ohlcv(start_dt, end_dt, "2001")
        
        if not df_k.empty and not df_kq.empty:
            last_k = df_k.iloc[-1]
            last_kq = df_kq.iloc[-1]
            date_str = last_k.name.strftime("%Y-%m-%d")
            
            summary = (
                f"### [ 📉 국내 증시 요약 ({date_str}) ]\n"
                f"- KOSPI: {last_k['종가']:,.2f} ({last_k['등락률']:+.2f}%)\n"
                f"- KOSDAQ: {last_kq['종가']:,.2f} ({last_kq['등락률']:+.2f}%)\n\n"
            )
    except Exception as e:
        print(f"⚠️ Pykrx 데이터 조회 실패: {e}")
    return summary

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
            "prompt": "당신은 전문 투자 전략가입니다. 뉴스를 분석하여 투자 전략을 제시하세요."
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

def get_krx_market_indicators():
    """코스피/코스닥 지수 및 수급현황 요약 (로그 강화)"""
    try:
        target_date = get_latest_trading_date()
        print(f"🔍 [지표 수집] 대상 날짜: {target_date}")
        summary = f"### [ KRX 시장 지표 요약 ({target_date}) ]\n"

        for m_name, m_code in [("KOSPI", "1001"), ("KOSDAQ", "2001")]:
            df = stock.get_index_ohlcv_by_date(target_date, target_date, m_code)
            if not df.empty:
                row = df.iloc[0]
                amount_bill = row['거래대금'] / 100_000_000
                summary += f"- {m_name}: {row['종가']:,.2f} (거래량: {row['거래량']:,.0f}, 거래대금: {amount_bill:,.0f}억)\n"
                print(f"   📊 {m_name} 로드 완료: {row['종가']:,.2f}")

        df_inv = stock.get_market_net_purchase_of_equities_by_ticker(target_date, target_date, "ALL")
        foreign_bill = df_inv['외국인'].sum() / 100_000_000
        inst_bill = df_inv['기관합계'].sum() / 100_000_000
        summary += f"- 투자자 수급: 외국인 {foreign_bill:,.0f}억, 기관 {inst_bill:,.0f}억 (순매수 기준)\n"
        print(f"   💰 수급 데이터 합계: 외인({foreign_bill:,.0f}억), 기관({inst_bill:,.0f}억)", flush=True)
        
        return summary
    except Exception as e:
        print(f"❌ [에러] 지수 요약 로드 실패: {e}")
        return "⚠️ KRX 지수 요약 로드 실패"

def get_krx_top_investors():
    """외국인/기관 순매수 상위 10개 종목 (로그 강화)"""
    try:
        target_date = get_latest_trading_date()
        df = stock.get_market_net_purchase_of_equities_by_ticker(target_date, target_date, "ALL")
        
        def get_top_list(data, col):
            top_df = data.sort_values(by=col, ascending=False).head(10)
            items = []
            for ticker, row in top_df.iterrows():
                name = stock.get_market_ticker_name(ticker)
                val_bill = row[col] / 100_000_000
                items.append(f"{name}({val_bill:,.0f}억)")
            return ", ".join(items)

        f_top = get_top_list(df, '외국인')
        i_top = get_top_list(df, '기관합계')
        
        print(f"🔝 [순매수 Top 10] 외인: {f_top[:50]}...", flush=True)# 로그가 너무 길지 않게 일부만 출력
        print(f"🔝 [순매수 Top 10] 기관: {i_top[:50]}...", flush=True)
        
        report = "### [ 수급 상위 종목 (Top 10) ]\n"
        report += f"- 외국인 매수: {f_top}\n"
        report += f"- 기관 매수: {i_top}\n"
        return report
    except Exception as e:
        print(f"❌ [에러] 수급 종목 로드 실패: {e}")
        return "⚠️ 수급 종목 로드 실패"

def get_krx_sector_indices():
    """주요 산업별 지수 현황 (로그 강화)"""
    try:
        target_date = get_latest_trading_date()
        indices = stock.get_index_ticker_list(target_date, market="KRX")
        print(f"🏭 [산업 섹터] 전체 {len(indices)}개 지수 중 주요 항목 필터링 중...")
        
        report = "### [ 주요 산업별 지수 현황 ]\n"
        count = 0
        for ticker in indices:
            name = stock.get_index_ticker_name(ticker)
            if any(kw in name for kw in ['반도체', 'IT', '금융', '에너지', '바이오', '자동차']):
                df = stock.get_index_ohlcv_by_date(target_date, target_date, ticker)
                if not df.empty:
                    val = df.iloc[0]['종가']
                    report += f"- {name}: {val:,.2f}\n"
                    print(f"   ✅ 섹터 확인: {name} ({val:,.2f})", flush=True)
                    count += 1
            if count >= 8: break
        return report
    except Exception as e:
        print(f"❌ [에러] 산업 지수 로드 실패: {e}")
        return "⚠️ 산업 지수 로드 실패"

def get_global_market_data(r_type="daily"):
    """yfinance를 통해 글로벌 시장 데이터를 수집합니다."""
    if not yf: return "⚠️ yfinance 모듈이 설치되지 않았습니다."

    end_dt = get_now_kst()
    if r_type == 'daily': days = 7
    elif r_type == 'weekly': days = 30
    else: days = 60
    
    start_dt = end_dt - timedelta(days=days)
    
    tickers = {
        "🇺🇸 미국 3대 지수 & VIX": {
            "^GSPC": "S&P500", "^DJI": "Dow Jones", "^IXIC": "Nasdaq", 
            "^SOX": "SOX(반도체)", "^VIX": "VIX"
        },
        "🌏 글로벌 지수": {
            "^N225": "Nikkei 225", "^GDAXI": "DAX", "^HSI": "Hang Seng"
        },
        "💵 금리 & 환율": {
            "^TNX": "미국채 10년", "^TYX": "미국채 30년", "^FVX": "미국채 5년", 
            "KRW=X": "USD/KRW", "DX-Y.NYB": "달러 인덱스", "JPY=X": "USD/JPY"
        },
        "🛢️ 원자재 & 코인": {
            "CL=F": "WTI 원유", "GC=F": "금", "SI=F": "은", "HG=F": "구리", 
            "BTC-USD": "비트코인"
        }
    }
    
    all_symbols = [s for cat in tickers.values() for s in cat.keys()]
    report = f"### [ 🌍 글로벌 시장 데이터 ({days}일 변동) ]\n"
    
    try:
        df = yf.download(all_symbols, start=start_dt.strftime('%Y-%m-%d'), end=end_dt.strftime('%Y-%m-%d'), progress=False)['Close']
        for cat_name, items in tickers.items():
            report += f"#### {cat_name}\n"
            for sym, name in items.items():
                try:
                    if sym in df.columns:
                        series = df[sym].dropna()
                        if series.empty: continue
                        curr, start = series.iloc[-1], series.iloc[0]
                        chg_pct = ((curr - start) / start) * 100
                        report += f"- **{name}**: {curr:,.2f} ({chg_pct:+.2f}%, 범위: {series.min():,.2f}~{series.max():,.2f})\n"
                except: continue
            report += "\n"
        return report
    except Exception as e:
        return f"⚠️ 글로벌 데이터 수집 실패: {e}"

def get_past_reports(section, count=1):
    """특정 섹션의 과거 보고서(날짜별 파일)를 최신순으로 가져옵니다."""
    base_dir = REPORT_DIR
    dir_map = {'daily': '01_daily', 'weekly': '02_weekly', 'monthly': '03_monthly'}
    target_dir = os.path.join(base_dir, dir_map.get(section, "05_etc"))
    
    content = ""
    if os.path.exists(target_dir):
        # latest.txt 제외하고 날짜 형식 파일만 정렬해서 가져옴
        files = sorted([f for f in os.listdir(target_dir) if f.endswith(".txt") and f != "latest.txt"], reverse=True)
        for f_name in files[:count]:
            try:
                with open(os.path.join(target_dir, f_name), 'r', encoding='utf-8') as f:
                    content += f"\n--- [ 과거 리포트: {f_name} ] ---\n{f.read()}\n"
            except: pass
    return content

def get_ai_summary(title, content, system_instruction=None, role="filter", custom_config=None):
    """뉴스 판독 또는 요약을 위해 AI 모델을 호출합니다. (통합됨)"""
    now_time = get_now_kst().strftime('%Y-%m-%d %H:%M:%S')
    
    # 설정 로드 (custom_config가 있으면 우선 사용, 아니면 common.data 사용)
    cfg_data = custom_config if custom_config else data
    cfg = cfg_data.get("filter_model") if role == "filter" else cfg_data.get("analyst_model")
    
    base_url = cfg.get("url", "").rstrip('/')
    model_name = cfg.get("name")
    
    # 지침 설정
    user_prompt = system_instruction if system_instruction else cfg.get("prompt", "")
    final_role = f"현재 시각: {now_time}\n분석 지침: {user_prompt}"

    # 클라우드(Google 직접 호출) 여부 판별
    is_direct_google = "generativelanguage.googleapis.com" in base_url
    
    if is_direct_google:
        api_key = config.get("gemini_api_key", "")
    else:
        api_key = cfg.get("key") if cfg.get("key") else config.get("openai_api_key", "")

    # 호출 방식 분기
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
            "messages": [{"role": "system", "content": final_role}, {"role": "user", "content": f"제목: {title}\n본문: {content}"}],
            "temperature": cfg.get("temperature", 0.3)
        }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        result = resp.json()
        if "candidates" in result:
            return result['candidates'][0]['content']['parts'][0]['text']
        else:
            return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"[{now_time}] AI 분석 에러: {str(e)}")
        return f"❌ [ERROR] AI 분석 중 예외 발생: {str(e)}"

def prepare_report_data(r_type, config_data):
    """보고서 생성을 위한 데이터(KRX 지표 + 뉴스/과거리포트)를 구성합니다."""
    now_kst = get_now_kst()
    global_data = get_global_market_data(r_type)
    
    if r_type == "daily":
        print(f"🔍 [Daily] 데이터 수집 (KRX 지표 & 뉴스 필터링) 시작...")
        market_summary = get_krx_market_indicators()
        top_purchases = get_krx_top_investors()
        industry_indices = get_krx_sector_indices()
        
        news_count = config_data.get("report_news_count", 100)
        raw_news_list = []
        seen_keys = set()
        target_date_limit = (now_kst - timedelta(days=3)).date()
        
        if os.path.exists(PENDING_PATH):
            files = sorted([f for f in os.listdir(PENDING_PATH) if f.endswith(".json")], reverse=True)
            for f_name in files:
                try:
                    with open(os.path.join(PENDING_PATH, f_name), "r", encoding="utf-8") as file:
                        news_data = json.load(file)
                        title = news_data.get("title", "").strip()
                        pub_dt_str = news_data.get("pub_dt", "")
                        if not title: continue
                        try: f_dt = datetime.strptime(pub_dt_str, '%Y-%m-%d %H:%M:%S').date()
                        except: f_dt = now_kst.date()
                        if f_dt < target_date_limit: continue
                        clean_key = title.replace("[특징주]", "").replace("[속보]", "").replace(" ", "")[:18]
                        if clean_key not in seen_keys:
                            seen_keys.add(clean_key)
                            raw_news_list.append(f"[{pub_dt_str[5:16]}] {title}")
                        if len(raw_news_list) >= news_count: break
                except: continue
        
        news_ctx = f"### [ 금일 주요 뉴스 {len(raw_news_list)}선 ]\n" + "\n".join([f"- {t}" for t in raw_news_list])
        return (f"{market_summary}\n{global_data}\n{top_purchases}\n{industry_indices}\n\n{news_ctx}", "일간(Daily)")
    else:
        # Weekly: 이번 주 일간 보고서 전부 (최대 7일)
        # Monthly: 이번 달 주간 보고서 전부 (최대 5개)
        if r_type == "weekly":
            source_docs = get_past_reports('daily', 7)
            label = "주간(Weekly)"
        else:
            source_docs = get_past_reports('weekly', 5)
            label = "월간(Monthly)"
            
        if not source_docs:
            source_docs = "⚠️ 분석할 하위 주기 리포트 데이터가 없습니다."
            
        return f"{source_docs}\n\n{global_data}", label

def generate_invest_report(r_type, input_content, config_data):
    """AI를 호출하여 투자 전략 보고서를 생성합니다."""
    now_kst = get_now_kst()
    
    if r_type == "daily":
        # 일간: 미래 전략 예상 (최근 3일치 일간 + 상위 주기 참조)
        past_daily = get_past_reports('daily', 3)
        past_weekly = get_past_reports('weekly', 1)
        past_monthly = get_past_reports('monthly', 1)
        
        historical_context = (
            f"### [ 최근 3일간의 일간 리포트 ]\n{past_daily}\n\n"
            f"### [ 상위 주기(주간/월간) 흐름 참조 ]\n{past_weekly}\n{past_monthly}"
        )
        
        base_prompt = "당신은 미래를 예측하고 대응 전략을 수립하는 '전략가'입니다."
        specific_guideline = (
            "1. **추세 연속성 확인**: 최근 3일간의 일간 리포트 흐름을 분석하여 단기 추세가 유지되는지 반전되는지 판단하라.\n"
            "2. **상위 프레임 정렬**: 현재의 단기 움직임이 주간/월간의 큰 흐름과 일치하는지(동조화) 아니면 벗어나는지(이탈) 분석하라.\n"
            "3. **미래 전략 수립**: 위 분석을 바탕으로 내일의 시장 시나리오를 예측하고, 이에 따른 구체적인 매매 전략을 제시하라."
        )
        structure_instruction = (
            "### [ 일간 보고서 작성 형식 ]\n"
            "1. 시황 브리핑\n"
            "2. 주요 뉴스 및 오피니언: 경제적 영향력이 큰 뉴스나 주요인사 발언\n"
            "3. 유동성 분석: 유동성 관련 지표를 분석하여 현재 유동성 흐름 파악 (예: 한국 -> 미국, 위험 -> 안전, AI -> 바이오)\n"
            "4. 추세 연속성 분석\n"
            "5. 증시 분석: 증시 각 산업별 0~5점 분석 및 요약\n"
            "6. 자산 분석: 증시 외 자산별 0~5점 분석 및 요약\n"
            "7. 현 주력산업 및 미래유망산업 전망\n"
            "8. 리스크 및 대응: 단기적 위험 요소와 회피 전략\n"
            "9. 포트폴리오 구성 및 투자 전략"
        )
        
    elif r_type == "weekly":
        # 주간: 현상 원인 기록 (지난 주간 리포트 참조)
        past_weekly = get_past_reports('weekly', 1)
        historical_context = f"### [ 지난 주간 리포트 (비교용) ]\n{past_weekly}"
        
        base_prompt = "당신은 시장의 현상을 기록하고 원인을 규명하는 '시장 역사가'입니다."
        specific_guideline = (
            "1. **인과관계 규명**: 이번 주 일간 리포트들에 기록된 시장 변동의 근본적인 원인(재료, 수급, 매크로 등)을 종합하여 규명하라.\n"
            "2. **주간 흐름 요약**: 월요일부터 금요일까지의 시장 심리 변화와 주요 이슈를 타임라인 형태로 요약하라.\n"
            "3. **변화 기록**: 지난주 리포트와 비교하여 시장의 색깔이 어떻게 변했는지 기록하라."
        )
        structure_type = "주간 시장 원인 및 흐름 분석"
        structure_instruction = f"### [ 보고서 작성 형식: {structure_type} ]\n(각 리포트 성격에 맞는 목차를 구성하여 작성할 것)"
        
    else: # monthly
        # 월간: 구조적 변화 기록 (지난 월간 리포트 참조)
        past_monthly = get_past_reports('monthly', 1)
        historical_context = f"### [ 지난 월간 리포트 (비교용) ]\n{past_monthly}"
        
        base_prompt = "당신은 거시경제와 시장의 구조적 변화를 기록하는 '매크로 분석가'입니다."
        specific_guideline = (
            "1. **월간 매크로 평가**: 이번 달 주간 리포트들을 관통하는 핵심 거시경제 키워드를 뽑고, 그 영향을 평가하라.\n"
            "2. **구조적 변화 포착**: 한 달간 발생한 사건들이 시장의 펀더멘털이나 장기 추세에 어떤 변화를 주었는지 기록하라.\n"
            "3. **역사적 기록**: 훗날 이 달을 회고할 때 가장 중요하게 기억될 사건과 그 의미를 정의하라."
        )
        structure_type = "월간 거시경제 및 구조적 변화 분석"
        structure_instruction = f"### [ 보고서 작성 형식: {structure_type} ]\n(각 리포트 성격에 맞는 목차를 구성하여 작성할 것)"

    analysis_guideline = f"### [ {r_type} 분석 지침 ]\n{specific_guideline}"

    system_prompt = (
        f"현재 임무: {r_type} 투자 보고서 작성\n"
        f"기준 시각: {now_kst.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"당신은 {base_prompt}이며, 아래 지침을 준수해야 합니다.\n\n"
        f"{analysis_guideline}\n\n"
        f"--- [ 참고 자료 (Context) ] ---\n{historical_context}\n\n"
        f"--- [ 최종 지시 ] ---\n"
        f"제공된 입력 데이터(Input Data)를 바탕으로 보고서를 작성하세요.\n"
        f"{structure_instruction}"
    )
    
    return get_ai_summary(title=f"{date.today()} {r_type.upper()} 보고서", content=input_content, system_instruction=system_prompt, role="analyst", custom_config=config_data)