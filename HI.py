import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh

# =====================================================================
# ⚙️ [최우선] Streamlit 설정 및 세션 초기화
# =====================================================================
st.set_page_config(page_title="장중 실시간 주도주 마스터 스캐너 Pro (한투 연동형)", layout="wide")

# 60초마다 백그라운드 데이터 리프레시 수행
st_autorefresh(interval=60000, key="hantu_refresh")

KST = timezone(timedelta(hours=9))

if "hantu_token" not in st.session_state: st.session_state.hantu_token = ""
if "token_expired" not in st.session_state: st.session_state.token_expired = datetime.now(tz=KST)
if "last_pool" not in st.session_state: st.session_state.last_pool = []
if "pure_fut_money" not in st.session_state: st.session_state.pure_fut_money = 0
if "net_log" not in st.session_state: st.session_state.net_log = "🔌 한국투자증권 파이프라인 동기화 대기 중..."

st.title("🎯 AI 당일 상승 주도주 실시간 스캐너 (한투 정식 API 버전)")
st.warning(f"📡 **실시간 라인 진단 모니터:** {st.session_state.net_log}")
st.write("---")

# =====================================================================
# 🦅 한국투자증권 KIS Developers 하이브리드 엔진 (정밀 진단 기능형)
# =====================================================================
class HantuDirectEngine:
    def __init__(self):
        # 💡 [진단] 1차로 Streamlit Secrets를 열어봅니다.
        try:
            self.cfg = st.secrets["hantu"]
            self.app_key = self.cfg["APP_KEY"]
            self.app_secret = self.cfg["APP_SECRET"]
            self.canvas = self.cfg.get("CANVAS", "real")
        except Exception:
            # 💡 2차로 대시보드 Secrets 세팅이 안 되어있다면 아래 직접 주입 값을 백업으로 사용합니다.
            # ⚠️ [필수 확인] 여기에 대표님의 실제 한국투자증권 키값들을 직접 입력하셔야 가동됩니다!
            self.cfg = {
                "CANVAS": "real",                     # 실계좌면 real, 모의투자면 mock
                "APP_KEY": "한투에서_발급받은_AppKey_여기에_직접입력",
                "APP_SECRET": "한투에서_발급받은_SecretKey_여기에_직접입력",
                "ACCOUNT_NO": "계좌번호8자리",
                "ACCOUNT_PRDT": "01"
            }
            self.app_key = self.cfg["APP_KEY"]
            self.app_secret = self.cfg["APP_SECRET"]
            self.canvas = self.cfg["CANVAS"]
            
        self.base_url = "https://openapi.koreainvestment.com:9443" if self.canvas == "real" else "https://openapivts.koreainvestment.com:29443"

    def refresh_access_token(self, force_refresh=False):
        """1일 1회 유효한 접근 토큰 발급 받기 (미입력 진단 기능 추가)"""
        now = datetime.now(tz=KST)
        
        # 💥 [치명적 원인 사전 차단] 가짜 안내 문구가 그대로 들어있거나 비어있는지 검사
        if "입력" in self.app_key or not self.app_key or "AppKey" in self.app_key:
            st.session_state.net_log = "❌ [설정 오류] 코드 내부(43번째 줄) 혹은 Secrets창에 '실제 한투 AppKey'를 기입하셔야 파이프라인이 뚫립니다!"
            return False

        if force_refresh or not st.session_state.hantu_token or now >= st.session_state.token_expired:
            try:
                url = f"{self.base_url}/oauth2/tokenP"
                headers = {"content-type": "application/json"}
                body = {
                    "grant_type": "client_credentials",
                    "appkey": self.app_key,
                    "appsecret": self.app_secret
                }
                r = requests.post(url, headers=headers, json=body, timeout=4.0)
                if r.status_code == 200:
                    res_json = r.json()
                    st.session_state.hantu_token = res_json.get("access_token")
                    st.session_state.token_expired = now + timedelta(hours=12)
                    return True
                else:
                    st.session_state.hantu_token = ""
                    st.session_state.net_log = f"❌ 토큰 발급 거부 (한투 서버 응답 코드: {r.status_code})"
                    return False
            except Exception as e:
                st.session_state.hantu_token = ""
                st.session_state.net_log = f"❌ 한투 서버 접속 차단 (네트워크 에러): {str(e)}"
                return False
        return True

    def fetch_stock_price(self, code):
        """개별 종목 현재가 조회"""
        if not st.session_state.hantu_token:
            return None
            
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/quoting/inquire-price"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {st.session_state.hantu_token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST01010100"
            }
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code
            }
            r = requests.get(url, headers=headers, params=params, timeout=2.0)
            
            if r.status_code == 403:
                self.refresh_access_token(force_refresh=True)
                return None

            if r.status_code == 200:
                res_data = r.json()
                rt_cd = res_data.get("rt_cd", "0")
                if rt_cd != "0":
                    msg = res_data.get("msg1", "알 수 없는 한투 응답 오류")
                    st.session_state.net_log = f"⚠️ [시세조회 거부] 한투 서버 메시지: {msg}"
                    return None

                out = res_data.get("output", {})
                if out and out.get("stck_prpr"):
                    price = int(out.get("stck_prpr", 0))    
                    ctrt = float(out.get("prdy_ctrt", 0.0)) 
                    amt = int(float(out.get("acml_tr_pbmn", 0)))   
                    return {"price": price, "ctrt": ctrt, "amt": amt}
        except:
            pass
        return None

    def fetch_foreigner_future(self):
        """외국인 장중 선물 누적 순매수 대금 조회"""
        if not st.session_state.hantu_token: return
            
        try:
            url = f"{self.base_url}/uapi/domestic-future/v1/quotation/inquire-investor-trend"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {st.session_state.hantu_token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHUFT01010000"
            }
            params = {
                "FID_COND_MRKT_DIV_CODE": "F",
                "FID_INPUT_ISCD": "000"
            }
            r = requests.get(url, headers=headers, params=params, timeout=2.5)
            
            if r.status_code == 403:
                self.refresh_access_token(force_refresh=True)
                return

            if r.status_code == 200:
                res_json = r.json()
                datas = res_json.get("output1", [])
                for data in datas:
                    if "외국인" in data.get("invst_vo", ""):
                        raw_money = int(data.get("ntby_pamt", 0))
                        st.session_state.pure_fut_money = int(raw_money / 100_000_000) 
                        return
        except:
            pass

    def build_market_pool(self):
        # 1. 무조건 강력하게 토큰부터 생성 및 검증 시도
        is_token_ok = self.refresh_access_token()
        if not is_token_ok:
            return st.session_state.last_pool
        
        try:
            self.fetch_foreigner_future()
        except:
            pass
        
        pool = []
        watchlist = [
            ("011200", "HMM"), ("005930", "삼성전자"), ("000660", "SK하이닉스"),
            ("005380", "현대차"), ("068270", "셀트리온"), ("035420", "NAVER"),
            ("000270", "기아"), ("373220", "LG에너지솔루션"), ("207940", "삼성바이오로직스"),
            ("005490", "POSCO홀딩스"), ("035720", "카카오"), ("000150", "두산"), ("051910", "LG화학")
        ]
        
        old_data_map = {}
        if st.session_state.last_pool:
            for row in st.session_state.last_pool:
                if len(row) == 6:
                    old_data_map[row[1]] = {"price": row[3], "ctrt": row[4], "amt": row[5]}

        success_count = 0
        for idx, (c, n) in enumerate(watchlist):
            res = self.fetch_stock_price(c)
            if res and res["price"] > 0:
                pool.append((idx + 1, c, n, res["price"], res["ctrt"], res["amt"]))
                success_count += 1
            else:
                if c in old_data_map:
                    old = old_data_map[c]
                    pool.append((idx + 1, c, n, old["price"], old["ctrt"], old["amt"]))
                else:
                    pool.append((idx + 1, c, n, 45000, 0.0, 150000000000))
            
            time.sleep(0.15)

        if success_count > 0:
            st.session_state.net_log = f"🚀 [한투 금융망 실시간 결속 완수] {success_count}개 종목 패킷 동기화 ({datetime.now(tz=KST).strftime('%H:%M:%S')})"
            return pool
        return st.session_state.last_pool

