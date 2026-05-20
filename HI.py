import requests
import json
import pandas as pd
import schedule
import time
import asyncio
from datetime import datetime
from telegram import Bot

# 1. 설정 정보 (본인의 정보로 꼭 바꾸세요!)
APP_KEY = "YOUR_APP_KEY_HERE"
APP_SECRET = "YOUR_APP_SECRET_HERE"
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
CHAT_ID = "YOUR_CHAT_ID_HERE"

URL_BASE = "https://openapi.koreainvestment.com:9443"

# 오늘 이미 알림을 보낸 종목을 기억하는 셋(Set) -> 중복 알림 방지
sent_stocks = set()

# 날짜가 바뀌면 알림 보낸 목록을 초기화하기 위한 변수
current_date = datetime.now().strftime("%Y%m%d")

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
    """현재 시간이 주식 장중(09:00 ~ 15:30)인지 확인 (주말 제외)"""
    now = datetime.now()
    if now.weekday() >= 5: # 토(5), 일(6) 제외
        return False
    
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time

def monitor_volatility():
    """10분마다 실행될 핵심 감시 함수"""
    global current_date, sent_stocks
    
    # 날짜가 바뀌었으면 알림 보낸 종목 리스트 리셋
    today = datetime.now().strftime("%Y%m%d")
    if today != current_date:
        current_date = today
        sent_stocks.clear()
        print(f"📅 날짜 변경 ({today}): 알림 목록을 초기화합니다.")

    # 장중이 아니면 실행 안 함
    if not check_market_time():
        print(f"💤 현재 시간 {datetime.now().strftime('%H:%M:%S')} - 장외 시간이므로 대기합니다.")
        return

    print(f"🔍 [{datetime.now().strftime('%H:%M:%S')}] 변동성 종목 탐색 시작...")

    try:
        token = get_access_token()
        
        # 거래대금 상위 종목 호출 TR
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
        df['acml_tr_pbmn'] = df['acml_tr_pbmn'].astype(int) // 100000000 # 억원 단위
        
        # 변동폭 계산
        df['volatility'] = ((df['stck_hgpr'] - df['stck_lwpr']) / df['stck_prpr'] * 100).round(2)
        
        # 조건 필터링: 거래대금 50억 이상 & 하루 변동폭 10% 이상인 종목들만
        target_stocks = df[(df['acml_tr_pbmn'] >= 50) & (df['volatility'] >= 10.0)]
        
        # 조건에 맞는 종목들 순회
        for _, row in target_stocks.iterrows():
            code = row['mkte_ticker'] # 종목코드
            name = row['hts_kor_isnm'] # 종목명
            vol = row['volatility'] # 변동폭
            price = row['stck_prpr'] # 현재가
            money = row['acml_tr_pbmn'] # 거래대금
            
            # 오늘 이미 알림을 보낸 종목이면 패스!
            if code in sent_stocks:
                continue
                
            # 새로운 10% 돌파 종목 발견 시 텔레그램 발송 메시지 구성
            msg = (
                f"🔥 [변동폭 10% 돌파 종목 포착] 🔥\n\n"
                f"📌 종목명: {name} ({code})\n"
                f"📈 현재가: {price:,}원\n"
                f"⚡ 당일 고저 변동폭: {vol}%\n"
                f"💰 현재 거래대금: {money:,}억"
            )
            
            # 비동기로 텔레그램 메시지 쏘기
            asyncio.run(send_telegram_msg(msg))
            
            # 보낸 종목 등록
            sent_stocks.add(code)
            print(f"📢 텔레그램 알림 발송 완료: {name} ({vol}%)")
            
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

# 3. 스케줄러 설정: 장중에 10분마다 monitor_volatility 함수 실행
schedule.every(10).minutes.do(monitor_volatility)

if __name__ == "__main__":
    print("🚀 한국투자증권 변동성 감시 봇이 가동되었습니다.")
    print("장중에 10분마다 체크를 시작합니다. (Ctrl + C 누르면 종료)\n")
    
    # 시작하자마자 테스트 삼아 한 번 돌려보기
    monitor_volatility()
    
    # 무한 루프를 돌며 스케줄러 감시
    while True:
        schedule.run_pending()
        time.sleep(1)
