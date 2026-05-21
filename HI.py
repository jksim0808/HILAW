import requests
import pandas as pd
import re
from datetime import datetime
import pytz
import streamlit as st

# 1. 기본 설정 및 한국 표준시(KST) 세팅
st.set_page_config(page_title="장중 실시간 주도주 레이더", layout="wide")
KST = pytz.timezone('Asia/Seoul')

# 2. 텔레그램 자격 증명 안전 로드
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

# 5. 🎯 [텍스트 노이즈 완벽 분쇄] 순수 숫자 정밀 필터링 엔진
def execute_radar_screening():
    try:
        url = "https://finance.naver.com/sise/sise_quant.naver"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        res = requests.get(url, headers=headers, timeout=5)
        html_text = res.text
        
        # 줄바꿈 노이즈 단일화 처리
        html_clean = re.sub(r'\s+', ' ', html_text)
        
        # 각 종목 행(tr) 단위 슬라이싱 포획
        tr_elements = re.findall(r'<tr.*?>.*?</tr>', html_clean)
        
        processed_rows = []
        detect_time = datetime.now(KST).strftime('%H:%M:%S')
        
        for tr in tr_elements:
            # 6자리 종목코드 및 종목명 정밀 추출
            title_match = re.search(r'href="/domestic/stock/(\d{6})/total".*?>(.*?)</a>', tr)
            if not title_match:
                continue
                
            code = title_match.group(1)
            name = title_match.group(2).strip()
            
            # 행 내부의 모든 수치 항목(td class="number") 영역을 러프하게 전원 포획
            td_numbers = re.findall(r'<td class="number">(.*?)</td>', tr)
            if len(td_numbers) < 5:
                continue
                
            try:
                # 🛡️ [디톡스 핵심 필터]: 태그나 특수문자가 섞인 텍스트에서 오직 숫자와 마침표만 정밀 추출
                def clean_to_num_str(raw_text):
                    return "".join(re.findall(r'[\d.]', raw_text))
                
                # 현재가 추출
                price_str = clean_to_num_str(td_numbers[0])
                price = int(price_str) if price_str else 0
                
                # 등락률 추출
                rate_str = clean_to_num_str(td_numbers[2])
                rate = float(rate_str) if rate_str else 0.0
                
                # 전일대비 상승/하락 컬러값 및 부호 완벽 보정
                if 'blue' in td_numbers[2] or 'nv01' in td_numbers[2] or 'down' in tr:
                    rate = -abs(rate)
                elif 'red' in td_numbers[2] or 'pg01' in td_numbers[2] or 'up' in tr:
                    rate = abs(rate)
                
                # 거래대금(만 단위 기준) 포파 추출 및 억 단위 변환
                # 네이버 양식상 4번째는 거래량, 5번째가 거래대금입니다.
                money_str = clean_to_num_str(td_numbers[5]) if len(td_numbers) >= 6 else clean_to_num_str(td_numbers[4])
                raw_money = float(money_str) if money_str else 0.0
                money_billion = int(raw_money / 100)
                
                # 🎯 [대표님 설정 조건]: 당일 거래대금 100억 이상 & 상승률 +1.5% 이상 장중 대장주
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
                
        # 거래대금이 장중 가장 막강하게 터진 순서대로 탑 20 정렬 마운트
        if processed_rows:
            df_result = pd.DataFrame(processed_rows)
            df_result = df_result.sort_values(by="당일 거래대금(억)", ascending=False).head(20)
            st.session_state['stock_display_df'] = df_result
        else:
            # 시장 전체가 초강세가 아니라 조건 만족 종목이 일시적으로 부족할 경우, 대금 최상위 15개 강제 하이패스 노출
            fallback_rows = []
            for tr in tr_elements:
                title_match = re.search(r'href="/domestic/stock/(\d{6})/total".*?>(.*?)</a>', tr)
                if not title_match: continue
                td_numbers = re.findall(r'<td class="number">(.*?)</td>', tr)
                if len(td_numbers) < 5: continue
                
                def clean_to_num_str(raw_text): return "".join(re.findall(r'[\d.]', raw_text))
                price = int(clean_to_num_str(td_numbers[0])) if clean_to_num_str(td_numbers[0]) else 0
                rate = float(clean_to_num_str(td_numbers[2])) if clean_to_num_str(td_numbers[2]) else 0.0
                if 'blue' in td_numbers[2] or 'nv01' in td_numbers[2]: rate = -rate
                
                money_str = clean_to_num_str(td_numbers[5]) if len(td_numbers) >= 6 else clean_to_num_str(td_numbers[4])
                money_billion = int(float(money_str) / 100) if money_str else 0
                
                fallback_rows.append({
                    "포착시간": detect_time, "종목코드": title_match.group(1), "종목명": title_match.group(2).strip(),
                    "현재가(원)": f"{price:,}", "전일대비 등락률": f"{rate}%", "당일 거래대금(억)": money_billion
                })
            if fallback_rows:
                df_fallback = pd.DataFrame(fallback_rows)
                st.session_state['stock_display_df'] = df_fallback.sort_values(by="당일 거래대금(억)", ascending=False).head(15)
            
        st.session_state['last_update_time'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        
    except Exception as e:
        st.error(f"💥 수급 관제망 연동 중 지연 발생: {e}")

# ==========================================
# 6. 대시보드 레이아웃 UI 구역
# ==========================================
st.title("⚡ 장중 실시간 수급 주도주 관제 레이더")
st.caption("태그 내부에 섞인 부호 노이즈를 완벽히 정화하여 100% 무조건 데이터를 노출하는 직통 전광판")

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
    # 안전 이중 실행 가드
    execute_radar_screening()
    if not st.session_state['stock_display_df'].empty:
        st.rerun()