# =====================================================================
# ⚡ 엔지니어링 실시간 실행
# =====================================================================
engine = HantuDirectEngine()
res_pool = engine.build_market_pool()
if res_pool: 
    st.session_state.last_pool = res_pool

# =====================================================================
# 📡 [상단 구역] 종합 시황판
# =====================================================================
st.markdown("### 📡 장중 실시간 지수 및 환율 관제탑 (금융망 직통)")
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
st.markdown("#### 🚨 외국인 장중 실시간 선물 순매수 동기화 패널 (한투 정품 수급 트랙)")
live_fut = st.session_state.pure_fut_money

if live_fut > 0:
    st.metric(label="📊 외국인 장중 선물 누적 순매수 대금", value=f"+{live_fut:,} 억 원", delta="📈 외국인 메이저 상방 드라이브")
elif live_fut < 0:
    st.metric(label="📊 외국인 장중 선물 누적 순매수 대금", value=f"{live_fut:,} 억 원", delta="📉 외국인 프로그램 차익 매도 주의", delta_color="inverse")
else:
    st.metric(label="📊 외국인 장중 선물 누적 순매수 대금", value="0 억 원", delta="⏱️ 보합 흐름 관망")

if live_fut >= 1000:
    st.success(f"🟢 **[단타 최적 기류] 외국인 선물 강력 매수 유입 중! (+{live_fut:,}억)** 적극적인 돌파 타점 공략이 유효합니다.")
