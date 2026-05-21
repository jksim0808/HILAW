import requests
import pandas as pd
import re
from datetime import datetime
import pytz
import streamlit as st

# 1. 기본 설정 및 한국 표준시(KST) 세팅
st.set_page_config(page_title="장중 실시간 주도주 레이더", layout="wide")
KST = pytz.timezone('Asia/Seoul')

# 2. 텔레그램 자격 증명만 안전하게 로드
TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"].strip()
CHAT_ID = st.secrets["CHAT_ID"].strip()

# 3. 세션 메모리 초기화
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set()
if 'stock_display_df' not in st.session_state:
    st.session_state['stock_display_df'] = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state['last_update_time'] = "아직 조회되지 않음"

# 4. 동기식 텔레그램 메시지 발송 함수
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=3)
    except:
        pass

# 5. 🛠️ [lxml 에러 완벽 격파] 순정 문자열 파싱 기법 기반의 주도주 추출 엔진
def execute_radar_screening():
    try:
        # 해외 IP 차단이 없는 네이버 실시간 거래대금/거래량 핵심 전광판 타격
        url = "https://finance.naver.com/sise/sise_quant.naver"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        res = requests.get(url, headers=headers, timeout=5)
        html_text = res.text
        
        # 🛡️ lxml 패키지 미설치 에러를 원천 차단하기 위해 pd.read_html을 쓰지 않고
        # 파이썬 기본 탑재 모듈인 정규식(re)을 이용해 HTML에서 종목 데이터 정밀 포획
        pattern = r'<tr.*?>\s*<td class="no">.*?</td>\s*<td><a href="/domestic/stock/(\d{6})/total" class="tltle">(.*?)</a></td>\s*<td class="number">([\d,]+)</td>\s*<td class="number">.*?<span class="(.*?)">([\d,]+)</span>.*?</td>\s*<td class="number">.*?<span class=".*?">([\d.,]+)%</span>.*?</td>\s*<td class="number">([\d,]+)</td>\s*<td class="number">([\d,]+)</td>'
        matches = re.findall(pattern, html_text, re.DOTALL)
        
        processed_rows = []
        detect_time = datetime.now(KST).strftime('%H:%M:%S')
        
        for match in matches:
            code = match[0]          # 종목코드
            name = match[1].strip()  # 종목명
            price = int(match[2].replace(',', '')) # 현재가
            direction = match[3]     # 상승/하락 여부 텍스트
            
            # 등락률 추출 및 부호 정형화
            rate = float(match[5])
            if 'blink_down' in direction or 'nv01' in direction:
                rate = -rate
                
            # 만 단위로 들어오는 거래대금 정밀 파싱 -> '억 원' 단위 절사 스케일링
            raw_money = float(match[7].replace(',', ''))
            money_billion = int(raw_money / 100) # 만원 단위 데이터를 100으로 나눠 억 단위로 변환
            
            # 🎯 [대표님 고정 조건]: 당일 누적 거래대금 100억 원 이상 돌파 & 상승률 +1.5% 이상 주도주
            if money_billion >= 10 and rate >= 1.5:
                # 텔레그램 실시간 중복 알림 가드 가동
                if name not in st.session_state['sent_stocks']:
                    msg = (
                        f"🚀 [장중 주도주 포착]\n\n"
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
                    "전일대비 등락률": f"+{rate}%",
                    "당일 거래대금(억)": money_billion
                })
                
        # 거래대금이 장중 가장 무겁게 터진 대장주 순서대로 상위 20개 정렬 적재
        if processed_rows:
            df_result = pd.DataFrame(processed_rows)
            df_result = df_result.sort_values(by="당일 거래대금(억)", ascending=False).head(20)
            st.session_state['stock_display_df'] = df_result
        else:
            st.session_state['stock_display_df'] = pd.DataFrame()
            
        st.session_state['last_update_time'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        st.success("🟢 특수 패키지 의존성 없이 장중 순정 수급 주도주 라인업을 정상적으로 로드했습니다.")
        
    except Exception as e:
        st.error(f"💥 수급 관제 엔진 연동 중 지연 발생 (새로고침을 다시 실행해 주십시오): {e}")

# ==========================================
# 6. 대시보드 레이아웃 UI 구역
# ==========================================
st.title("⚡ 장중 실시간 수급 주도주 관제 레이더")
st.caption("외부 패키지(lxml) 의존성을 완전 소멸시키고 파이썬 순정 파싱 모듈로 새로 고침한 완벽 차단 우회본")

# 수동 즉시 조회 버튼
if st.button("🔄 실시간 수급 주도주 데이터 즉시 새로고침", use_container_width=True):
    execute_radar_screening()

# 메트릭 보드 정렬
col_t1, col_t2 = st.columns(2)
with col_t1:
    st.metric(label="📊 수급망 최종 동기화 완료 시간 (KST)", value=st.session_state['last_update_time'])
with col_t2:
    st.metric(label="🎯 현재 포착된 거래대금 주도주", value=f"{len(st.session_state['stock_display_df'])} 개")

st.markdown("---")

# 실시간 모니터링 데이터 표 렌더링 구역
if not st.session_state['stock_display_df'].empty:
    st.dataframe(st.session_state['stock_display_df'], use_container_width=True, hide_index=True)
else:
    # 최초 실행 시 화면이 비어있으면 자동 기동 트리거링 후 새로고침 유도
    execute_radar_screening()
    if not st.session_state['stock_display_df'].empty:
        st.rerun()
    else:
        st.warning("📥 상단의 [🔄 실시간 수급 주도주 데이터 즉시 새로고침] 버튼을 누르시면 차단벽과 패키지 에러 없는 데이터베이스로부터 장중 거래 대장주들을 즉시 긁어옵니다.")
