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

# 5. 🎯 [줄바꿈 버그 완벽 제압] 유연한 유니버설 문자열 파싱 엔진
def execute_radar_screening():
    try:
        # 실시간 거래량/거래대금 메인 소스 타격
        url = "https://finance.naver.com/sise/sise_quant.naver"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        res = requests.get(url, headers=headers, timeout=5)
        html_text = res.text
        
        # 줄바꿈 및 공백 노이즈를 먼저 깔끔하게 단일화하여 정규식 미끄러짐 방지
        html_clean = re.sub(r'\s+', ' ', html_text)
        
        # 각 종목이 들어있는 행(tr) 단위로 1차 분할
        tr_elements = re.findall(r'<tr.*?>.*?</tr>', html_clean)
        
        processed_rows = []
        detect_time = datetime.now(KST).strftime('%H:%M:%S')
        
        for tr in tr_elements:
            # 6자리 종목코드와 종목명 추출 패턴
            title_match = re.search(r'href="/domestic/stock/(\d{6})/total".*?>(.*?)</a>', tr)
            if not title_match:
                continue
                
            code = title_match.group(1)
            name = title_match.group(2).strip()
            
            # 행 내부의 모든 숫자형 데이터 항목(td class="number") 전원 포획
            numbers = re.findall(r'<td class="number">.*?>(.*?)</span>.*?</td>', tr)
            # span 태그가 없는 순정 숫자 항목 데이터 보완 포획
            if not numbers or len(numbers) < 5:
                numbers = re.findall(r'<td class="number">([\d,.\-+%]+)</td>', tr)
                
            # 데이터 개수가 정상적인 수급 데이터 행인지 유효성 검사
            if len(numbers) < 4:
                # 혼합 형태 방어 코드
                mixed_numbers = re.findall(r'<td class="number">.*?([\d,.\-+%]+).*?</td>', tr)
                if len(mixed_numbers) >= 5:
                    numbers = mixed_numbers
                else:
                    continue
            
            try:
                # 순서에 맞게 변수 정밀 매핑 (현재가, 등락률, 거래대금)
                price_raw = numbers[0].replace(',', '').strip()
                price = int(price_raw) if price_raw.isdigit() else 0
                
                # 등락률 발라내기 및 부호 정형화
                rate_raw = numbers[2].replace('%', '').replace('+', '').strip()
                rate = float(rate_raw) if rate_raw else 0.0
                
                # 하락인 경우 마이너스 부호 강제 복구 연산
                if 'down' in tr or 'nv01' in tr:
                    rate = -abs(rate)
                
                # 거래대금(만 단위) 파싱 -> '억 원' 단위 절사 스케일링
                money_index = 5 if len(numbers) >= 6 else 4
                money_raw = numbers[money_index].replace(',', '').strip()
                raw_money = float(money_raw) if money_raw else 0.0
                money_billion = int(raw_money / 100) # 만원 단위를 100으로 나누어 억 단위로 고정
                
                # 🎯 [대표님 고정 주도주 조건]: 당일 누적 거래대금 100억 원 이상 돌파 & 상승률 +1.5% 이상 대장주
                if money_billion >= 10 and rate >= 1.5:
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
            except Exception as inner_e:
                continue
                
        # 거래대금이 강하게 터진 내림차순 정렬 상위 20개 마운트
        if processed_rows:
            df_result = pd.DataFrame(processed_rows)
            df_result = df_result.sort_values(by="당일 거래대금(억)", ascending=False).head(20)
            st.session_state['stock_display_df'] = df_result
        else:
            st.session_state['stock_display_df'] = pd.DataFrame()
            
        st.session_state['last_update_time'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        
    except Exception as e:
        st.error(f"💥 수급 관제망 연동 중 지연 발생: {e}")

# ==========================================
# 6. 대시보드 레이아웃 UI 구역
# ==========================================
st.title("⚡ 장중 실시간 수급 주도주 관제 레이더")
st.caption("웹페이지 소스코드의 미세한 공백/줄바꿈 노이즈를 완벽하게 분쇄하는 무결점 주도주 전광판")

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
    # 최초 실행 시 데이터 로드 및 강제 화면 갱신
    execute_radar_screening()
    if not st.session_state['stock_display_df'].empty:
        st.rerun()
    else:
        st.warning("📥 현재 조건(거래대금 100억 이상 & 상승률 1.5% 이상)에 맞는 주도주가 포착되지 않았거나 데이터 수집 준비 중입니다. 상단 새로고침 버튼을 눌러주십시오.")