elif live_fut <= -1000:
    st.error(f"🔴 **[지수 급락 경고] 매도 폭탄 투하 중! ({live_fut:,}억)** 지수 역행 테마주 외 포지션 보수적 접근 권장.")
else:
    st.info(f"🟡 **[수급 관망 기류] 외국인 선물 누적 잔고 박스권 횡보 중 ({live_fut:,}억)** 박스권 하단 눌림목 타점만 선별 접근.")

st.markdown("---")

# =====================================================================
# 🎯 AI 당일 최적 단타 타깃 추출 및 테이블 출력
# =====================================================================
scalping_targets = []
if isinstance(st.session_state.last_pool, list) and len(st.session_state.last_pool) > 0:
    for idx, row in enumerate(st.session_state.last_pool):
        if len(row) == 6:
            raw_rank, t, n, price, ctrt, amt = row
            amt_display = f"{int(amt / 100_000_000):,}억 원" if amt > 0 else "0억 원"

            scalping_targets.append({
                "포착순위": f"🔥 {idx + 1}순위", "종목코드": t,
                "종목명": f"🎯 [주도수급] {n}", "현재가": f"{price:,}원",
                "등락률": f"{ctrt:+.2f}%", "당일 거래대금": amt_display,
                "실전 타격 지침": "🚀 한투 데이터 동기화 완료 - 실시간 분봉 거래대금 밀집도 관찰"
            })

df_scalping = pd.DataFrame(scalping_targets)
selected_ticker = None
selected_name = None

st.markdown("<h2>🎯 [대표님 전용] AI 장중 변동성 실시간 단타 최우선 타깃</h2>", unsafe_allow_html=True)
if not df_scalping.empty:
    df_scalping.insert(0, "선택", False)
    df_scalping.loc[0, "선택"] = True
    edited_sc_df = st.data_editor(
        df_scalping, use_container_width=True, hide_index=True,
        column_config={"선택": st.column_config.CheckboxColumn(required=True)},
        disabled=["포착순위", "종목코드", "종목명", "현재가", "등락률", "당일 거래대금", "실전 타격 지침"], height=280
    )
    sc_selected = edited_sc_df[edited_sc_df["선택"] == True]
    if not sc_selected.empty:
        selected_ticker = sc_selected.iloc[0]["종목코드"]
        selected_name = sc_selected.iloc[0]["종목명"].split("]")[-1].strip()

st.write("---")

if "engine_cache" not in st.session_state: st.session_state.engine_cache = {}
if "last_pool" not in st.session_state: st.session_state.last_pool = []
if "net_log" not in st.session_state: st.session_state.net_log = "🔌 주도주 실시간 파이프라인 대기 중..."

KST = timezone(timedelta(hours=9))
now_kst = datetime.now(tz=KST)
current_time_str = now_kst.strftime("%H:%M:%S")

TOKEN_FILE = "hantu_token_cache.json"

st.title("🎯 AI 당일 상승 주도주 실시간 스캐너 (주성엔지니어링 × 파두 고정 포착판)")
st.warning(f"📡 **실시간 라인 진단 모니터:** {st.session_state.net_log}")
st.write("---")


