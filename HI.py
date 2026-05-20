import requests
import json
import pandas as pd
import schedule
import time
import asyncio
from datetime import datetime
from telegram import Bot
import pytz  # 한국 시간 지정을 위해 추가
import streamlit as st

# 1. 스트림릿 비밀값(Secrets)에서 환경 변수 불러오기
APP_KEY = st.secrets["APP_KEY"]
APP_SECRET = st.secrets["APP_SECRET"]
TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
CHAT_ID = st.secrets["CHAT_ID"]

URL_BASE = "https://openapi.koreainvestment.com:9443"
KST = pytz.timezone('Asia/Seoul')  # 한국 표준시 정의

# 오늘 이미 알림을 보낸 종목을 기억하는 셋(Set) -> 중복 알림 방지
sent_stocks = set()

# 날짜가 바뀌면 알림 보낸 목록을 초기화하기 위한 변수 (한국 시간 기준)
current_date = datetime.now(KST).strftime("%Y%m%d")

def get_access_token():
    """한투 API 접근 토큰 발급"""
    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": APP_SECRET}
    res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body))
    return res.json()["access_token"]

async def send_telegram_msg(text):
    """텔레그램 메시지 전송 (비동기 처리)"""
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=text)

def check_market_time():
    """현재 한국 시간이 주식 장중(09:00 ~ 15:30)인지 확인 (주말 제외)"""
    now = datetime.now(KST)  # 💡 서버 시간이 아닌 진짜 한국 시간 기준
    if now.weekday() >= 5:   # 토(5), 일(6) 제외
        return False
    
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time

def monitor_volatility():
    """10분마다 실행될 핵심 감시 함수"""
    global current_date, sent_stocks
    
    # 한국 시간 기준으로 오늘 날짜 가져오기
    today = datetime.now(KST).strftime("%Y%m%d")
    current_time_str = datetime.now(KST).strftime('%H:%M:%S')
    
    # 날짜가 바뀌었으면 알림 보낸 종목 리스트 리셋
    if today != current_date:
        current_date = today
        sent_stocks.clear()
        print(f"📅 날짜 변경 ({today}): 알림 목록을 초기화합니다.")

    # 장중이 아니면 실행 안 함
    if not check_market_time():
        print(f"💤 현재 한국시간 {current_time_str} - 장외 시간이므로 대기합니다.")
        return

    print(f"🔍 [{current_time_str}] 변동성 종목 탐색 시작...")

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
        
        # 변동폭 계산
        df['volatility'] = ((df['stck_hgpr'] - df['stck_lwpr']) / df['stck_prpr'] * 100).round(2)
        
        # 조건 필터링: 거래대금 50억 이상 & 하루 변동폭 10% 이상
        target_stocks = df[(df['acml_tr_pbmn'] >= 50) & (df['volatility'] >= 10.0)]
        
        for _, row in target_stocks.iterrows():
            code = row['mkte_ticker']
            name = row['hts_kor_isnm']
            vol = row['volatility']
            price = row['stck_prpr']
            money = row['acml_tr_pbmn']
            
            if code in sent_stocks:
                continue
                
            msg = (
                f"🔥 [변동폭 10% 돌파 종목 포착] 🔥\n\n"
                f"📌 종목명: {name} ({code})\n"
                f"📈 현재가: {price:,}원\n"
                f"⚡ 당일 고저 변동폭: {vol}%\n"
                f"💰 현재 거래대금: {money:,}억"
            )
            
            asyncio.run(send_telegram_msg(msg))
            sent_stocks.add(code)
            print(f"📢 텔레그램 알림 발송 완료: {name} ({vol}%)")
            
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

# 스트림릿 웹 화면 구성 (서버가 깨어있는지 확인용)
st.title("📈 한국투자증권 변동성 감시 시스템")
st.write(f"현재 한국 시간: {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}")
st.write("백그라운드에서 10분마다 국내 주식 시장을 감시 중입니다.")

# 3. 스케줄러 설정: 10분마다 감시
schedule.every(10).minutes.do(monitor_volatility)

# 프로그램 최초 실행 시 즉시 한 번 체크
if 'initialized' not in st.session_state:
    st.session_state['initialized'] = True
    monitor_volatility()

# 스트림릿 백그라운드 루프 (스케줄러 작동용)
while True:
    schedule.run_pending()
    time.sleep(1)
