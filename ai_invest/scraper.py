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

if __name__ == "__main__":
    start_scraping()