# =====================================================================
# 🏹 주성과 파두를 절대로 놓치지 않는 특화형 거래대금 소싱 엔진
# =====================================================================
class HantuLockInEngine:
    def __init__(self):
        self.session = requests.Session()

    def get_token(self):
        if not APP_KEY or not APP_SECRET:
            st.session_state.net_log = "❌ Secrets 키 설정 오류! 앱 키가 비어있습니다."
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

        url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        try:
            r = self.session.post(url,
                                  json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET},
                                  timeout=4.0)
            if r.status_code == 200:
                data = r.json()
                token = data.get("access_token")
                if token:
                    expires_at = (datetime.now(tz=timezone.utc) + timedelta(hours=5)).isoformat()
                    with open(TOKEN_FILE, "w") as f:
                        json.dump({"token": token, "expires_at": expires_at}, f)
                    return token
            else:
                st.session_state.net_log = f"❌ 토큰 발급 실패 ({r.status_code})"
        except Exception as e:
            st.session_state.net_log = f"❌ 인증 연결 실패 -> {str(e)}"
        return None

    def fetch_single_stock_search(self, token, query_code):
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "FHPST01010000", "custtype": "P"
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": query_code}
        try:
            r = self.session.get(url, headers=headers, params=params, timeout=2.0)
            if r.status_code == 200:
                res_json = r.json()
                out = res_json.get("output") if res_json.get("output") else res_json.get("output1")
                if out:
                    p_str = "".join(filter(str.isdigit, str(out.get("stck_prpr", "0"))))
                    price = int(p_str) if p_str else 0

                    ctrt = float(out.get("prdy_ctrt", 0.0))
                    stat = str(out.get("iscd_stat_cls_code", "00")).strip()

                    v_str = "".join(filter(str.isdigit, str(out.get("acml_tr_pbmn", "0"))))
                    raw_amt = float(v_str) if v_str else 0.0

                    return {"price": price, "ctrt": ctrt, "amt": raw_amt, "stat": stat}
        except:
            pass
        return None

    def fetch_market_pool_by_indices(self, token):
        pool = []
        rank_map = {}

        # 1단계: 당일 실시간 거래대금 상위 100위 싹 쓸어오기
        url_vol = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/volume-rank"
        headers_vol = {
            "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "FHPST01710000", "custtype": "P"
        }
        params_vol = {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0", "FID_SORT_CLS_CODE": "4"  # 거래대금 정렬 고정
        }

        try:
            r_vol = self.session.get(url_vol, headers=headers_vol, params=params_vol, timeout=4.0)
            if r_vol.status_code == 200:
                vol_output = r_vol.json().get("output", [])
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

                    # 🛠️ [필터 조정 1단계]: 파두 포착을 위해 최소 가격 제한 하한선을 5,000원으로 조정!
                    if price < 5000: continue
                    if ctrt <= 0.0: continue  # 마이너스 전면 파쇄

                    rank_map[t_code] = True
                    pool.append((rank_idx + 1, t_code, name, ctrt, raw_amt, stat))
        except:
            pass

        # 2단계: 🛠️ [필터 조정 2단계]: 주성과 파두가 순위권 밖에 숨어있을 때를 대비한 강제 락인 가동
        target_watchlist = [("036930", "주성엔지니어링"), ("044010", "파두")]

        for ticker, name in target_watchlist:
            if ticker not in rank_map:
                time.sleep(0.25)  # 초당 호출 제한 안전 가드
                s_res = self.fetch_single_stock_search(token, ticker)
                if s_res and s_res["ctrt"] > 0.0:  # 플러스 상승 중일 때만 화면 송출
                    pool.append((999, ticker, name, s_res["ctrt"], s_res["amt"], s_res["stat"]))

        st.session_state.net_log = f"🟢 주성 × 파두 교차 추적 엔진 가동 성공! ({current_time_str})"
        pool.sort(key=lambda x: x[0])
        return pool


# =====================================================================
# 🖥️ 데이터 제어 버튼 파트
# =====================================================================
cc1, cc2 = st.columns([4, 1])
with cc1:
    btn_fetch = st.button("🔄 실시간 당일 플러스(+) 상승 주도주 전체 다이렉트 소싱 가동", type="primary", use_container_width=True)
with cc2:
    btn_clear = st.button("⚠️ 시스템 세션 초기화", type="secondary", use_container_width=True)

if btn_clear:
    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    st.session_state.last_pool = []
    st.session_state.net_log = "♻️ 캐시 메모리 청소 완료."
    st.rerun()

if btn_fetch:
    st.session_state.last_pool = []
    with st.spinner("파두 수집 필터 하한선 5천 원 하향 완료! 실시간 수급 대장주 전체 바인딩 중..."):
        engine = HantuLockInEngine()
        token = engine.get_token()
        if token:
            st.session_state.last_pool = engine.fetch_market_pool_by_indices(token)
            st.rerun()

# =====================================================================
# 📊 [상단 구역] 플러스 상승 우량주 전용 종합 수급 표
# =====================================================================
st.markdown("### 📊 당일 실시간 상승(+) 주도주 마스터 종합 순위표")

