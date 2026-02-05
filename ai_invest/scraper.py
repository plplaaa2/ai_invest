import feedparser
import time
import os
import json
import hashlib
import requests
from datetime import datetime, timedelta, date

# --- 경로 설정 (기존 유지) ---
CONFIG_PATH = "/share/ai_analyst/rss_config.json"
PENDING_PATH = "/share/ai_analyst/pending"
REPORTS_BASE_DIR = "/share/ai_analyst/reports"

processed_titles = set()

# 필수 디렉토리 생성 보장
os.makedirs(PENDING_PATH, exist_ok=True)
os.makedirs(REPORTS_BASE_DIR, exist_ok=True)

def save_file(entry, feed_name):
    """중복을 제거하고 뉴스를 파일로 저장합니다."""
    global processed_titles    
    # 1. 제목 정제 및 중복 판단용 키 생성
    title = entry.title.strip()
    summary = entry.get('summary', '내용 없음')
    current_content_len = len(title) + len(summary)
    # 공백과 특정 문구를 제거한 앞 18자로 유사도 체크
    clean_key = title.replace("[특징주]", "").replace("[속보]", "").replace(" ", "")[:18]
    
    # 2. 2중 중복 체크 (메모리 캐시 or 물리 파일 존재 여부)
    title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()
    fname = f"{PENDING_PATH}/{title_hash}.txt"
    
# 🎯 중복 판단 시 '덮어쓰기' 전략 도입
    if clean_key in processed_titles or os.path.exists(fname):
        # 이미 파일이 있다면 기존 파일의 크기를 확인합니다.
        if os.path.exists(fname):
            existing_size = os.path.getsize(fname)
            # 💡 새 기사가 기존 기사보다 정보량(용량)이 더 많을 때만 교체합니다.
            if current_content_len > existing_size:
                pass # 아래 저장 로직으로 진행
            else:
                return False # 기존 기사가 더 알차므로 스킵
        else:
            return False # 메모리 캐시에만 있는 경우도 스킵

    pub_date = entry.get('published') or datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    # 4. 파일 쓰기
    try:
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"제목: {title}\n")
            f.write(f"링크: {entry.link}\n")
            f.write(f"날짜: {pub_date}\n")
            f.write(f"요약: {entry.get('summary', '내용 없음')}")
        
        processed_titles.add(clean_key)
        return True
    except Exception as e:
        print(f"❌ 파일 저장 실패: {e}")
        return False

def check_logic(text, inc_list, exc_list):
    """필터링 로직: 제외어 포함 시 탈락, 포함어 설정 시 포함되어야 통과"""
    text = text.lower()
    if any(x in text for x in exc_list if x):
        return False
    if inc_list:
        if not any(i in text for i in inc_list if i):
            return False
    return True

def cleanup_old_files(retention_days):
    """설정된 기간보다 오래된 파일 및 메모리 캐시 삭제"""
    global processed_titles
    if not os.path.exists(PENDING_PATH): return
    
    current_time = time.time()
    seconds_threshold = retention_days * 86400
    deleted_count = 0
    
    for filename in os.listdir(PENDING_PATH):
        file_path = os.path.join(PENDING_PATH, filename)
        if os.path.isfile(file_path) and filename.endswith(".txt"):
            if (current_time - os.path.getmtime(file_path)) > seconds_threshold:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except: pass
    
    # 파일 삭제 시 메모리 캐시도 함께 비워 시스템을 가볍게 유지
    processed_titles.clear()
    if deleted_count > 0:
        print(f"🧹 {deleted_count}개의 뉴스 파일을 정리하고 중복 필터를 초기화했습니다.")

def start_scraping():
    print("🚀 뉴스 수집 엔진 가동 중 (전역 필터링 및 2중 중복 제거 시스템)...")
    
    while True:
        # 1. 설정 로드
        config = {"feeds": [], "update_interval": 10, "retention_days": 7}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config.update(json.load(f))
            except: pass
        
        interval = config.get("update_interval", 10)
        cleanup_old_files(config.get("retention_days", 7))
        
        g_inc = [k.strip().lower() for k in config.get('global_include', "").split(",") if k.strip()]
        g_exc = [k.strip().lower() for k in config.get('global_exclude', "").split(",") if k.strip()]

        # 2. 피드 순회
        feeds = config.get("feeds", [])
        total_found, new_saved = 0, 0

        for feed in feeds:
            try:
                parsed = feedparser.parse(feed['url'])
                l_inc = [k.strip().lower() for k in feed.get('include', "").split(",") if k.strip()]
                l_exc = [k.strip().lower() for k in feed.get('exclude', "").split(",") if k.strip()]
                
                for entry in parsed.entries[:50]:
                    total_found += 1
                    if not check_logic(entry.title, g_inc, g_exc): continue
                    if not check_logic(entry.title, l_inc, l_exc): continue
                    
                    if save_file(entry, feed['name']):
                        new_saved += 1
            except: continue
        
        # 3. 실시간 보고 로그
        if total_found > 0:
            print(f"📊 수집 현황: 발견 {total_found}개 | 신규 {new_saved}개 | 중복/필터 제외 {total_found - new_saved}개")
        
        print(f"💤 {interval}분 후 다시 확인합니다.")
        time.sleep(interval * 60)

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
    if os.path.exists(PENDING_PATH):
        pending_files = sorted(os.listdir(PENDING_PATH), reverse=True)[:news_count]
        for f_name in pending_files:
            try:
                with open(os.path.join(PENDING_PATH, f_name), "r", encoding="utf-8") as file:
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
        
# --- 4. 메인 루프 가동 ---

if __name__ == "__main__":
    last_news_time, last_auto_report_date = 0, datetime.now().strftime("%Y-%m-%d")
    print(f"🚀 [AI Analyst Engine] 가동 시작")

    while True:
        try:
            now, current_ts = datetime.now(), time.time()
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f: 
                    current_config = json.load(f)
            else: continue

            # 🎯 [T1] 자동 보고서 생성 (지표 로드 로직 삭제)
            auto_gen_enabled = current_config.get("report_auto_gen", False)
            target_time_str = current_config.get("report_gen_time", "08:00")
            today_date_str = now.strftime("%Y-%m-%d")
            
            if auto_gen_enabled and now.strftime("%H:%M") == target_time_str and last_auto_report_date != today_date_str:
                if generate_auto_report(current_config): 
                    last_auto_report_date = today_date_str

            # 🎯 [T2] 뉴스 수집 및 정제
            interval_sec = current_config.get("update_interval", 10) * 60
            if current_ts - last_news_time >= interval_sec:
                cleanup_old_files(current_config.get("retention_days", 7))
                
                # RSS 피드 순회 수집
                feeds = current_config.get("feeds", [])
                g_inc = [k.strip().lower() for k in current_config.get('global_include', "").split(",") if k.strip()]
                g_exc = [k.strip().lower() for k in current_config.get('global_exclude', "").split(",") if k.strip()]

                for feed in feeds:
                    try:
                        parsed = feedparser.parse(feed['url'])
                        l_inc = [k.strip().lower() for k in feed.get('include', "").split(",") if k.strip()]
                        l_exc = [k.strip().lower() for k in feed.get('exclude', "").split(",") if k.strip()]
                        for entry in parsed.entries[:50]:
                            if not check_logic(entry.title, g_inc, g_exc): continue
                            if not check_logic(entry.title, l_inc, l_exc): continue
                            save_file(entry, feed['name'])
                    except: continue
                last_news_time = current_ts
                
        except Exception as e: 
            print(f"❌ 루프 에러: {e}")
        time.sleep(60)






