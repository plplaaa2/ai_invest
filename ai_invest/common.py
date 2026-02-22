
import json
import os
import re
import requests
import time
import math
import io
import pandas as pd
import feedparser
from datetime import datetime, timedelta, date, timezone
from bs4 import BeautifulSoup

try:
    import yfinance as yf
except ImportError:
    yf = None

from prompts import REPORT_PROMPTS

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

def check_keyword_filter(text, exc_list):
    """
    통합 필터링 로직: 제외어(Exclude) 포함 시 탈락
    scraper.py와 app.py에서 공통으로 사용
    """
    if not text: return False
    text = text.lower()
    
    exc_list = exc_list or []

    # 1. 제외어(Exclude) 체크
    if any(x in text for x in exc_list if x):
        return False
            
    return True

def check_news_filter(title, g_exc):
    """전역 제외 필터만 처리"""
    if not title: return False
    title = title.lower()
    
    # 1. 제외 필터링 (Global)
    exc_list = [k.strip().lower() for k in g_exc.split(",") if k.strip()]
    if any(x in title for x in exc_list): return False
    
    return True

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
    
def get_krx_summary_raw(ignore_cache=False):
    """KOSPI/KOSDAQ 지수 및 KOSPI 3대 주체(개인/외인/기관) 종합 분석"""
    results = {}
    cache_dir = os.path.join(BASE_PATH, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "krx_summary_v2.json")
    
    # 🎯 캐시 처리 (10분)
    if not ignore_cache and os.path.exists(cache_path):
        try:
            if time.time() - os.path.getmtime(cache_path) < 600:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except: pass

    try:
        from pykrx import stock
        from pykrx import bond
        now = get_now_kst()
        
        # 🎯 한국 장 시간(09:00) 전이면 어제 날짜를 기준일로 설정
        if now.hour < 9:
            target_date = (now - timedelta(days=1)).strftime("%Y%m%d")
        else:
            target_date = now.strftime("%Y%m%d")
            
        # 휴일 등을 고려하여 넉넉하게 14일 전부터 조회
        start_dt = (now - timedelta(days=14)).strftime("%Y%m%d")
        
        # 1. 지수 데이터 (KOSPI/KOSDAQ)
        for code, name in [("1001", "KOSPI"), ("2001", "KOSDAQ")]:
            df = stock.get_index_ohlcv(start_dt, target_date, code)
            if not df.empty:
                last = df.iloc[-1]
                price = float(last['종가'])
                pct = float(last['등락률']) if '등락률' in df.columns else 0.0
                
                # 등락폭 계산 (종가와 등락률 역산)
                prev = price / (1 + (pct / 100))
                diff = price - prev
                
                results[name] = {
                    "price": price, "pct": pct,
                    "amount": float(last['거래대금']) / 100_000_000,
                    "date": last.name.strftime("%m-%d"),
                    # 대시보드 호환용 키 추가
                    "value": price,
                    "val_str": f"{price:,.2f}",
                    "delta_str": f"{diff:+.2f} ({pct:+.2f}%)"
                }

        # 2. KOSPI/KOSDAQ 주체별 거래대금 및 Top 10 종목
        if "KOSPI" in results:
            actual_date = df.index[-1].strftime("%Y%m%d") # 실제 데이터 날짜
            
            for mkt in ["KOSPI", "KOSDAQ"]:
                try:
                    # (A) 거래대금 합계
                    df_inv = stock.get_market_trading_value_by_date(actual_date, actual_date, mkt)
                    if not df_inv.empty:
                        row = df_inv.iloc[-1]
                        for kor, eng in [('개인', 'Individual'), ('외국인합계', 'Foreigner'), ('기관합계', 'Institution')]:
                            val_bill = float(row[kor]) / 100_000_000
                            results[f"{mkt}_{eng}"] = {
                                "value": val_bill,
                                "val_str": f"{val_bill/10000:,.2f}조" if abs(val_bill) >= 10000 else f"{val_bill:,.0f}억"
                            }

                    # (B) 주체별 순매수 Top 10 종목
                    for kor, eng in [("개인", "Top_Individual"), ("외국인", "Top_Foreigner"), ("기관합계", "Top_Institution")]:
                        df_top = stock.get_market_net_purchases_of_equities(actual_date, actual_date, mkt, kor)
                        if not df_top.empty:
                            items = [f"{r['종목명']}({float(r['종목별순매수금액'])/100_000_000:,.0f}억)" for _, r in df_top.head(10).iterrows()]
                            results[f"{mkt}_{eng}"] = ", ".join(items)

                    # (C) 공매도 거래량
                    df_short = stock.get_shorting_investor_volume_by_date(actual_date, actual_date, mkt)
                    if not df_short.empty:
                        s_row = df_short.iloc[-1]
                        results[f'{mkt}_Short'] = {"total": f"{s_row['합계']:,.0f}주", "for": f"{s_row['외국인']:,.0f}주"}
                except: pass

            # (D) 채권 금리
            try:
                df_bond = bond.get_otc_treasury_yields(actual_date)
                if not df_bond.empty:
                    for label, key in [("KR_3Y", "국고채 3년"), ("KR_10Y", "국고채 10년")]:
                        if key in df_bond.index:
                            val = float(df_bond.loc[key, "수익률"])
                            diff = float(df_bond.loc[key, "대비"])
                            results[label] = {
                                "value": val, "diff": diff,
                                "val_str": f"{val:.2f}%", "delta_str": f"{diff:+.2f}"
                            }
            except: pass

        # 캐시 저장 후 반환
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False)
        return results

    except Exception as e:
        print(f"⚠️ 데이터 수집 실패: {e}")
        return results
    
