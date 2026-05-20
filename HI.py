import requests
import json
import pandas as pd
import time
import asyncio
from datetime import datetime
from telegram import Bot
import pytz
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정 (넓은 화면 모드)
# ==========================================
st.set_page_config(page_title="한투 주도주 감시봇", layout="wide")

# 한국 표준시(KST) 타임존 정의
KST = pytz.timezone('Asia/Seoul')

# ==========================================
# 2. 보안 변수(Secrets) 및 사용자 입력 처리
# ==========================================
# 한국투자증권 API 키는 보안상 스트림릿 Secrets에서만 가져옵니다.
APP_KEY = st.secrets["APP_KEY"]
APP_SECRET = st.secrets["APP_SECRET"]
URL_BASE = "https://openapi.koreainvestment.com:9443"

# [다른 사람들을 위한 공유 기능] 
# 왼쪽 사이드바에서 접속자가 자기 텔레그램 키를 넣으면 그 사람에게 알림이 갑니다.
st.sidebar.header("🤖 나만의 텔레그램 알림 설정")
st.sidebar.markdown("이곳에 본인의 키를 입력하면 개인 알림을 받을 수 있습니다. 입력하지 않으면 개발자의 기본 방으로 알림이 전송됩니다.")

user_token = st.sidebar.text_input("텔레그램 봇 토큰 입력", type="password", help="BotFather에게 받은 토큰을 넣으세요.")
user_chat_id = st.sidebar.text_input("내 채팅방 ID 입력", help="@userinfobot에게 받은 ID(숫자)를 넣으세요.")

# 사용자가 입력한 값이 있으면 그것을 쓰고, 없으면 스트림릿 Secrets의 기본값(내 방)을 사용합니다.
TELEGRAM_TOKEN = user_token if user_token else st.secrets["TELEGRAM_TOKEN"]
CHAT_ID = user_chat_id if user_chat_id else st.secrets["CHAT_ID"]

# ==========================================
# 3. 세션 상태(Session State) 초기화
# ==========================================
# 스트림릿은 화면이 갱신될 때 코드가 처음부터 다시 돌기 때문에, 데이터를 유지하기 위해 세션 상태를 씁니다.
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set() # 중복 알림 방지용 셋
if 'current_date' not in st.session_state:
    st.session_state['current_date'] = datetime.now(KST).strftime("%Y%m%d")
if 'detected_list' not in st.session_state:
    st.session_state['detected_list'] = []  # 화면에 표로 그려줄 데이터 리스트

# ==========================================
# 4. 핵심 백엔드 기능 함수들
# ==========================================
def get_access_token():
    """한국투자증권 API 접근 토큰 발급"""
    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": APP_SECRET}
    res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body))
    return res.json()["access_token"]

async def send_telegram_msg(token, chat_id, text):
    """텔레그램 메시지 전송 (비동기 처리)"""
    try:
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        print(f"텔레그램 발송 실패 (키 오류 가능성): {e}")

def check_market_time():
    """현재 한국 시간이 주식 장중(09:00 ~ 15:30)인지 확인 (주말 제외)"""
    now = datetime.now(KST)
    if now.weekday() >= 5: # 토(5), 일(6)은 장외
        return False
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time

