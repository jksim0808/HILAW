import requests
import json
import pandas as pd
import time
import asyncio
from datetime import datetime
from telegram import Bot
import pytz
import streamlit as st

# 1. 스트림릿 페이지 기본 설정 (넓은 화면 모드)
st.set_page_config(page_title="한투 변동성 감시", layout="wide")

# Env 변수 불러오기
APP_KEY = st.secrets["APP_KEY"]
APP_SECRET = st.secrets["APP_SECRET"]
TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
CHAT_ID = st.secrets["CHAT_ID"]

URL_BASE = "https://openapi.koreainvestment.com:9443"
KST = pytz.timezone('Asia/Seoul')

# 세션 상태(Session State)를 활용해 새로고침되어도 데이터 유지하기
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set()
if 'current_date' not in st.session_state:
    st.session_state['current_date'] = datetime.now(KST).strftime("%Y%m%d")
if 'detected_list' not in st.session_state:
    st.session_state['detected_list'] = [] # 화면에 표로 보여줄 데이터 저장소

def get_access_token():
    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": APP_SECRET}
    res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body))
    return res.json()["access_token"]

async def send_telegram_msg(text):
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=text)

def check_market_time():
    now = datetime.now(KST)
    if now.weekday() >= 5: 
        return False
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time

def run_monitoring():
    """시장을 조회하고 변동성 종목을 찾아 리스트와 텔레그램으로 보냄"""
    today = datetime.now(KST).strftime("%Y%m%d")
    
    # 날짜 바뀌면 초기화
    if today != st.session_state['current_date']:
        st.session_state['current_date'] = today
        st.session_state['sent_stocks'].clear()
        st.session_state['detected_list'] = []

    # 장외 시간 예외 처리 (주석 해제하면 장외에 작동 안 함)
    # if not check_market_time():
    #     return

    try:
        token = get_access_token()
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000"
        }
        params = {"user_id": "", "seq": "", "data_cnt": "", "ranking_option": "1", "market_div": "0000", "industry_div": "0000"}
        
        res = requests.get(f"{URL_BASE}/uapi/domestic-stock/v1/ranking/trade-vol", headers=headers, params=params)
        data = res.json()['output']
        
        df = pd.DataFrame(data)
        df['stck_prpr'] = df['stck_prpr'].astype(int)
        df['stck_hgpr'] = df['stck_hgpr'].astype(int)
        df['stck_lwpr'] = df['stck_lwpr'].astype(int)
        df['acml_tr_pbmn'] = df['acml_tr_pbmn'].astype(int) // 100000000
        df['volatility'] = ((df['stck_hgpr'] - df['stck_lwpr']) / df['stck_prpr'] * 100).round(2)
        
        # 조건: 거래대금 50억 이상 & 변동폭 10% 이상
        target_stocks = df[(df['acml_tr_pbmn'] >= 200) & (df['volatility'] >= 3.0)]
        
        for _, row in target_stocks.iterrows():
            code = row['mkte_ticker']
            name = row['hts_kor_isnm']
            vol = row['volatility']
            price = row['stck_prpr']
            money = row['acml_tr_pbmn']
            detect_time = datetime.now(KST).strftime('%H:%M:%S')
            
            if code in st.session_state['sent_stocks']:
                continue
                
            # 1. 텔레그램 발송
            msg = f"🔥 [ 주도주 포착 - 변동폭 3% / 거래대금 200억 돌파] 🔥\n\n📌 종목명: {name} ({code})\n📈 현재가: {price:,}원\n⚡ 변동폭: {vol}%\n💰 거래대금: {money:,}억"
            asyncio.run(send_telegram_msg(msg))
            st.session_state['sent_stocks'].add(code)
            
            # 2. 스트림릿 화면용 리스트에 추가 (최신 발견 종목이 맨 위로 오도록 insert)
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
        pass

# --- 여기서부터 스트림릿 UI 그려주는 부분 ---
st.title("🔥 한국투자증권 변동성 종목 실시간 대시보드")

# 상단 정보 레이아웃
col1, col2 = st.columns(2)
with col1:
    st.metric(label="현재 한국 시간", value=datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
with col2:
    st.metric(label="오늘 포착된 총 종목 수", value=f"{len(st.session_state['detected_list'])} 개")

st.markdown("---")
st.subheader("🎯 포착된 고변동성 종목 리스트 (1분마다 갱신)")

# 실시간으로 변하는 표를 그려줄 빈 공간(Placeholder) 생성
table_placeholder = st.empty()
info_placeholder = st.empty()

# 무한 루프를 돌며 1분(60초)마다 데이터 갱신 및 화면 리프레시
# 테스트를 위해 코드를 켜자마자 바로 한 번 실행하게 유도
countdown = 0

while True:
    current_time_str = datetime.now(KST).strftime('%H:%M:%S')
    
    # 1분(60초)마다 한투 API 호출
    if countdown <= 0:
        run_monitoring()
        countdown = 60 # 1분 타이머 리셋

    # 데이터가 있으면 화면에 표(Table) 출력
    if st.session_state['detected_list']:
        display_df = pd.DataFrame(st.session_state['detected_list'])
        table_placeholder.data_editor(display_df, use_container_width=True, hide_index=True)
    else:
        table_placeholder.info("아직 조건(변동폭 3% 이상 & 거래대금 200억 이상)을 만족하는 종목이 없습니다. 시장을 감시 중입니다...")

    # 하단에 다음 갱신까지 남은 시간 표시
    info_placeholder.text(f"⏱️ 최근 동기화 시간: {current_time_str} | 다음 자동 조회까지 {countdown}초 남음...")
    
    time.sleep(1)
    countdown -= 1