def get_krx_market_data(r_type="daily"):
    """(통합) 지수, 수급, 금리 요약 보고서 (기간별 맞춤)"""
    # 🎯 보고서 유형별 기간 설정
    if r_type == 'daily':
        fetch_days = 7      # 데이터 확보: 1주일
        comp_idx = -2       # 변화 기준: 전일 대비 (Daily Change)
        period_name = "일간(1D)"
    elif r_type == 'weekly':
        fetch_days = 14     # 데이터 확보: 2주일
        comp_idx = -6       # 변화 기준: 1주 전 대비 (Weekly Change, approx 5 trading days)
        period_name = "주간(1W)"
    else: # monthly
        fetch_days = 60     # 데이터 확보: 2달
        comp_idx = -21      # 변화 기준: 1달 전 대비 (Monthly Change, approx 20 trading days)
        period_name = "월간(1M)"

    data = get_krx_summary_raw() # 최신 수급/금리용 (Snapshot)
    summary = f"### [ KRX 시장 지표 ({period_name} 변동) ]\n"

    try:
        from pykrx import stock
        now = get_now_kst()
        target_date = now.strftime("%Y%m%d")
        if now.hour < 9: target_date = (now - timedelta(days=1)).strftime("%Y%m%d")
        start_dt = (now - timedelta(days=fetch_days)).strftime("%Y%m%d")

        for code, name in [("1001", "KOSPI"), ("2001", "KOSDAQ")]:
            df = stock.get_index_ohlcv(start_dt, target_date, code)
            if not df.empty and len(df) >= 2:
                curr = float(df.iloc[-1]['종가'])
                prev_idx = comp_idx if len(df) >= abs(comp_idx) else 0
                prev = float(df.iloc[prev_idx]['종가'])
                
                diff = curr - prev
                pct = (diff / prev) * 100
                
                # 시계열 수치 추출 (최대 fetch_days 개)
                ts_values = [f"{float(val):,.2f}" for val in df['종가'].tolist()]
                ts_str = " -> ".join(ts_values)
                
                summary += f"- {name}: {curr:,.2f} ({pct:+.2f}% / {period_name} 변동)\n"
                summary += f"  └ 시계열(과거->현재): {ts_str}\n"
    except Exception as e:
        summary += f"⚠️ 지수 데이터 시계열 계산 중 오류: {e}\n"

    summary += f"- KOSPI 수급(순매수): 개인 {data.get('KOSPI_Individual',{}).get('val_str','0억')}, 외국인 {data.get('KOSPI_Foreigner',{}).get('val_str','0억')}, 기관 {data.get('KOSPI_Institution',{}).get('val_str','0억')}\n"
    summary += f"- KOSDAQ 수급(순매수): 개인 {data.get('KOSDAQ_Individual',{}).get('val_str','0억')}, 외국인 {data.get('KOSDAQ_Foreigner',{}).get('val_str','0억')}, 기관 {data.get('KOSDAQ_Institution',{}).get('val_str','0억')}\n"
    k3 = data.get('KR_3Y', {}).get('val_str', 'N/A')
    k10 = data.get('KR_10Y', {}).get('val_str', 'N/A')
    summary += f"- 국고채 금리: 3년물 {k3} | 10년물 {k10}\n"
    return summary