def run_monitoring():
    """시장을 조회하고 3%/200억 조건에 맞는 주도주를 찾아냅니다."""
    today = datetime.now(KST).strftime("%Y%m%d")
    
    # 날짜가 바뀌었으면 오늘 첫 실행이므로 초기화 리셋
    if today != st.session_state['current_date']:
        st.session_state['current_date'] = today
        st.session_state['sent_stocks'].clear()
        st.session_state['detected_list'] = []

    # 장외 시간 예외 처리 (주말이나 밤에 테스트해보려면 아래 두 줄을 주석처리(#) 하세요)
    if not check_market_time():
        return

    try:
        token = get_access_token()
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000" # 거래대금 상위 타겟 TR
        }
        params = {"user_id": "", "seq": "", "data_cnt": "", "ranking_option": "1", "market_div": "0000", "industry_div": "0000"}
        
        res = requests.get(f"{URL_BASE}/uapi/domestic-stock/v1/ranking/trade-vol", headers=headers, params=params)
        data = res.json()['output']
        
        df = pd.DataFrame(data)
        df['stck_prpr'] = df['stck_prpr'].astype(int)
        df['stck_hgpr'] = df['stck_hgpr'].astype(int)
        df['stck_lwpr'] = df['stck_lwpr'].astype(int)
        df['acml_tr_pbmn'] = df['acml_tr_pbmn'].astype(int) // 100000000 # 억원 단위 변환
        
        # 💡 변동폭 계산 공식 적용
        df['volatility'] = ((df['stck_hgpr'] - df['stck_lwpr']) / df['stck_prpr'] * 100).round(2)
        
        # 🔥 [핵심 필터] 거래대금 200억 이상 & 하루 변동폭 3% 이상인 묵직한 주도주만 선별!
        target_stocks = df[(df['acml_tr_pbmn'] >= 200) & (df['volatility'] >= 3.0)]
        
        for _, row in target_stocks.iterrows():
            code = row['mkte_ticker']
            name = row['hts_kor_isnm']
            vol = row['volatility']
            price = row['stck_prpr']
            money = row['acml_tr_pbmn']
            detect_time = datetime.now(KST).strftime('%H:%M:%S')
            
            # 오늘 이미 알림을 쐈던 종목은 패스 (중복 알림 방지)
            if code in st.session_state['sent_stocks']:
                continue
                
            # 1. 텔레그램 메시지 발송
            msg = (
                f"🚀 [주도주 포착 - 변동폭 3% / 거래대금 200억 돌파] 🚀\n\n"
                f"📌 종목명: {name} ({code})\n"
                f"📈 현재가: {price:,}원\n"
                f"⚡ 당일 고저 변동폭: {vol}%\n"
                f"💰 현재 거래대금: {money:,}억"
            )
            asyncio.run(send_telegram_msg(TELEGRAM_TOKEN, CHAT_ID, msg))
            
            # 알림 보낸 목록에 추가
            st.session_state['sent_stocks'].add(code)
            
            # 2. 스트림릿 웹 화면용 리스트에 추가 (최신 종목이 가장 위로 오도록 insert)
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
        # 에러 발생 시 스트림릿 로그창에는 출력하되 대시보드가 멈추지 않게 방어
        print(f"데이터 조회 중 에러 발생: {e}")

# ==========================================
# 5. 프론트엔드 UI (Streamlit 대시보드 화면)
# ==========================================
st.title("🔥 한국투자증권 실시간 주도주 대시보드 (3% / 200억)")

# 상단 실시간 현황판
col1, col2 = st.columns(2)
with col1:
    st.metric(label="현재 한국 표준시(KST)", value=datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
with col2:
    st.metric(label="오늘 레이더에 걸린 총 종목 수", value=f"{len(st.session_state['detected_list'])} 개")

st.markdown("---")
st.subheader("🎯 장중 실시간 주도주 포착 리스트 (1분 주기)")

# 실시간으로 변하는 표와 정보를 그려줄 빈 공간(Placeholder) 확보
table_placeholder = st.empty()
info_placeholder = st.empty()

# ==========================================
# 6. 1분(60초) 주기 백그라운드 타이머 루프
# ==========================================
# 앱을 켜자마자 바로 조회가 돌아가도록 0으로 시작
if 'countdown' not in st.session_state:
    st.session_state['countdown'] = 0

while True:
    current_time_str = datetime.now(KST).strftime('%H:%M:%S')
    
    # 타이머가 0이 되면 한투 API를 찔러서 데이터 갱신
    if st.session_state['countdown'] <= 0:
        run_monitoring()
        st.session_state['countdown'] = 60 # 🕐 60초(1분) 타이머 리셋!

    # 포착된 데이터가 리스트에 하나라도 존재하면 표(Table)로 예쁘게 출력
    if st.session_state['detected_list']:
        display_df = pd.DataFrame(st.session_state['detected_list'])
        table_placeholder.data_editor(display_df, use_container_width=True, hide_index=True)
    else:
        table_placeholder.info("아직 조건(변동폭 3% 이상 & 거래대금 200억 이상)을 동시에 만족하는 주도주가 없습니다. 시장을 실시간 감시 중입니다...")

    # 하단 상태 바에 다음 갱신까지 남은 시간 초 단위로 출력
    info_placeholder.text(f"⏱️ 최근 동기화 시간: {current_time_str} | 다음 자동 조회까지 {st.session_state['countdown']}초 남음...")
    
    # 1초씩 쉬면서 카운트다운을 깎음
    time.sleep(1)
    st.session_state['countdown'] -= 1
