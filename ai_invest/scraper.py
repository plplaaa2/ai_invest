import feedparser
import time
import os
import json
import hashlib
import requests
from datetime import datetime, timedelta, date

# --- 경로 설정 (기존 유지) ---
CONFIG_PATH = "/share/ai_analyst/rss_config.json"
SAVE_PATH = "/share/ai_analyst/pending"
REPORTS_BASE_DIR = "/share/ai_analyst/reports"

def get_file_hash(text):
    """중복 수집 방지를 위한 해시 생성"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def save_file(entry, feed_name):
    os.makedirs(SAVE_PATH, exist_ok=True)
    title_hash = hashlib.md5(entry.title.encode('utf-8')).hexdigest()
    fname = f"{SAVE_PATH}/{title_hash}.txt"
    
    if os.path.exists(fname): return

    pub_date = entry.get('published') 
    if not pub_date:
        pub_date = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    try:
        with open(fname, "w", encoding="utf-8") as f:
            # ⚠️ app.py의 load_pending_files와 직결된 저장 순서 준수
            f.write(f"제목: {entry.title}\n")
            f.write(f"링크: {entry.link}\n")
            f.write(f"날짜: {pub_date}\n")
            f.write(f"요약: {entry.get('summary', '내용 없음')}")
    except Exception as e:
        print(f"❌ 파일 저장 실패: {e}")

def check_logic(text, inc_list, exc_list):
    text = text.lower()
    if any(x in text for x in exc_list if x): return False
    if inc_list:
        if not any(i in text for i in inc_list if i): return False
    return True

def cleanup_old_files(retention_days):
    """설정된 보관 기간보다 오래된 뉴스 파일 삭제"""
    if not os.path.exists(SAVE_PATH): return
    current_time = time.time()
    seconds_threshold = retention_days * 86400
    deleted_count = 0
    for filename in os.listdir(SAVE_PATH):
        file_path = os.path.join(SAVE_PATH, filename)
        if os.path.isfile(file_path) and filename.endswith(".txt"):
            if (current_time - os.path.getmtime(file_path)) > seconds_threshold:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except: continue
    if deleted_count > 0:
        print(f"🧹 뉴스 파일 {deleted_count}개 삭제 완료 (기준: {retention_days}일)")

def load_historical_contexts():
    """과거 리포트 맥락 로드 (RAG 기능)"""
    dir_map = {
        'YEARLY_STRATEGY': '04_yearly/latest.txt',
        'MONTHLY_THEME': '03_monthly/latest.txt',
        'WEEKLY_MOMENTUM': '02_weekly/latest.txt',
        'DAILY_LOG': '01_daily/latest.txt'
    }
    context_text = "### [ 역사적 맥락 참조 데이터 ]\n"
    for label, rel_path in dir_map.items():
        full_path = os.path.join(REPORTS_BASE_DIR, rel_path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
                if len(content.strip()) > 10:
                    context_text += f"\n<{label}>\n{content[:1000]}\n"
                else:
                    context_text += f"\n<{label}>: 데이터 비어 있음.\n"
        else:
            context_text += f"\n<{label}>: 이전 기록 없음. 현재 뉴스 위주로 분석하십시오.\n"
    return context_text

def save_report_to_file(content, section_name):
    """AI 보고서 계층형 저장 및 정제"""
    subdir = {'daily': '01_daily', 'weekly': '02_weekly', 'monthly': '03_monthly'}.get(section_name.lower(), "05_etc")
    report_dir = os.path.join(REPORTS_BASE_DIR, subdir)
    os.makedirs(report_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    filepath = os.path.join(report_dir, f"{timestamp}_{section_name}.txt")
    
    with open(filepath, "w", encoding="utf-8") as f: f.write(content)
    with open(os.path.join(report_dir, "latest.txt"), "w", encoding="utf-8") as f: f.write(content)

    # 자동 정제
    purge_rules = {'01_daily': 7, '02_weekly': 30, '03_monthly': 365}
    if subdir in purge_rules:
        threshold = time.time() - (purge_rules[subdir] * 86400)
        for f in os.listdir(report_dir):
            if f == "latest.txt": continue
            f_p = os.path.join(report_dir, f)
            if os.path.isfile(f_p) and os.path.getmtime(f_p) < threshold:
                os.remove(f_p)
    return filepath

def generate_auto_report(config_data):
    """DB 없이 뉴스 및 과거 맥락만으로 보고서 생성"""
    if not os.path.exists(CONFIG_PATH): return False
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    historical_context = load_historical_contexts() 

    # 🎯 [뉴스 로드] DB 지표 로직 삭제됨
    news_count = config_data.get("report_news_count", 100)
    news_ctx = f"### [ 금일 최신 뉴스 {news_count}선 ]\n"
    if os.path.exists(SAVE_PATH):
        pending_files = sorted(os.listdir(SAVE_PATH), reverse=True)[:news_count]
        for f_name in pending_files:
            try:
                with open(os.path.join(SAVE_PATH, f_name), "r", encoding="utf-8") as file:
                    news_ctx += f"- {file.readline().strip()}\n"
            except: continue

    a_cfg = config_data.get("analyst_model", {})
    payload = {
        "model": a_cfg.get("name", "gpt-4o"),
        "messages": [
            {
                "role": "system", 
                "content": f"현재시각: {now_str}\n{a_cfg.get('prompt', '전문 전략가로서 분석하라.')}\n\n{historical_context}"
            },
            {
                "role": "user", 
                "content": f"아래 최신 뉴스의 흐름을 과거 맥락과 결합하여 오늘 리포트를 작성하라.\n\n{news_ctx}"
            }
        ], 
        "temperature": 0.3
    }

    try:
        url = f"{a_cfg.get('url').rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {a_cfg.get('key')}"} if a_cfg.get('key') else {}
        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        report_content = resp.json()['choices'][0]['message']['content']
        save_report_to_file(report_content, "daily") 
        print(f"[{now_str}] 🏛️ 뉴스 기반 자동 보고서 생성 완료")
        return True
    except Exception as e:
        print(f"🚨 [보고서 생성 중단] 원인: {str(e)}")
        return False

# --- [ 메인 루프 ] ---
if __name__ == "__main__":
    last_news_time, last_auto_report_date = 0, datetime.now().strftime("%Y-%m-%d")
    
    if not os.path.exists(CONFIG_PATH):
        print(f"🛠️ 기본 설정을 생성합니다: {CONFIG_PATH}")
        save_data({"report_auto_gen": True, "report_gen_time": "08:00", "report_news_count": 100, "update_interval": 10, "feeds": []})

    while True:
        try:
            now, current_ts = datetime.now(), time.time()
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f: current_config = json.load(f)
            else: continue

            # 🎯 자동 보고서 로직 (지표 로드 구문 삭제됨)
            auto_gen_enabled = current_config.get("report_auto_gen", False)
            target_time_str = current_config.get("report_gen_time", "08:00")
            today_date_str = now.strftime("%Y-%m-%d")
            
            if auto_gen_enabled and now.strftime("%H:%M") == target_time_str and last_auto_report_date != today_date_str:
                if generate_auto_report(current_config): last_auto_report_date = today_date_str

            # 🎯 뉴스 수집 엔진
            interval_sec = current_config.get("update_interval", 10) * 60
            if current_ts - last_news_time >= interval_sec:
                cleanup_old_files(current_config.get("retention_days", 7))
                # (여기에 실제 RSS 수집 루프 호출 추가 가능)
                last_news_time = current_ts
                
        except Exception as e: print(f"❌ 루프 에러: {e}")
        time.sleep(60)