def get_krx_top_investors():
    """(통합) 3대 주체별 순매수 상위 및 공매도 보고서"""
    data = get_krx_summary_raw()
    if not data: return ""
    
    report = "### [ KOSPI 주체별 순매수 Top 10 ]\n"
    report += f"- 👤 개인: {data.get('KOSPI_Top_Individual', '데이터 없음')}\n"
    report += f"- 🌍 외인: {data.get('KOSPI_Top_Foreigner', '데이터 없음')}\n"
    report += f"- 🏢 기관: {data.get('KOSPI_Top_Institution', '데이터 없음')}\n"
    
    s_total = data.get('KOSPI_Short', {}).get('total', 'N/A')
    s_for = data.get('KOSPI_Short', {}).get('for', 'N/A')
    report += f"📊 공매도: 총 {s_total} (외인 {s_for})\n"

    report += "\n### [ KOSDAQ 주체별 순매수 Top 10 ]\n"
    report += f"- 👤 개인: {data.get('KOSDAQ_Top_Individual', '데이터 없음')}\n"
    report += f"- 🌍 외인: {data.get('KOSDAQ_Top_Foreigner', '데이터 없음')}\n"
    report += f"- 🏢 기관: {data.get('KOSDAQ_Top_Institution', '데이터 없음')}\n"
    
    s_total_kq = data.get('KOSDAQ_Short', {}).get('total', 'N/A')
    s_for_kq = data.get('KOSDAQ_Short', {}).get('for', 'N/A')
    report += f"📊 공매도: 총 {s_total_kq} (외인 {s_for_kq})\n"
    return report

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


def get_global_market_data(r_type="daily"):
    """yfinance를 통해 글로벌 시장 데이터를 수집합니다."""
    if not yf: return "⚠️ yfinance 모듈이 설치되지 않았습니다."

    end_dt = get_now_kst()
    
    # 🎯 보고서 유형별 기간 및 비교 시점 설정
    if r_type == 'daily': 
        days = 7
        comp_idx = -2 # 전일 대비
    elif r_type == 'weekly': 
        days = 14
        comp_idx = -6 # 1주 전 대비 (약 5거래일)
    else: 
        days = 60
        comp_idx = -21 # 1달 전 대비 (약 20거래일)
    
    start_dt = end_dt - timedelta(days=days + 5) # 여유 있게 조회
    
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
    report = f"### [ 🌍 글로벌 시장 데이터 ({r_type.upper()} 기준 변동) ]\n"
    
    try:
        df = yf.download(all_symbols, start=start_dt.strftime('%Y-%m-%d'), end=end_dt.strftime('%Y-%m-%d'), progress=False)['Close']
        for cat_name, items in tickers.items():
            report += f"#### {cat_name}\n"
            for sym, name in items.items():
                try:
                    if sym in df.columns:
                        series = df[sym].dropna()
                        if len(series) < 2: continue
                        
                        curr = float(series.iloc[-1])
                        target_idx = comp_idx if len(series) >= abs(comp_idx) else 0
                        prev = float(series.iloc[target_idx])
                        
                        chg_pct = ((curr - prev) / prev) * 100
                        
                        # 시계열 수치 추출 (최대 days 개)
                        ts_values = [f"{float(val):,.2f}" for val in series.tolist()[-days:]]
                        ts_str = " -> ".join(ts_values)
                        
                        report += f"- **{name}**: {curr:,.2f} ({chg_pct:+.2f}%, {days}일 범위: {series.min():,.2f}~{series.max():,.2f})\n"
                        report += f"  └ 시계열(과거->현재): {ts_str}\n"
                except: continue
            report += "\n"
        return report
    except Exception as e:
        return f"⚠️ 글로벌 데이터 수집 실패: {e}"

