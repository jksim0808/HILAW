import streamlit as st
import pandas as pd
import requests
import time
import os
import json
from datetime import datetime, timezone, timedelta

# =====================================================================
# ⚙️ [최우선] Streamlit 설정 및 세션 초기화
# =====================================================================
st.set_page_config(page_title="장중 실시간 주도주 마스터 스캐너 Pro", layout="wide")

APP_KEY = st.secrets.get("HANTU_APP_KEY", "").strip()
APP_SECRET = st.secrets.get("HANTU_APP_SECRET", "").strip()
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = st.secrets.get("CHAT_ID", "").strip()

if "engine_cache" not in st.session_state: st.session_state.engine_cache = {}
if "last_pool" not in st.session_state: st.session_state.last_pool = []
if "net_log" not in st.session_state: st.session_state.net_log = "🔌 주도주 실시간 파이프라인 대기 중..."
if "pure_fut_money" not in st.session_state: st.session_state.pure_fut_money = 0

KST = timezone(timedelta(hours=9))
TOKEN_FILE = "hantu_token_cache.json"

st.title("🎯 AI 당일 상승 주도주 실시간 스캐너 (순수 거래대금 대장주 전광판)")
st.warning(f"📡 **실시간 라인 진단 모니터:** {st.session_state.net_log}")
st.write("---")

# =====================================================================
# 🏹 대한민국 시장 돈의 흐름을 1위부터 긁어오는 정순위 수급 엔진
# =====================================================================
class HantuPureSpeedEngine:
    def __init__(self):
        self.session = requests.Session()
        
    def get_token(self):
        if not APP_KEY or not APP_SECRET:
            st.session_state.net_log = "❌ Secrets 내부에 HANTU_APP_KEY 또는 HANTU_APP_SECRET 설정이 유실되었습니다."
            return None

        now_utc = datetime.now(tz=timezone.utc)

        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, "r") as f:
                    cache = json.load(f)
                expire_time = datetime.fromisoformat(cache["expires_at"])
                if expire_time > now_utc and cache.get("token"):
                    return cache["token"]
            except:
                pass

        url = "https://openapi.koreainvestment.com/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials", 
            "appkey": APP_KEY, 
            "appsecret": APP_SECRET
        }
        try:
            # ⚡ [타임아웃 최적화 수술] 네트워크 지연 시 무한 대기를 막기 위해 패킷 제한 세팅
            r = self.session.post(url, json=body, timeout=3.5)
            if r.status_code == 200:
                data = r.json()
                token = data.get("access_token")
                if token:
                    expires_at = (datetime.now(tz=timezone.utc) + timedelta(hours=5)).isoformat()
                    with open(TOKEN_FILE, "w") as f:
                        json.dump({"token": token, "expires_at": expires_at}, f)
                    return token
            else:
                st.session_state.net_log = "⚠️ 한투 인증 게이트 과부하 / 60초 후 자동 재접속 기동"
        except:
            st.session_state.net_log = "🔌 한투망 물리적 지연 발생 / 백그라운드 무중단 실시간 재연결 추적 엔진 가동 중"
        return None

    def fetch_live_foreigner_future(self, token):
        if not token: return
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/investor-trend-by-market"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET,
            "tr_id": "FHPST06430000", "custtype": "P"
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "0000"}
        try:
            r = self.session.get(url, headers=headers, params=params, timeout=2.5)
            if r.status_code == 200:
                outputs = r.json().get("output1", [])
                for row in outputs:
                    stts_name = row.get("prsn_stts_name", "").strip()
                    if "외국인" in stts_name or "외국" in stts_name:
                        net_val = row.get("ntby_money", row.get("ntby_amt", "0"))
                        st.session_state.pure_fut_money = int(float(net_val) / 100)
                        break
        except: pass

    def fetch_single_stock_backup(self, token, query_code):
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "FHPST01010000", "custtype": "P"
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": query_code}
        try:
            r = self.session.get(url, headers=headers, params=params, timeout=2.5)
            if r.status_code == 200:
                out = r.json().get("output", {})
                if out:
                    p_str = "".join(filter(str.isdigit, str(out.get("stck_prpr", "0"))))
                    price = int(p_str) if p_str else 0
                    ctrt = float(out.get("prdy_ctrt", 0.0))
                    stat = str(out.get("iscd_stat_cls_code", "00")).strip()
                    v_str = "".join(filter(str.isdigit, str(out.get("acml_tr_pbmn", "0"))))
                    raw_amt = float(v_str) if v_str else 0.0
                    return {"price": price, "ctrt": ctrt, "amt": raw_amt, "stat": stat}
        except: pass
        return None

    def fetch_market_pool_by_indices(self, token):
        if not token: return st.session_state.last_pool
        pool = []
        rank_map = {}
        
        self.fetch_live_foreigner_future(token)
        
        url_vol = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/volume-rank"
        headers_vol = {
            "content-type": "application/json; charset=utf-8", 
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET, 
            "tr_id": "FHPST01710000", "custtype": "P"
        }
        params_vol = {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0", "FID_SORT_CLS_CODE": "4",       
            "FID_BLNG_CLS_CODE": "0", "FID_TRGT_CLS_CODE": "00000000", "FID_TRGT_EXCL_CLS_CODE": "00000000",
            "FID_INPUT_PRICE_1": "0", "FID_INPUT_PRICE_2": "0", "FID_VOL_CNT": "", "FID_INPUT_DATE_1": ""          
        }
        
        try:
            r_vol = self.session.get(url_vol, headers=headers_vol, params=params_vol, timeout=3.5)
            if r_vol.status_code == 200:
                vol_output = r_vol.json().get("output", [])
                mega_cap_codes = ["005930", "000660", "005380", "000270", "005490", "035420", "035720", "068270", "207940", "051910", "006400", "012450", "011200", "000150", "373220"]
                
                for rank_idx, item in enumerate(vol_output):
                    t_code = str(item.get("mksc_shrn_iscd", "")).strip()[-6:]
                    if not t_code.isdigit(): continue
                    name = str(item.get("hts_kor_isnm", item.get("data_name", ""))).strip()
                    if any(k in name for k in ["스팩", "리츠", "인버스", "레버리지", "KODEX", "TIGER"]): continue
                    
                    p_str_raw = "".join(filter(str.isdigit, str(item.get("stck_prpr", "0"))))
                    price = int(p_str_raw) if p_str_raw else 0
                    ctrt = float(str(item.get("prdy_ctrt", "0.0")).strip())
                    stat = str(item.get("iscd_stat_cls_code", "00")).strip()
                    raw_amt = float(str(item.get("acml_tr_pbmn", "0")).strip())
                    
                    is_mega_cap = (t_code in mega_cap_codes or "하이닉스" in name or "삼성전자" in name or "현대차" in name)
                    if price < 5000 and not is_mega_cap: continue
                    if ctrt <= 0.0 and not is_mega_cap: continue 
                    
                    rank_map[t_code] = True
                    pool.append((rank_idx + 1, t_code, name, price, ctrt, raw_amt, stat))
                
                watchlist_backups = [("000660", "SK하이닉스"), ("005930", "삼성전자")]
                for b_code, b_name in watchlist_backups:
                    if b_code not in rank_map:
                        time.sleep(0.1) 
                        b_res = self.fetch_single_stock_backup(token, b_code)
                        if b_res: pool.append((999, b_code, b_name, b_res["price"], b_res["ctrt"], b_res["amt"], b_res["stat"]))
                
                st.session_state.net_log = f"🟢 한투 실전망 대장주 순수 동기화 완료! ({datetime.now(tz=KST).strftime('%H:%M:%S')})"
                pool.sort(key=lambda x: x[0])
                return pool
        except:
            pass
        return st.session_state.last_pool

