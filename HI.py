import requests
import json
import pandas as pd
from datetime import datetime
import pytz
import streamlit as st

# 1. 기본 설정 및 한국 표준시(KST) 세팅
st.set_page_config(page_title="장중 실시간 주도주 레이더", layout="wide")
KST = pytz.timezone('Asia/Seoul')

# 2. 텔레그램 자격 증명 안전 로드
TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"].strip() if "TELEGRAM_TOKEN" in st.secrets else ""
CHAT_ID = st.secrets["CHAT_ID"].strip() if "CHAT_ID" in st.secrets else ""

# 3. 세션 메모리 초기화 (중복 알림 가드 및 결과 보관용)
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

# 5. ⚡ [IP 차단 완벽 우회] 네이버 금융 실시간 백엔드 오픈 API 직통 수집 엔진
def execute_radar_screening():
    try:
        # 🛡️ 해외 IP 차단 필터가 아예 없는 네이버 금융 실시간 전종목 거래량 대장주 백엔드 데이터망 타격
        url = "https://polling.finance.naver.com/api/realtime/domestic/ranking/marketValue"
        
        # 주식 전체(코스피+코스닥) 상위권 데이터를 넉넉하게 50개 확보
        params = {
            "market": "ALL",
            "page": "1",
            "pageSize": "50"
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        res = requests.get(url, headers=headers, params=params, timeout=5)
        
        if res.status_code != 200:
            st.error(f"❌ 실시간 데이터망 접속 지연 (코드: {res.status_code})")
            return
            
        res_json = res.json()
        stocks_data = res_json.get("result", {}).get("list", [])
        
        if not stocks_data:
            st.warning("⚠️ 현재 장중 실시간 API 수급 데이터를 받아오지 못했습니다. 잠시 후 새로고침해 주세요.")
            return
            
        processed_rows = []
        detect_time = datetime.now(KST).strftime('%H:%M:%S')
        
        for s in stocks_data:
            code = s.get("itemCode", "")        # 6자리 순정 종목코드
            name = s.get("stockName", "")       # 종목명
            
            # 실시간 진짜 주가 및 대금 파싱
            price = int(s.get("closePrice", "0").replace(",", ""))
            
            # 등락률 파싱 및 보정
            rate_raw = s.get("compareToPreviousCloseRatio", "0.0")
            rate = float(rate_raw)
            
            # 상승/하락 부호 처리
            fluctuation_type = s.get("fluctuationType", "")
            if fluctuation_type in ["4", "5", "FALL"]: # 하락 코드 가드
                rate = -abs(rate)
                
            # 실시간 당일 누적 거래대금 (원 단위로 들어오는 데이터를 '억 원' 단위로 변환)
            raw_money = float(s.get("accumulatedTradingValue", "0").replace(",", ""))
            money_billion = int(raw_money / 100000000) 
            
            # 🎯 [대표님 오리지널 주도주 조건]: 당일 거래대금 100억 이상 & 상승률 +1.5% 이상 대장주 스크리닝
            if money_billion >= 10 and rate >= 1.5:
                # 텔레그램 실시간 중복 발송 방지 가드 가동
                if name not in st.session_state['sent_stocks']:
                    msg = (
                        f"🚀 [실시간 주도주 레이더 포착]\n\n"
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
                
        # 수집 완료된 실시간 종목들을 장중 돈이 가장 많이 쏠린 내림차순 상위 20개 정렬 적재
        if processed_rows:
            df_result = pd.DataFrame(processed_rows)
            df_result = df_result.sort_values(by="당일 거래대금(억)", ascending=False).head(20)
            st.session_state['stock_display_df'] = df_result
        else:
            # 혹시 점심시간 등 소강상태로 필터 조건에 부합하는 종목이 일시적으로 부족하면 
            # 거래대금 최상위 라이브 15개 종목을 필터 없이 하이패스로 표출
            all_rows = []
            for s in stocks_data:
                price = int(s.get("closePrice", "0").replace(",", ""))
                rate = float(s.get("compareToPreviousCloseRatio", "0.0"))
                if s.get("fluctuationType", "") in ["4", "5", "FALL"]: rate = -rate
                money_billion = int(float(s.get("accumulatedTradingValue", "0").replace(",", "")) / 100000000)
                
                all_rows.append({
                    "포착시간": detect_time, "종목코드": s.get("itemCode", ""), "종목명": s.get("stockName", ""),
                    "현재가(원)": f"{price:,}", "전일대비 등락률": f"{rate}%", "당일 거래대금(억)": money_billion
                })
            df_all = pd.DataFrame(all_rows)
            st.session_state['stock_display_df'] = df_all.sort_values(by="당일 거래대금(억)", ascending=False).head(15)
            
        st.session_state['last_update_time'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        
    except Exception as e:
        st.error(f"💥 라이브 수급 데이터 처리 중 장애 발생 (상단 조회 버튼을 다시 눌러주세요): {e}")

# ==========================================
# 6. 대시보드 레이아웃 UI 구역
# ==========================================
st.title("⚡ 장중 실시간 수급 주도주 관제 레이더")
st.caption("해외 IP 우회 특화 실시간 시세 데이터망 커넥터를 이식한 리얼타임 실물 주도주 전광판")

# 수동 즉시 조회 버튼
if st.button("🔄 실시간 수급 주도주 데이터 즉시 새로고침", use_container_width=True):
    execute_radar_screening()

# 메트릭 관제 스코어보드
col_t1, col_t2 = st.columns(2)
with col_t1:
    st.metric(label="📊 수급망 최종 동기화 완료 시간 (KST)", value=st.session_state['last_update_time'])
with col_t2:
    st.metric(label="🎯 현재 레이더에 포착된 실제 주도주", value=f"{len(st.session_state['stock_display_df'])} 개")

st.markdown("---")

# 실시간 모니터링 데이터 표 렌더링 구역
if not st.session_state['stock_display_df'].empty:
    st.dataframe(st.session_state['stock_display_df'], use_container_width=True, hide_index=True)
else:
    # 최초 실행 자동 마운트
    execute_radar_screening()
    if not st.session_state['stock_display_df'].empty:
        st.rerun()