def is_kr_market_open():
    now = get_now_kst()
    if now.weekday() >= 5: return False # 토/일 제외
    
    # 09:00 ~ 15:30 (15시 30분)
    current_minutes = now.hour * 60 + now.minute
    if not (540 <= current_minutes <= 930): return False
    
    try:
        from pykrx import stock
        today_str = now.strftime("%Y%m%d")
        b_days = stock.get_business_days_dates(today_str, today_str)
        if len(b_days) == 0: return False
    except: pass
    return True

def is_us_market_open():
    now = get_now_kst()
    current_minutes = now.hour * 60 + now.minute
    # 넓은 썸머타임/표준시 구간 포괄: 22:30 ~ 06:00
    is_open_time = (current_minutes >= 1350) or (current_minutes <= 360) 
    if not is_open_time: return False
    
    if now.weekday() == 6: return False # 일요일 전체 휴장 (KST)
    if now.weekday() == 0 and current_minutes <= 360: return False # 월요일 새벽 (미국 일요일)
    if now.weekday() == 5 and current_minutes >= 1350: return False # 토요일 밤 (미국 토/일)
    return True

def get_global_financials_raw(ignore_cache=False, fetch_type="all"):
    """대시보드용 글로벌 지수, 환율, 원자재, 금리 데이터를 통합 수집합니다."""
    print(f"🔍 [DEBUG] get_global_financials_raw 진입 (fetch_type: {fetch_type})")
    
    cache_dir = os.path.join(BASE_PATH, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "global_financials.json")
    
    results = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                results = json.load(f)
            if not ignore_cache and time.time() - os.path.getmtime(cache_path) < 600:
                print("🔍 [DEBUG] get_global_financials_raw 캐시 사용")
                return results
        except: pass

    if not yf: return results
    
    tickers = {
        "USD/KRW": "KRW=X", "USD/JPY": "JPY=X", 
        "WTI": "CL=F", "Gold": "GC=F", "Bitcoin": "BTC-USD"
    }
    if fetch_type == "all":
        tickers.update({
            "S&P500": "^GSPC", "Dow Jones": "^DJI", "Nasdaq": "^IXIC", "VIX": "^VIX",
            "US10Y": "^TNX", "US2Y": "^IRX"
        })
    
    try:
        print("🔍 [DEBUG] get_global_financials_raw yfinance 데이터 다운로드 시작")
        end_dt = get_now_kst()
        start_dt = end_dt - timedelta(days=7)
        df = yf.download(list(tickers.values()), start=start_dt.strftime('%Y-%m-%d'), end=end_dt.strftime('%Y-%m-%d'), progress=False)['Close']

        for name, sym in tickers.items():
            if sym in df.columns:
                series = df[sym].dropna()
                if len(series) >= 2:
                    curr = float(series.iloc[-1])
                    prev = float(series.iloc[-2])
                    diff = curr - prev
                    pct = (diff / prev) * 100
                    results[name] = {
                        "price": curr, "diff": diff, "pct": pct,
                        "val_str": f"{curr:,.2f}",
                        "delta_str": f"{diff:+.2f} ({pct:+.2f}%)"
                    }
        
        # 캐시 저장 (non_equities 모드일 때 기존 주식 데이터 보존)
        if fetch_type != "all" and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                existing.update(results)  # 새 데이터로 덮어쓰되, 기존 주식 데이터는 보존
                results = existing
            except: pass
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False)
        print("🔍 [DEBUG] get_global_financials_raw 캐시 저장 완료")
    except Exception as e:
        print(f"⚠️ get_global_financials_raw 다운로드 중 오류: {e}")
        pass
        
    return results

