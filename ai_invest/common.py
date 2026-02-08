
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
 SYNCHRONOUS


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
    base_dir = "/share/ai_analyst/reports"
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
    base_dir = "/share/ai_analyst/reports"
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
            "prompt": "당신은 전문 투자 전략가입니다. 지표와 뉴스를 분석하여 투자 전략을 제시하세요."
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