# =====================================================================
# ⚡ [상시 표출 시스템 브릿지]
# =====================================================================
engine = HantuPureSpeedEngine()
token = engine.get_token()
if token:
    res_pool = engine.fetch_market_pool_by_indices(token)
    if res_pool: st.session_state.last_pool = res_pool

# =====================================================================
# 📡 [상단 구역] 네이버 오리지널 실시간 캔들 시황판 이식
# =====================================================================
st.markdown("### 📡 장중 실시간 지수 및 환율 관제탑 (오리지널 금융망 직통)")

time_seed = int(time.time())
col_radar1, col_radar2 = st.columns(2)

with col_radar1:
    st.markdown("**📊 KOSPI 종합 지수 실시간 흐름**")
    st.image(f"https://ssl.pstatic.net/imgfinance/chart/main/KOSPI.png?sid={time_seed}", use_container_width=True)

with col_radar2:
    st.markdown("**💵 원/달러 환율 실시간 추이**")
    st.image(f"https://ssl.pstatic.net/imgfinance/chart/marketindex/FX_USDKRW.png?sid={time_seed}", use_container_width=True)

# =====================================================================
# 🚦 3단계 수급 행동명령 신호등 전광판
# =====================================================================
st.markdown("#### 🚨 외국인 장중 실시간 선물 순매수 동기화 패널 (순정 하이브리드 트랙)")
live_fut = st.session_state.pure_fut_money

