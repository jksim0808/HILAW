import requests
import json
import pandas as pd
import time
import re
from datetime import datetime
import pytz
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정 (넓은 화면 모드)
# ==========================================
st.set_page_config(page_title="한투 주도주 감시봇", layout="wide")

# 한국 표준시(KST) 타임존 정의
KST = pytz.timezone('Asia/Seoul')

# 세션 안전 초기화
def get_secret(key, default=""):
    if key in st.secrets:
        return st.secrets[key]
    return default

# ==========================================
# 2. 사이드바 - 인증키 제어 센터 (Secrets 자동 감지 포함)
# ==========================================
st.sidebar.header("🔑 Open API & 알림 설정")

# 한투 Key 설정
st.sidebar.subheader("1. 한국투자증권 인증")
sc_app_key = get_secret("APP_KEY")
sc_app_secret = get_secret("APP_SECRET")

user_app_key = st.sidebar.text_input("한투 App Key 입력", value=sc_app_key, type="password")
user_app_secret = st.sidebar.text_input("한투 App Secret 입력", value=sc_app_secret, type="password")

# 텔레그램 설정
st.sidebar.subheader("2. 텔레그램 알림")
sc_token = get_secret("TELEGRAM_TOKEN")
sc_chat_id = get_secret("CHAT_ID")

user_token = st.sidebar.text_input("텔레그램 봇 토큰 입력", value=sc_token, type="password")
user_chat_id = st.sidebar.text_input("내 채팅방 ID 입력", value=sc_chat_id)

APP_KEY = user_app_key
APP_SECRET = user_app_secret
URL_BASE = "https://openapi.koreainvestment.com:9443"

TELEGRAM_TOKEN = user_token
CHAT_ID = user_chat_id

# 📱 텔레그램 도움말 접이식 배치
with st.sidebar.expander("ℹ️ 텔레그램 연동방법"):
    st.markdown("""
    **1. 봇 토큰(TOKEN) 만들기**
    1. 텔레그램 **@BotFather** 검색 후 시작
    2. `/newbot` 입력 후 봇 이름 및 아이디 생성
    3. 발급된 **`Use this token...`** 뒤 문자열 복사 붙여넣기
    
    **2. 내 채팅방 ID 찾기**
    1. 방금 만든 봇 방에 들어가서 **[시작]** 누르기 (선톡 필수)
    2. **@userinfobot** 검색 후 시작하여 내 **`Id: 숫자`** 복사 붙여넣기
    """)

# ==========================================
# 3. 세션 상태(Session State) 초기화
# ==========================================
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set() 
if 'current_date' not in st.session_state:
    st.session_state['current_date'] = datetime.now(KST).strftime("%Y%m%d")
if 'detected_list' not in st.session_state:
    st.session_state['detected_list'] = []  
if 'clicked_stock' not in st.session_state:
    st.session_state.clicked_stock = None

# ==========================================
# 4. 핵심 백엔드 기능 함수들 (동기식 교체 및 안전 파싱)
# ==========================================
def get_access_token():
    if not APP_KEY or not APP_SECRET:
        return None
    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": APP_SECRET}
    try:
        res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body), timeout=5)
        if res.status_code == 200:
            return res.json().get("access_token")
    except Exception as e:
        st.error(f"토큰 발급 중 서버 연결 오류: {e}")
    return None

def send_telegram_msg_sync(token, chat_id, text):
    """[동기식 연동] Streamlit 프로세스 락 현상을 완벽하게 방지하는 동기 통신 모듈"""
    if not token or not chat_id:
        return
    url = f"https://api.telegram.com/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

def check_market_time():
    now = datetime.now(KST)
    if now.weekday() >= 5: 
        return False
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time