def get_fed_liquidity_raw():
    """FRED 데이터 원본 리스트를 반환합니다. (Dashboard용)"""
    print("🔍 [DEBUG] get_fed_liquidity_raw 진입")
    # 🎯 [NEW] 캐싱 설정 (24시간 - 하루 1회)
    cache_dir = os.path.join(BASE_PATH, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    print("🔍 [DEBUG] get_fed_liquidity_raw 캐시 경로:", cache_dir)
    cache_path = os.path.join(cache_dir, "fed_liquidity.json")
    
    if os.path.exists(cache_path):
        try:
            if time.time() - os.path.getmtime(cache_path) < 3600: # 1시간 주기로 갱신 변경
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except: pass

    results = []
    
    # (Series ID, 이름, 단위변환계수, 단위문자열)
    indicators = [
        ("RRPONTSYD", "RRP", 1.0, "B$"),
        ("WRESBAL", "Reserves", 0.001, "B$"), # 백만 단위 -> B(Billion) 단위 변환
        ("WTREGEN", "TGA", 0.001, "B$"),
        ("M2SL", "M2", 1.0, "B$"),
        ("CPIAUCSL", "CPI", 1.0, "Idx"),      # 소비자물가지수
        ("UNRATE", "Unemployment", 1.0, "%"), # 실업률
        ("FEDFUNDS", "FedRate", 1.0, "%"),    # 기준금리
        ("BAMLH0A0HYM2", "HighYield", 1.0, "%"), # 하이일드 스프레드
        ("T10YIE", "ExpInf", 1.0, "%"),       # 기대인플레이션 (10년)
        ("GDPNOW", "GDPNow", 1.0, "%")        # 애틀란타 연은 GDP Now
    ]
    
    base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
    try:
        print("🔍 [DEBUG] get_fed_liquidity_raw FRED 데이터 다운로드 시작")
        for code, name, scale, unit in indicators:
            try:
                # FRED는 별도 API 키 없이 CSV 직접 다운로드 가능
                res = requests.get(base_url.format(code), timeout=5)
                if res.status_code == 200:
                    # 데이터프레임 변환
                    df = pd.read_csv(io.StringIO(res.text), index_col=0, parse_dates=True)
                    if not df.empty:
                        series = df.iloc[:, 0].dropna()
                        if series.empty: continue
                        
                        curr_val = float(series.iloc[-1]) * scale
                        curr_date = series.index[-1].strftime("%Y-%m-%d")
                        
                        # 🎯 1년 전 데이터 계산 (약 252 거래일 or 12개월)
                        idx_1y = -252 if len(series) > 252 else (-12 if len(series) > 12 else 0)
                        val_1y = float(series.iloc[idx_1y]) * scale
                        diff_1y = curr_val - val_1y
                        pct_1y = (diff_1y / val_1y) * 100 if val_1y != 0 else 0.0
                        
                        # 전조(Previous) 대비 증감
                        diff_str = "-"
                        if len(series) > 1:
                            prev_val = float(series.iloc[-2]) * scale
                            diff = curr_val - prev_val
                            diff_str = f"{diff:+.1f}"
                        
                        # 두달치(최대 60일) 데이터를 추출하여 5일 간격으로 샘플링
                        sixty_days_ago = series.index[-1] - pd.Timedelta(days=60)
                        recent_series = series.loc[series.index >= sixty_days_ago]
                        ts_values = [f"{float(v * scale):.2f}" for v in recent_series.iloc[::5]]

                        # 단위에 따른 포맷팅 미세 조정
                        fmt = ",.2f" if unit in ["%", "Idx", "B$"] else ",.1f"
                        results.append({
                            "name": name, "value": curr_val, "diff": diff, 
                            "diff_str": diff_str, "date": curr_date,
                            "val_str": f"{curr_val:{fmt}}{unit}",
                            "delta_str": f"{diff_str} (직전)",
                            "diff_1y": diff_1y,
                            "pct_1y": pct_1y,
                            "ts_values": ts_values
                        })
                print(f"🔍 [DEBUG] get_fed_liquidity_raw {name} 로드 완료")
            except Exception as e:
                continue
                
        # 캐시 저장
        if results:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False)
        print("🔍 [DEBUG] get_fed_liquidity_raw 캐시 저장")
    except: pass
    
    return results

