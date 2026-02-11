import hashlib
from common import *
from collections import deque
from difflib import SequenceMatcher

# 🎯 중복 제거를 위한 메모리 캐시
processed_titles = deque(maxlen=500)
SIMILARITY_THRESHOLD = 0.85 # 85% 이상 유사하면 중복으로 간주

def is_similar(a, b):
    """두 문자열의 유사도를 계산합니다."""
    return SequenceMatcher(None, a, b).ratio()

def load_recent_titles():
    """디스크에 있는 최신 뉴스 제목들을 메모리에 로드하여 재시작 시에도 중복 방지"""
    global processed_titles
    processed_titles.clear()
    
    if not os.path.exists(PENDING_PATH): return

    # 최신 파일 순으로 정렬 (JSON만)
    files = sorted([f for f in os.listdir(PENDING_PATH) if f.endswith(".json")], reverse=True)
    
    count = 0
    for filename in files:
        if count >= processed_titles.maxlen: break
        try:
            with open(os.path.join(PENDING_PATH, filename), 'r', encoding='utf-8') as f:
                data = json.load(f)
                t = data.get('title', '')
                if t:
                    # 저장 로직과 동일한 정규화
                    normalized = ''.join(filter(str.isalnum, t)).lower()
                    processed_titles.append(normalized)
                    count += 1
        except: continue
    
    if count > 0:
        print(f"📂 [Init] 기존 뉴스 {count}건을 중복 방지 캐시에 복구했습니다.")

def log_duplicate(title, feed_name):
    """중복된 뉴스 제목을 로그 파일에 기록합니다."""
    try:
        log_path = os.path.join(PENDING_PATH, "duplicate_news.log")
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now_str}] [{feed_name}] {title}\n")
    except: pass

def save_file(entry, feed_name, current_saved, current_total):
    """KST 역순 정렬 파일명 생성 및 상세 로그 기록 버전"""
    global processed_titles
    try:
        title = entry.title.strip()

        # 🎯 1. 유사도 기반 중복 검사
        # 강력한 정규화 (특수문자/공백 제거, 소문자화)
        normalized_title = ''.join(filter(str.isalnum, title)).lower()

        for old_title in processed_titles:
            if is_similar(normalized_title, old_title) > SIMILARITY_THRESHOLD:
                # print(f"⚠️  유사도 중복 뉴스 건너뛰기: {title}") # 디버깅 필요시 주석 해제
                log_duplicate(title, feed_name)
                return False

        # 🎯 2. 발행 시간 파싱 및 KST 변환
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            dt_obj = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc).astimezone(KST)
        else:
            dt_obj = get_now_kst()

        # 🎯 3. 파일명용 정렬 문자열 (YYYYMMDD_HHMMSS)
        dt_str = dt_obj.strftime('%Y%m%d_%H%M%S')

        # 🎯 4. 고유 파일명 결정 (시간 정보를 맨 앞으로)
        file_hash = hashlib.md5(title.encode()).hexdigest()[:6]
        filename = f"{dt_str}_{file_hash}.json"
        filepath = os.path.join(PENDING_PATH, filename)

        news_data = {
            "title": title,
            "pub_dt": dt_obj.strftime('%Y-%m-%d %H:%M:%S'), # KST 문자열 저장
            "source": feed_name,
            "summary": entry.get('summary', '내용 없음'),
            "link": entry.get('link', '')
        }

        with open(filepath, "w", encoding='utf-8') as f:
            json.dump(news_data, f, ensure_ascii=False, indent=2)

        # 🎯 5. 처리가 끝난 제목을 캐시에 추가 (정규화된 버전)
        processed_titles.append(normalized_title)
        return True
    except Exception as e:
        print(f"❌ [Scraper] 저장 에러 ({feed_name}): {e}")
        return False
        
        
def cleanup_old_files(retention_days):
    """설정된 기간보다 오래된 파일 및 메모리 캐시 삭제"""
    global processed_titles
    if not os.path.exists(PENDING_PATH): return
    
    current_time = time.time()
    seconds_threshold = retention_days * 86400
    deleted_count = 0
    log_cleaned = False
    
    for filename in os.listdir(PENDING_PATH):
        file_path = os.path.join(PENDING_PATH, filename)
        if not os.path.isfile(file_path): continue

        # 오래된 파일인지 확인
        is_old = (current_time - os.path.getmtime(file_path)) > seconds_threshold

        if is_old:
            # 1. 오래된 뉴스 파일(.json) 정리 (기존 .txt 오류 수정)
            if filename.endswith(".json"):
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except: pass
            # 2. 오래된 중복 로그 파일(.log) 정리
            elif filename == "duplicate_news.log":
                try:
                    os.remove(file_path)
                    log_cleaned = True
                except: pass
    
    # 캐시가 비워지면 중복 저장이 발생하므로, 파일 정리 후 캐시를 재구축합니다.
    load_recent_titles()
    
    if deleted_count > 0:
        print(f"🧹 {deleted_count}개의 오래된 뉴스 파일(.json)을 정리했습니다.")
    if log_cleaned:
        print(f"🧹 오래된 중복 뉴스 로그(duplicate_news.log)를 정리했습니다.")

def start_scraping():
    print("🚀 뉴스 수집 엔진 가동 중 (타임라인 보존 및 동적 중복 제거)...")
    
    # 시작 시 기존 파일 로드
    load_recent_titles()
    
    while True:
        # 1. 설정 및 필터링 키워드 로드
        config = {"feeds": [], "update_interval": 10, "retention_days": 7}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config.update(json.load(f))
            except: pass
        
        interval = config.get("update_interval", 10)
        cleanup_old_files(config.get("retention_days", 7))
        
        g_inc = config.get('global_include', "")
        g_exc = config.get('global_exclude', "")

        # 2. 피드 순회
        feeds = config.get("feeds", [])
        total_found, new_saved = 0, 0

        for feed in feeds:
            try:
                parsed = feedparser.parse(feed['url'])
                l_inc = feed.get('include', "")
                l_exc = feed.get('exclude', "")

                # 상위 50개 뉴스 확인
                feed_new = 0
                for entry in parsed.entries[:50]:
                    total_found += 1 # 발견 수 카운트 업
                    
                    if not is_filtered(entry.title, g_inc, g_exc, l_inc, l_exc): continue
                    
                    # 🎯 [핵심 수정] save_file 호출 시 현재 카운트 정보를 함께 전달합니다.
                    # new_saved + 1 은 '이번에 저장될 뉴스가 몇 번째인지'를 의미합니다.
                      # ✅ save_file 정의와 인자 개수 맞춤
                    if save_file(entry, feed['name'], new_saved + 1, total_found):
                        feed_new += 1
                        new_saved += 1
                        
                if feed_new > 0:
                    print(f"   └─ {feed['name']}: {feed_new}개 신규 확보")
                    
            except Exception as e:
                print(f"❌ {feed.get('name')} 수집 중 에러: {e}")                
                continue
        
        # 3. 전체 수집 완료 후 요약 로그
        now_str = datetime.now().strftime('%H:%M:%S')
        if total_found > 0:
            print(f"[{now_str}] 📊 사이클 종료: 발견 {total_found}개 | 신규 저장 {new_saved}개")
        
        time.sleep(interval * 60)

# --- [5. 메인 루프] ---
if __name__ == "__main__":
    start_scraping()