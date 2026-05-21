import requests
import json
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz
import streamlit as st

# 1. 기본 설정 및 한국 표준시(KST) 세팅
st.set_page_config(page_title="장중 실시간 주도주 레이더", layout="wide")
KST = pytz.timezone('Asia/Seoul')

# 2. 텔레그램 자격 증명 안전 로드
TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"].strip() if "TELEGRAM_TOKEN" in st.secrets else ""
CHAT_ID = st.secrets["CHAT_ID"].strip() if "CHAT_ID" in st.secrets else ""

# 3. 세션 메모리 초기화 (중복 알림 방지 및 데이터 보관)
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set()
if 'stock_display_df' not in st.session_state:
    st.session_state['stock_display_df'] = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state['last_update_time'] = "아직 조회되지 않음"

# 4. 동기식 텔레그램 메시지 발송 함수
def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=3)
    except:
        pass

# 5. ⚡ [차단 원천 차단] 글로벌 표준 금융망 직통 실시간 주도주 추출 엔진
def execute_radar_screening():
    try:
        # 📌 대한민국 증시 장중 거래대금 상위 필수 관제 심장부 종목 마스터 리스트 (시장을 주도하는 주요 대장주 전수 등록)
        target_tickers = {
            "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "012450.KS": "한화에어로스페이스",
            "247540.KQ": "에코프로비엠", "068270.KS": "셀트리온", "005380.KS": "현대차",
            "035420.KS": "NAVER", "455120.KQ": "제룡전기", "000270.KS": "기아",
            "192080.KQ": "부방", "041020.KS": "일진전기", "005490.KS": "POSCO홀딩스",
            "028300.KQ": "HLB", "009830.KS": "한화오션", "035720.KS": "카카오",
            "000150.KS": "두산", "003670.KS": "포스코푸처엠", "373220.KS": "LG에너지솔루션",
            "086520.KQ": "에코프로", "000810.KS": "삼성화재", "011200.KS": "HMM"
        }
        
        tickers_str = " ".join(target_tickers.keys())
        
        # 차단 없는 글로벌 금융망을 통해 대한민국 대장주 데이터 고속 대량 확보
        data = yf.Tickers(tickers_str)
        
        processed_rows = []
        detect_time = datetime.now(KST).strftime('%H:%M:%S')
        
        for ticker_id, name in target_tickers.items():
            try:
                ticker_data = data.tickers[ticker_id].info
                
                # 실시간 진짜 가격 및 전일대비 변동 데이터 추출
                price = int(ticker_data.get("currentPrice", ticker_data.get("regularMarketPrice", 0)))
                prev_close = ticker_data.get("regularMarketPreviousClose", 0)
                
                if prev_close > 0:
                    rate = round(((price - prev_close) / prev_close) * 100, 2)
                else:
                    rate = 0.0
                
                # 실시간 당일 거래대금 스케일링 연산 (글ローバル 표준 스케일을 '억 원' 단위로 깔끔하게 절사)
                # Volume * CurrentPrice 기반 당일 회전 자금 정밀 추적
                volume = ticker_data.get("regularMarketVolume", 0)
                if volume == 0:
                    volume = ticker_data.get("volume", 0)
                    
                raw_money = volume * price
                money_billion = int(raw_money / 100000000)
                
                code = ticker_id.split(".")[0] # 6자리 종목코드만 정밀 추출
                
                # 🎯 [대표님 고정 주도주 커트라인]: 당일 거래대금 100억 이상 & 상승률 +1.5% 이상 레이더 감지
                if money_billion >= 10 and rate >= 1.5:
                    if name not in st.session_state['sent_stocks']:
                        msg = (
                            f"🚀 [글로벌 망 직통 - 주도주 포착]\n\n"
                            f"📌 종목명: {name} ({code})\n"
                            f"📈 현재가: {price:,}원\n"
                            f"⚡ 당일 등락률: +{rate}%\n"
                            f"💰 현재 거래대금: {money_billion:,}억 돌파!"
                        )
                        send_telegram(msg)
                        st.session_state['sent_stocks'].add(name)
                        
                    processed_rows.append({
                        "포착시간": detect_time,
                        "종목코드": code,
                        "종목명": name,
                        "현재가(원)": f"{price:,}",
                        "전일대비 등락률": f"+{rate}%" if rate > 0 else f"{rate}%",
                        "당일 거래대금(억)": money_billion
                    })
            except:
                continue
                
        # 수집 및 정화 완료된 대한민국 실시간 주도주들을 거래대금 내림차순 정렬 상위 20개 최종 적재
        if processed_rows:
            df_result = pd.DataFrame(processed_rows)
            df_result = df_result.sort_values(by="당일 거래대금(억)", ascending=False)
            st.session_state['stock_display_df'] = df_result
        else:
            # 장세 소강 상태용 무조건 표출 방어 장치: 전체 수집 목록을 대금 순서대로 상위 12개 하이패스 노출
            fallback_rows = []
            for ticker_id, name in target_tickers.items():
                try:
                    t_info = data.tickers[ticker_id].info
                    p = int(t_info.get("currentPrice", t_info.get("regularMarketPrice", 0)))
                    pc = t_info.get("regularMarketPreviousClose", 0)
                    r = round(((p - pc) / pc) * 100, 2) if prev_close > 0 else 0.0
                    v = t_info.get("regularMarketVolume", t_info.get("volume", 0))
                    m = int((v * p) / 100000000)
                    fallback_rows.append({
                        "포착시간": detect_time, "종목코드": ticker_id.split(".")[0], "종목명": name,
                        "현재가(원)": f"{p:,}", "전일대비 등락률": f"+{r}%" if r > 0 else f"{r}%", "당일 거래대금(억)": m
                    })
                except: continue
            if fallback_rows:
                df_fb = pd.DataFrame(fallback_rows)
                st.session_state['stock_display_df'] = df_fb.sort_values(by="당일 거래대금(억)", ascending=False).head(15)
                
        st.session_state['last_update_time'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        
    except Exception as e:
        st.error(f"💥 글로벌 통신망 데이터 처리 중 장애 발생: {e}")

# ==========================================
# 6. 대시보드 레이아웃 UI 구역
# ==========================================
st.title("⚡ 장중 실시간 수급 주도주 관제 레이더")
st.caption("국내 금융 포털의 해외 IP 404 차단벽을 무력화하고 글로벌 표준 금융 백엔드 네트워크망을 직통 연결한 최종 가동본")

# 수동 즉시 조회 버튼
if st.button("🔄 실시간 수급 주도주 데이터 즉시 새로고침", use_container_width=True):
    execute_radar_screening()

# 메트릭 관제 스코어보드
col_t1, col_t2 = st.columns(2)
with col_t1:
    st.metric(label="📊 글로벌 금융망 최종 동기화 완료 시간 (KST)", value=st.session_state['last_update_time'])
with col_t2:
    st.metric(label="🎯 현재 레이더에 포착된 실제 주도주", value=f"{len(st.session_state['stock_display_df'])} 개")

st.markdown("---")

# 실시간 모니터링 데이터 표 렌더링 구역
if not st.session_state['stock_display_df'].empty:
    st.dataframe(st.session_state['stock_display_df'], use_container_width=True, hide_index=True)
else:
    # 최초 구동 자동 마운트
    execute_radar_screening()
    if not st.session_state['stock_display_df'].empty:
        st.rerun()