if token and live_fut != 0:
    if live_fut > 0:
        st.metric(label="📊 외국인 장중 선물 누적 순매수 대금 (정품 수치)", value=f"+{live_fut:,} 억 원", delta="📈 외국인 메이저 상방 바스켓 가동")
    else:
        st.metric(label="📊 외국인 장중 선물 누적 순매수 대금 (정품 수치)", value=f"{live_fut:,} 억 원", delta="📉 외국인 프로그램 하방 압박 주의", delta_color="inverse")
    
    if live_fut >= 1000:
        st.success(f"🟢 **[단타 최적 기류] 외국인 선물 강력 매수 유입 중! (+{live_fut:,}억)** 메시지가 뜨며 안심하고 자금을 투입할 타이밍임을 알려줍니다.")
    elif live_fut <= -1000:
        st.error(f"🔴 **[지수 급락 경고] 매도로 시장을 짓누르면 매도 폭탄 투하 중! ({live_fut:,}억)** 개별 테마주 외 진입 금지 경고등을 켜서 자금을 잠그도록 보호합니다.")
    else:
        st.info(f"🟡 **[수급 관망 기류] 외국인 선물 누적 잔고 박스권 이동 중 ({live_fut:,}억)** 무리한 대형주 추격 매수를 자제하고 하단 주도 테마의 분봉 눌림목 지지선을 철저히 타격하십시오.")
else:
    st.metric(label="📊 외국인 장중 선물 누적 순매수 대금 (정품 수치)", value="연결 대기 중", delta="🔌 한투 통신망 동기화 재도전 중")
    st.info("🟡 **[수급 관망 기류] 한투 통신망 패킷 대기 중** 상단 오리지널 지수 패널의 환율 흐름이 안정되는지 관찰하며 하단 주도 테마의 진입 타점을 대기하십시오.")

st.markdown("---")

# =====================================================================
# 🖥️ 데이터 제어 버튼 파트
# =====================================================================
cc1, cc2 = st.columns([4, 1])
with cc1:
    btn_fetch = st.button("🔄 한투 실전망 당일 주도주 전체 즉시 동기화", type="primary", use_container_width=True)
with cc2:
    btn_clear = st.button("⚠️ 시스템 세션 초기화", type="secondary", use_container_width=True)

if btn_clear:
    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    st.session_state.last_pool = []
    st.session_state.net_log = "♻️ 한투 실전망 인증 세션 초기화 완료."
    st.rerun()

if btn_fetch:
    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    st.session_state.last_pool = []
    with st.spinner("한투 실전망 게이트웨이 동기화 중..."):
        st.rerun()

# =====================================================================
# 🎯 대표님 전용 실시간 최적 단타 타깃 추출 연산부
# =====================================================================
scalping_targets = []
normal_display_list = []

if isinstance(st.session_state.last_pool, list) and len(st.session_state.last_pool) > 0:
    for row in st.session_state.last_pool:
        if isinstance(row, tuple) and len(row) == 7: 
            raw_rank, t, n, price, ctrt, amt, stat = row
            
            stat_prefix = ""
            if stat in ["58", "59"]: stat_prefix = "[🚨VI발동] "
            elif stat == "52": stat_prefix = "[⚠️유의] "
            elif stat == "51": stat_prefix = "[❌관리] "
            elif stat == "57": stat_prefix = "[🔥경고] "

            mega_cap_codes = ["005930", "000660", "005380", "000270", "005490", "035420", "035720", "068270", "207940", "051910", "006400", "012450", "011200", "000150", "373220"]
            is_mega_cap = (t in mega_cap_codes or "하이닉스" in n or "삼성전자" in n or "현대차" in n)
            amt_display = f"{int(amt / 100000000):,}억 원" if amt > 0 else "실시간 집계 중"

            if raw_rank <= 20 and (4.0 <= ctrt <= 12.0) and not is_mega_cap:
                scalping_targets.append({
                    "포착순위": f"🔥 {len(scalping_targets) + 1}순위",
                    "종목코드": t,
                    "종목명": f"🎯[단타타깃] {stat_prefix}{n}",
                    "현재가": f"{price:,}원",
                    "등락률": f"{ctrt:+.2f}%",
                    "당일 거래대금": amt_display,
                    "실전 타격 지침": "🚀 거래대금 상위권 폭발! 등락률 +4%~12% 꿀맛 단타 타점 (하단 분봉 눌림목 관찰)"
                })
            
            if raw_rank == 999:
                d_name, r_grade, a_tag = f"🏛️[순위권밖-강제포획] {stat_prefix}{n}", "📊 지수 연동형 메가크라운 대형주", "⚡ 한투 100위권 밖에 위치함 / 실시간 백업 엔진 자동 연동"
            elif raw_rank <= 20 and ctrt >= 4.0 and not is_mega_cap:
                d_name, r_grade, a_tag = f"🔥[우량주도-최강] {stat_prefix}{n}", "🔥 1단계: A급 (시세 강력 분출)", "🚀 대한민국 시장 자금을 가장 빠르게 빨아들이는 핵심 대장"
            elif is_mega_cap:
                d_name, r_grade, a_tag = f"🏛️[시장지수-대장] {stat_prefix}{n}", "📊 지수 연동형 메가크라운 대형주", "⚡ 대한민국 증시 지수 상위 대장주 (장중 시황 체크용)"
            else:
                d_name, r_grade, a_tag = f"{stat_prefix}{n}", "⚡ 2단계: B급 (견고한 거래량 쏠림)", "🟢 수급 확인 완료 / 하단 차트 패널에서 분봉 파동 추적"

            normal_display_list.append({
                "당일 대금 순위": "100위권 밖" if raw_rank == 999 else f"{raw_rank}위",
                "종목코드": t,
                "종목명": d_name,
                "수급 등급 분류": r_grade,
                "현재가": f"{price:,}원", 
                "등락률": f"{ctrt:+.2f}%" if ctrt > 0 else f"{ctrt:.2f}%",
                "당일 누적대금": amt_display,
                "실전 행동 지침": a_tag
            })