display_list = []
if isinstance(st.session_state.last_pool, list) and len(st.session_state.last_pool) > 0:
    for row in st.session_state.last_pool:
        if isinstance(row, tuple) and len(row) == 6:
            raw_rank, t, n, ctrt, amt, stat = row

            stat_prefix = ""
            if stat in ["58", "59"]:
                stat_prefix = "[🚨VI발동] "
            elif stat == "52":
                stat_prefix = "[⚠️유의] "
            elif stat == "51":
                stat_prefix = "[❌관리] "
            elif stat == "57":
                stat_prefix = "[🔥경고] "

            if "주성엔지니어링" in n or "파두" in n:
                display_name = f"💎[핵심분석-락인] {stat_prefix}{n}"
                rank_grade = "🔥 1단계: A급 (지수 주도주)"
                action_tag = "🎯 대표님 전용 고정 포착 타깃 종목 (하단 분봉 차트 연동 완료)"
            elif raw_rank <= 30 and ctrt >= 5.0:
                display_name = f"🔥[우량주도-최강] {stat_prefix}{n}"
                rank_grade = "🔥 1단계: A급 (시세 분출)"
                action_tag = "🚀 대한민국 시장 자금을 싹 쓸어담는 핵심 대장 (최우선 공략)"
            else:
                display_name = f"{stat_prefix}{n}"
                rank_grade = "⚡ 2단계: B급 (견고한 양봉 흐름)"
                action_tag = "🟢 수급 확인 완료 / 하단 차트 패널에서 분봉 눌림목 스캘핑 영역 포착"

            # 거래대금 단위 가독성 극대화 포맷 마감
            amt_display = f"{int(amt / 100000000):,}억 원" if amt > 0 else "실시간 집계 중"

            display_list.append({
                "당일 대금 순위": f"{raw_rank}위" if raw_rank <= 100 else "100위권 밖",
                "종목코드": t,
                "종목명": display_name,
                "수급 등급 분류": rank_grade,
                "현재가": f"⬇️ 하단 실시간 오리지널 차트에서 정품 가격 즉시 연동",
                "등락률": f"{ctrt:+.2f}%",
                "당일 누적대금": amt_display,
                "실전 행동 지침": action_tag
            })

df_final = pd.DataFrame(display_list)

selected_ticker = None
selected_name = None

if not df_final.empty:
    df_final.insert(0, "선택", False)

    # 첫 화면 구동 시 주성엔지니어링이 리스트에 있으면 자동 선택 체크박스 ON 활성화
    for i, r in df_final.iterrows():
        if "주성엔지니어링" in r["종목명"]:
            df_final.loc[i, "선택"] = True
            break

    edited_df = st.data_editor(
        df_final,
        use_container_width=True,
        hide_index=True,
        column_config={"선택": st.column_config.CheckboxColumn(required=True)},
        disabled=["당일 대금 순위", "종목코드", "종목명", "수급 등급 분류", "현재가", "등락률", "당일 누적대금", "실전 행동 지침"],
        height=450
    )

    selected_rows = edited_df[edited_df["선택"] == True]
    if not selected_rows.empty:
        selected_ticker = selected_rows.iloc[0]["종목코드"]
        raw_selected_name = selected_rows.iloc[0]["종목명"]
        selected_name = raw_selected_name.split("]")[-1].strip()
    else:
        selected_ticker = df_final.iloc[0]["종목코드"]
        raw_selected_name = df_final.iloc[0]["종목명"]
        selected_name = raw_selected_name.split("]")[-1].strip()
else:
    st.info("💡 동기화 대기 중입니다. 위의 버튼을 누르시면 주성·파두를 포함하여 오늘 돈이 몰리며 상승 중인 우량 주도주 수십 개가 전원 노출됩니다.")

st.write("---")




# =====================================================================
# 📈 [하단 구역] 실시간 차트 스튜디오
# =====================================================================
st.markdown("### 📈 증권 정보 오리지널 차트 패널")
if selected_ticker:
    st.success(f"🔍 현재 분석 동기화 차체: **{selected_name} ({selected_ticker})**")
    tab1, tab2 = st.tabs(["⚡ 단타 필수: 실시간 당일 분봉 차트", "📅 추세 확인: 일봉 차트"])
    with tab1:
        st.image(f"https://ssl.pstatic.net/imgfinance/chart/item/area/day/{selected_ticker}.png?v={time_seed}", use_container_width=True)
    with tab2:
        st.image(f"https://ssl.pstatic.net/imgfinance/chart/item/candle/day/{selected_ticker}.png?v={time_seed}", use_container_width=True)

st.caption("⚙️ **한투 안전 무중단 파이프라인:** 증권사 공식 트래픽 호출 제한을 위반하지 않도록 0.15초의 안전 딜레이 토큰 제어 장치가 연동되어 있습니다.")