def get_fed_liquidity_data():
    """FRED 데이터를 보고서 문자열 형태로 반환합니다."""
    raw_data = get_fed_liquidity_raw()
    summary = "### [ 🏦 연준(Fed) 거시/유동성 지표 ]\n"
    try:
        for item in raw_data:
            ts_str = ", ".join(item.get('ts_values', []))
            summary += f"- **{item['name']}**: {item['val_str']} (직전: {item['diff_str']} | 1년 변동: {item['pct_1y']:+.1f}%) | 최근 두달치 추이: [{ts_str}]\n"
        return summary + "\n"
    except Exception as e:
        return f"⚠️ 연준 데이터 수집 중 에러: {e}\n"

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
    fed_data = get_fed_liquidity_data() # 연준 지표 추가
    
    # KRX 데이터 공통 수집 (주간/월간 보고서에도 현재 시장 상황 반영)
    market_summary = get_krx_market_data(r_type)

    if r_type == "daily":
        print(f"🔍 [Daily] 데이터 수집 (KRX 지표 & 뉴스 필터링) 시작...")
        top_purchases = get_krx_top_investors()
        
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
                        # scraper.py와 동일한 MD5 해시 기반 중복 방지
                        import hashlib
                        clean_key = hashlib.md5(title.encode()).hexdigest()[:16]
                        if clean_key not in seen_keys:
                            seen_keys.add(clean_key)
                            summary = news_data.get("summary", "").strip()
                            if summary and summary != "내용 없음":
                                raw_news_list.append(f"[{pub_dt_str[5:16]}] {title} — {summary[:200]}")
                            else:
                                raw_news_list.append(f"[{pub_dt_str[5:16]}] {title}")
                        if len(raw_news_list) >= news_count: break
                except: continue
        
        news_ctx = f"### [ 금일 주요 뉴스 {len(raw_news_list)}선 ]\n" + "\n".join([f"- {t}" for t in raw_news_list])
        return (f"{market_summary}\n{global_data}\n{fed_data}\n{top_purchases}\n\n{news_ctx}", "일간(Daily)")
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
            
        return f"{source_docs}\n\n{market_summary}\n{global_data}\n{fed_data}", label

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
        
        base_prompt = REPORT_PROMPTS["daily"]["base_prompt"]
        specific_guideline = REPORT_PROMPTS["daily"]["specific_guideline"]
        structure_instruction = REPORT_PROMPTS["daily"]["structure_instruction"]
        
    elif r_type == "weekly":
        # 주간: 현상 원인 기록 (지난 주간 리포트 참조)
        past_weekly = get_past_reports('weekly', 1)
        historical_context = f"### [ 지난 주간 리포트 (비교용) ]\n{past_weekly}"
        
        base_prompt = REPORT_PROMPTS["weekly"]["base_prompt"]
        specific_guideline = REPORT_PROMPTS["weekly"]["specific_guideline"]
        structure_instruction = REPORT_PROMPTS["weekly"]["structure_instruction"]
        
    else: # monthly
        # 월간: 구조적 변화 기록 (지난 월간 리포트 참조)
        past_monthly = get_past_reports('monthly', 1)
        historical_context = f"### [ 지난 월간 리포트 (비교용) ]\n{past_monthly}"
        
        base_prompt = REPORT_PROMPTS["monthly"]["base_prompt"]
        specific_guideline = REPORT_PROMPTS["monthly"]["specific_guideline"]
        structure_instruction = REPORT_PROMPTS["monthly"]["structure_instruction"]

    analysis_guideline = f"### [ {r_type} 분석 지침 ]\n{specific_guideline}"

    system_prompt = (
        f"현재 임무: {r_type} 투자 보고서 작성\n"
        f"기준 시각: {now_kst.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"당신은 {base_prompt}이며, 아래 지침을 준수해야 합니다.\n\n"
        f"{analysis_guideline}\n\n"
        f"--- [ 중요 사항 ] ---\n"
        f"* 입력된 시장 데이터(KOSPI, 글로벌 지수 등)에는 '시계열(과거->현재)' 변화 흐름이 화살표(->)로 나열되어 있습니다.\n"
        f"* 이 시계열 추이(Time-series)를 분석하여 해당 기간(7일, 14일, 60일) 동안의 추세(하락 후 반등, 지속 상승 등)를 반드시 파악하고 보고서에 반영하십시오.\n\n"
        f"--- [ 참고 자료 (Context) ] ---\n{historical_context}\n\n"
        f"--- [ 최종 지시 ] ---\n"
        f"제공된 시계열 입력 데이터(Input Data)를 바탕으로 보고서를 작성하세요.\n"
        f"{structure_instruction}"
    )
    
    return get_ai_summary(title=f"{date.today()} {r_type.upper()} 보고서", content=input_content, system_instruction=system_prompt, role="analyst", custom_config=config_data)