df_scalping = pd.DataFrame(scalping_targets)
df_normal = pd.DataFrame(normal_display_list)

selected_ticker = None
selected_name = None

if not df_scalping.empty:
    df_scalping.insert(0, "선택", False)
    df_scalping.loc[0, "선택"] = True
    
    edited_sc_df = st.data_editor(
        df_scalping, use_container_width=True, hide_index=True,
        column_config={"선택": st.column_config.CheckboxColumn(required=True)},
        disabled=["포착순위", "종목코드", "종목명", "현재가", "등락률", "당일 거래대금", "실전 타격 지침"],
        height=200
    )
    sc_selected = edited_sc_df[edited_sc_df["선택"] == True]
    if not sc_selected.empty:
        selected_ticker = sc_selected.iloc[0]["종목코드"]
        selected_name = sc_selected.iloc[0]["종목명"].split("]")[-1].strip()
else:
    if not df_normal.empty:
        st.info("💡 지금 이 순간에는 거래대금 상위 20위 내에서 등락률 +4% ~ +12% 규격에 맞는 안전한 단타 주도주가 없습니다. 무리한 진입 금지 / 하단 마스터 시황판을 점검해 주십시오.")
    else:
        st.info("📥 한투 게이트웨이 파이프라인 무중단 재연결 동기화 중입니다. 지수 차트를 보며 잠시만 기다려주십시오.")

if not df_normal.empty:
    if not selected_ticker:
        df_normal.insert(0, "선택", False)
        df_normal.loc[0, "선택"] = True
        
        edited_nm_df = st.data_editor(
            df_normal, use_container_width=True, hide_index=True,
            column_config={"선택": st.column_config.CheckboxColumn(required=True)},
            disabled=["당일 대금 순위", "종목코드", "종목명", "수급 등급 분류", "현재가", "등락률", "당일 누적대금", "실전 행동 지침"],
            height=350
        )
        nm_selected = edited_nm_df[edited_nm_df["선택"] == True]
        if not nm_selected.empty:
            selected_ticker = nm_selected.iloc[0]["종목코드"]
            selected_name = nm_selected.iloc[0]["종목명"].split("]")[-1].strip()
    else:
        st.dataframe(df_normal, use_container_width=True, hide_index=True, height=350)

st.write("---")

# =====================================================================
# 📈 [하단 구역] 네이버 실시간 차트 스튜디오
# =====================================================================
st.markdown("### 📈 네이버 페이 증권 실시간 오리지널 차트 패널")

if selected_ticker:
    st.success(f"🔍 현재 분석 동기화 차트: **{selected_name} ({selected_ticker})**")
    
    tab1, tab2 = st.tabs(["⚡ 단타 필수: 실시간 당일 분봉 차트", "📅 추세 확인: 일봉 차트"])
    
    with tab1:
        naver_minute_chart = f"https://ssl.pstatic.net/imgfinance/chart/item/area/day/{selected_ticker}.png?v={time_seed}"
        st.image(naver_minute_chart, caption=f"[{selected_name}] 네이버 실시간 분봉 및 당일 세력 거래량 분석", use_container_width=True)
        
    with tab2:
        naver_day_chart = f"https://ssl.pstatic.net/imgfinance/chart/item/candle/day/{selected_ticker}.png?v={time_seed}"
        st.image(naver_day_chart, caption=f"[{selected_name}] 네이버 실시간 일봉 캔들 추세 지지선", use_container_width=True)

# =====================================================================
# ⏱️ [장중 상시 자동 관제]: 60초 무중단 리프레시 엔진
# =====================================================================
st.caption("⚙️ **자동 감시 시스템 가동 중:** 장중 최신 거래대금 파싱을 위해 60초마다 백그라운드 리프레시를 자동 수행합니다.")
time.sleep(60)
st.rerun()
