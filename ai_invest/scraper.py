import feedparser
import time
import os
import json
import hashlib

# --- 경로 설정 ---
CONFIG_PATH = "/share/ai_analyst/rss_config.json"
SAVE_PATH = "/share/ai_analyst/pending"

def get_file_hash(text):
    """중복 수집 방지를 위한 해시 생성"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def save_file(entry, feed_name):
    os.makedirs(SAVE_PATH, exist_ok=True)
    # 제목 기반 해시로 파일명 생성
    title_hash = hashlib.md5(entry.title.encode('utf-8')).hexdigest()
    fname = f"{SAVE_PATH}/{title_hash}.txt"
    
    if os.path.exists(fname): return

    # 💡 RSS 날짜가 없으면 현재 시간(2026-02-02)을 기본값으로 사용
    pub_date = entry.get('published') 
    if not pub_date:
        pub_date = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

    try:
        with open(fname, "w", encoding="utf-8") as f:
            # ⚠️ 아래 순서를 절대 바꾸지 마세요 (app.py의 load_pending_files와 직결됨)
            f.write(f"제목: {entry.title}\n")
            f.write(f"링크: {entry.link}\n")
            f.write(f"날짜: {pub_date}\n") # 💡 3번째 줄에 날짜 기록
            f.write(f"요약: {entry.get('summary', '내용 없음')}")
    except Exception as e:
        print(f"❌ 파일 저장 실패: {e}")



def check_logic(text, inc_list, exc_list):
    """필터링 로직: 제외어 포함 시 탈락, 포함어 설정 시 포함되어야 통과"""
    text = text.lower()
    # 1. 제외 필터 (하나라도 걸리면 바로 탈락)
    if any(x in text for x in exc_list if x):
        return False
    # 2. 포함 필터 (리스트가 비어있지 않을 때만 체크)
    if inc_list:
        if not any(i in text for i in inc_list if i):
            return False
    return True

def cleanup_old_files(retention_days):
    """설정된 보관 기간보다 오래된 파일을 삭제합니다."""
    if not os.path.exists(SAVE_PATH):
        return
        
    current_time = time.time()
    # 1일 = 86400초
    seconds_threshold = retention_days * 86400
    
    deleted_count = 0
    for filename in os.listdir(SAVE_PATH):
        file_path = os.path.join(SAVE_PATH, filename)
        
        # 파일 수정 시간 체크
        if os.path.isfile(file_path) and filename.endswith(".txt"):
            file_age = os.path.getmtime(file_path)
            if (current_time - file_age) > seconds_threshold:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"❌ 파일 삭제 실패 ({filename}): {e}")
                    
    if deleted_count > 0:
        print(f"🧹 보관 기간 만료로 {deleted_count}개의 뉴스 파일을 삭제했습니다. (기준: {retention_days}일)")

def start_scraping():
    print("🚀 뉴스 수집 엔진 가동 중 (전역 필터링 및 자동 삭제 시스템)...")
    
    while True:
        # 1. 설정 및 전역 필터 로드 (기본 변수명 config 유지)
        config = {"feeds": [], "update_interval": 10, "global_include": "", "global_exclude": "", "retention_days": 7}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config.update(json.load(f))
            except Exception as e:
                print(f"⚠️ 설정 파일 로드 오류: {e}")
        
        interval = config.get("update_interval", 10)
        retention_days = config.get("retention_days", 7)
        
        # [자동 삭제 로직 실행]
        cleanup_old_files(retention_days)
        
        # 2. 전역 필터 키워드 리스트화
        g_inc = [k.strip().lower() for k in config.get('global_include', "").split(",") if k.strip()]
        g_exc = [k.strip().lower() for k in config.get('global_exclude', "").split(",") if k.strip()]

        feeds = config.get("feeds", [])
        if not feeds:
            time.sleep(60); continue

        # 3. 개별 피드 순회 및 수집
        for feed in feeds:
            try:
                parsed = feedparser.parse(feed['url'])
                l_inc = [k.strip().lower() for k in feed.get('include', "").split(",") if k.strip()]
                l_exc = [k.strip().lower() for k in feed.get('exclude', "").split(",") if k.strip()]
                
                for entry in parsed.entries[:50]:
                    # 제목 기준으로 필터링 (사용자 요청 반영)
                    check_text = entry.title
                    
                    if not check_logic(check_text, g_inc, g_exc): continue
                    if not check_logic(check_text, l_inc, l_exc): continue
                    
                    save_file(entry, feed['name'])
            except: continue
        
        print(f"💤 {interval}분 후 업데이트 확인 및 파일 정리 예정...")
        time.sleep(interval * 60)

# --- [5. 메인 루프] ---
if __name__ == "__main__":
    # 💡 마지막 성공 데이터를 저장할 메모리 공간 (초기화)
    last_prices = {} 
    last_collect_time, last_news_time, last_auto_report_date = 0, 0, ""
# 🎯 [핵심] 수집기를 켰을 때 오늘 날짜를 미리 넣어 정시 가동을 준비합니다.
    last_auto_report_date = datetime.now().strftime("%Y-%m-%d")
    print(f"🚀 [AI Analyst V3] 통합 수집기 가동 시작")

# 🎯 [신규] 설정 파일 자동 생성 로직
    if not os.path.exists(CONFIG_PATH):
        print(f"🛠️ 설정 파일이 없습니다. 기본 설정을 생성합니다: {CONFIG_PATH}")
        default_config = {
            "report_auto_gen": True,         # 기본적으로 자동 생성 켬
            "report_gen_time": "08:00",      # 기본 아침 8시
            "report_news_count": 100,        # 뉴스 100개
            "update_interval": 10,           # 10분 주기
            "feeds": [],                     # 비어있는 피드 리스트
            "analyst_model": {               # 5070 Ti에 최적화된 기본 모델 설정
                "name": "openai/gpt-oss-20b",
                "url": "http://192.168.1.105:11434/v1", 
                "prompt": "당신은 전문 투자 전략가입니다. 지표와 뉴스를 분석하여 수익 전략을 제시하세요."
            }
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4, ensure_ascii=False)
        print(f"✅ 기본 설정 파일 생성 완료.")

    while True:
        try:
            now, current_ts = datetime.now(), time.time()
            # 최신 설정값 로드 (보고서 생성 시간, 자동 생성 여부 등)
            with open(CONFIG_PATH, "r", encoding="utf-8") as f: 
                current_config = json.load(f)

            # ---------------------------------------------------------
            # 🎯 [T1: 자동 보고서 로직 복구]
            # ---------------------------------------------------------
            auto_gen_enabled = current_config.get("report_auto_gen", False)
            target_time_str = current_config.get("report_gen_time", "08:00")
            today_date_str = now.strftime("%Y-%m-%d")
            current_time_str = now.strftime("%H:%M")

            # 1. 자동 생성 활성화 여부 확인
            # 2. 현재 시간이 설정된 시간(HH:MM)을 지났는지 확인
            # 3. 오늘 이미 생성했는지 확인 (중복 생성 방지)
            current_time_str = now.strftime("%H:%M")
            
            # 1. 자동 생성이 켜져 있고
            # 2. 지금 시각이 설정한 시각과 정확히 일치하며 (또는 1분 이내 루프 시점)
            # 3. 오늘 보고서를 발행한 적이 없을 때만 실행
            if auto_gen_enabled and current_time_str == target_time_str and last_auto_report_date != today_date_str:
                print(f"🤖 [{now.strftime('%H:%M:%S')}] 정시 보고서 생성 시각 도래: 분석 시작...")
                
                success = generate_auto_report(current_config)
                
                if success:
                    print(f"✅ [{now.strftime('%H:%M:%S')}] 정기 보고서 박제 완료.")
                    last_auto_report_date = today_date_str
                else:
                    print(f"⚠️ [{now.strftime('%H:%M:%S')}] 생성 실패 (1분 뒤 재시도)")
            # ---------------------------------------------------------
# [T3: 뉴스 수집] (수집 주기 설정값 반영)
            update_interval_sec = current_config.get("update_interval", 10) * 60
            if current_ts - last_news_time >= update_interval_sec:
                # print(f"📰 뉴스 수집 엔진 가동...")
                # fetch_all_rss_feeds() 함수 등 뉴스 수집 로직 호출
                last_news_time = current_ts
                
        except Exception as e: 
            print(f"❌ 루프 에러: {e}")
        time.sleep(60)