def run_monitoring():
    today = datetime.now(KST).strftime("%Y%m%d")
    
    if today != st.session_state['current_date']:
        st.session_state['current_date'] = today
        st.session_state['sent_stocks'].clear()
        st.session_state['detected_list'] = []

    if not check_market_time():
        return

    try:
        token = get_access_token()
        if not token:
            st.warning("⚠️ 한투 API 키 및 보안 자격 증명이 활성화되지 않았습니다. 사이드바 설정을 확인하세요.")
            return

        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000" 
        }
        params = {"user_id": "", "seq": "", "data_cnt": "", "ranking_option": "1", "market_div": "0000", "industry_div": "0000"}
        
        res = requests.get(f"{URL_BASE}/uapi/domestic-stock/v1/ranking/trade-vol", headers=headers, params=params, timeout=10)
        data = res.json().get('output', [])
        
        if not data:
            return

        df = pd.DataFrame(data)
        df['stck_prpr'] = df['stck_prpr'].astype(int)
        df['stck_hgpr'] = df['stck_hgpr'].astype(int)
        df['stck_lwpr'] = df['stck_lwpr'].astype(int)
        df['acml_tr_pbmn'] = df['acml_tr_pbmn'].astype(int) // 100000000 
        
        df['volatility'] = ((df['stck_hgpr'] - df['stck_lwpr']) / df['stck_prpr'] * 100).round(2)
        
        # 필터: 거래대금 100억 이상 & 하루 변동폭 3% 이상
        target_stocks = df[(df['acml_tr_pbmn'] >= 100) & (df['volatility'] >= 3.0)]
        
        for _, row in target_stocks.iterrows():
            raw_code = row['mkte_ticker']
            # 불필요한 알파벳 머리말 제거 후 6자리 순수 숫자로 정제
            code = ''.join(filter(str.isdigit, raw_code))[:6]
            name = row['hts_kor_isnm']
            vol = row['volatility']
            price = row['stck_prpr']
            money = row['acml_tr_pbmn']
            detect_time = datetime.now(KST).strftime('%H:%M:%S')
            
            if code in st.session_state['sent_stocks']:
                continue
                
            msg = (
                f"🚀 [주도주 포착 - 변동폭 3% / 거래대금 100억 돌파] 🚀\n\n"
                f"📌 종목명: {name} ({code})\n"
                f"📈 현재가: {price:,}원\n"
                f"⚡ 당일 고저 변동폭: {vol}%\n"
                f"💰 현재 거래대금: {money:,}억"
            )
            
            # 동기식 텔레그램 연동 발송
            send_telegram_msg_sync(TELEGRAM_TOKEN, CHAT_ID, msg)
            st.session_state['sent_stocks'].add(code)
            
            new_item = {
                "포착 시간": detect_time,
                "종목코드": code,
                "종목명": name,
                "현재가(원)": f"{price:,}",
                "하루 변동폭": f"{vol}%",
                "거래대금(억)": money
            }
            st.session_state['detected_list'].insert(0, new_item)
            
    except Exception as e:
        print(f"데이터 조회 중 에러 발생: {e}")

# ==========================================
# 5. 프론트엔드 UI 및 대시보드 출력 구역
# ==========================================
st.title("🔥 한국투자증권 실시간 주도주 대시보드 (3% / 100억)")
st.caption("실시간 수급 모니터링 시스템 + 텔레그램 동기 연동형 관제 시스템")

col1, col2 = st.columns(2)
with col1:
    st.metric(label="현재 한국 표준시(KST)", value=datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
with col2:
    st.metric(label="오늘 레이더에 걸린 총 종목 수", value=f"{len(st.session_state['detected_list'])} 개")

st.markdown("---")
st.subheader("🎯 장중 실시간 주도주 포착 리스트 (1분 주기)")
st.caption("💡 아래 표에서 관심 있는 **종목 줄(Row)을 클릭**하시면 하단에 실시간 종합 호가창과 차트가 화면 내에 즉각 연동됩니다.")

table_placeholder = st.empty()
info_placeholder = st.empty()

# ==========================================
# 6. 1분(60초) 주기 백그라운드 타이머 루프 및 인터랙티브 뷰포트
# ==========================================
if 'countdown' not in st.session_state:
    st.session_state['countdown'] = 0

# 자동 동기화 가동
if st.session_state['countdown'] <= 0:
    run_monitoring()
    st.session_state['countdown'] = 60 

if st.session_state['detected_list']:
    display_df = pd.DataFrame(st.session_state['detected_list'])
    
    # on_select="rerun"을 주어 마우스 행 클릭 이벤트를 즉각적으로 획득
    event = table_placeholder.dataframe(
        display_df, 
        use_container_width=True, 
        hide_index=True, 
        on_select="rerun", 
        selection_mode="single-row"
    )
    
    if event and event.get("selection") and event["selection"].get("rows"):
        selected_row_idx = event["selection"]["rows"][0]
        st.session_state.clicked_stock = display_df.iloc[selected_row_idx].to_dict()
else:
    table_placeholder.info("아직 조건(변동폭 3% 이상 & 거래대금 100억 이상)을 만족하는 주도주가 없습니다. 시장을 실시간 감시 중입니다...")

info_placeholder.text(f"⏱️ 최근 동기화 시간: {datetime.now(KST).strftime('%H:%M:%S')} | 다음 자동 조회까지 {st.session_state['countdown']}초 남음...")

# ==========================================
# 7. 하단 실시간 네이버 모바일 종합 전광판 상시 표출 구역
# ==========================================
if st.session_state.clicked_stock:
    st.markdown("---")
    s_name = st.session_state.clicked_stock["종목명"]
    s_code = st.session_state.clicked_stock["종목코드"]
    
    st.markdown(f"### 📊 [{s_name} : {s_code}] 실시간 종합 차트")
    
    naver_mobile_chart_url = f"https://m.stock.naver.com/domestic/stock/{s_code}/total"
    
    naver_chart_html = f"""
    <div style="width: 100%; height: 650px; border-radius: 12px; overflow: hidden; border: 1px solid #e0e0e0; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
      <iframe src="{naver_mobile_chart_url}" 
              style="width: 100%; height: 100%; border: none; margin: 0; padding: 0;" 
              allowfullscreen></iframe>
    </div>
    """
    st.components.v1.html(naver_chart_html, height=670)

# 자동 카운트다운을 위한 리프레시 루프 연산 트리거
time.sleep(1)
st.session_state['countdown'] -= 1
st.rerun()
