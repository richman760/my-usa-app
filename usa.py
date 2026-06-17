import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import pytz
import requests

st.set_page_config(layout="wide")

# 💱 1. 실시간 환율 캐싱 (10분 유지)
@st.cache_data(ttl=600)
def get_exchange_rate():
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        data = requests.get(url).json()
        return data['rates']['KRW']
    except:
        return 1400.0

# 🏢 2. 종목 정보 캐싱 (1시간 유지) -> Rate Limit 방어 1단계
@st.cache_data(ttl=3600)
def get_company_info(code):
    try:
        tk = yf.Ticker(code)
        info = tk.info
        name = info.get('shortName', info.get('longName', code))
        cap = info.get('marketCap', 0)
        return name, cap
    except:
        return code, 0

# 📈 3. [오류 해결 핵심] 차트 데이터 캐싱 (1분 유지) -> Rate Limit 완벽 차단!
@st.cache_data(ttl=60)
def get_stock_history(code):
    try:
        tk = yf.Ticker(code)
        df = tk.history(period="5d", interval="5m")
        return df
    except:
        return pd.DataFrame()

# 💾 새로고침 방어용 세션 고정
if "current_stock" not in st.session_state: st.session_state.current_stock = ""
if "code" in st.query_params: st.session_state.current_stock = st.query_params["code"]
if "search_box" not in st.session_state: st.session_state.search_box = ""

def handle_search():
    input_val = st.session_state.search_box.strip().upper()
    if input_val:
        st.session_state.current_stock = input_val
        st.query_params["code"] = input_val 
    st.session_state.search_box = ""

st.title("🇺🇸 미국장 10분봉 필승 화살표 검색기")
st.text_input("미국 주식 티커 입력 후 엔터 (예: AAPL, TSLA)", key="search_box", on_change=handle_search)

st.write("---")

@st.fragment
def render_dashboard():
    code = st.session_state.current_stock
    if not code: return
        
    try:
        # 안전하게 캐싱된 함수들로 데이터 호출
        name, market_cap = get_company_info(code)
        
        col_title, col_btn = st.columns([8, 2])
        with col_title:
            st.subheader(f"🏢 {name} ({code})")
            st.caption(f"⏱️ 마지막 데이터 갱신: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        with col_btn:
            if st.button("🔄 정보만 갱신"): st.rerun() 
                
        # 1분 동안은 야후 서버를 찌르지 않고 메모리에서 가져옴 (에러 방지)
        df_5m = get_stock_history(code)
        if df_5m.empty:
            st.warning("데이터를 불러올 수 없습니다. 티커가 잘못되었거나 서버 지연입니다.")
            return
            
        # NaN 에러 방지용 ffill 추가 후 10분봉 합성
        df_5m.ffill(inplace=True)
        df_10m = df_5m.resample('10T', label='right', closed='right').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        # 지표 계산
        delta = df_10m['Close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
        rs = gain / loss
        df_10m['RSI'] = 100 - (100 / (1 + rs))
        
        L12 = df_10m['Low'].rolling(window=12).min()
        H12 = df_10m['High'].rolling(window=12).max()
        df_10m['Fast_%K'] = 100 * ((df_10m['Close'] - L12) / (H12 - L12))
        df_10m['Slow_%K'] = df_10m['Fast_%K'].rolling(window=5).mean()
        df_10m['Slow_%D'] = df_10m['Slow_%K'].rolling(window=5).mean()
        df_10m.dropna(inplace=True)

        last_candle = df_10m.iloc[-1]
        prev_candle = df_10m.iloc[-2]
        cur_price = float(last_candle['Close'])
        cur_vol = float(last_candle['Volume'])
        cur_rsi = float(last_candle['RSI'])
        cur_k = float(last_candle['Slow_%K'])
        cur_d = float(last_candle['Slow_%D'])
        prev_k = float(prev_candle['Slow_%K'])
        prev_d = float(prev_candle['Slow_%D'])
        stop_loss = float(prev_candle['Low'])
        
        # 매매 알고리즘 및 필터링
        us_tz = pytz.timezone('US/Eastern')
        now_us = datetime.datetime.now(us_tz)
        is_opening_9_mins = (now_us.time() >= datetime.time(9, 30)) and (now_us.time() < datetime.time(9, 40))
        is_buy_signal = (cur_k <= 30) and (prev_k <= prev_d) and (cur_k > cur_d) and (cur_rsi <= 45)
        is_sell_signal = (cur_k >= 70) and (prev_k >= prev_d) and (cur_k < cur_d)
        
        # 하위권 종목은 에러가 아닌 '경고'로 처리 (형의 요청 반영)
        is_small_cap = (market_cap < 10_000_000_000) or ((cur_vol * cur_price) < 5_000_000)

        st.markdown("### 🎯 10분봉 화살표 알고리즘 결과")
        
        if is_opening_9_mins:
            st.warning("⏳ **[시간 제어 가동]** 장 시작 후 9분간은 뇌동매매 방지를 위해 대기(Hold)합니다.")
        else:
            if is_small_cap:
                st.warning("⚠️ **[주의]** 중소형주입니다. 변동성이 크니 손절가를 칼같이 지키세요.")
            
            if is_buy_signal:
                st.error("## 🟥 [매수 포착] 빨간색 화살표 발생! 🟥")
                st.info(f"**전략:** 30~50% 이분할 매수 / **손절 라인:** 직전 10분봉 최저가 **${stop_loss:.2f}**")
            elif is_sell_signal:
                st.info("## 🟦 [매도 포착] 파란색 고점 화살표 발생! 🟦")
                st.warning("**전략:** 과열권 데드크로스 발생. 분할 익절하세요.")
            else:
                st.success("## ⚪ [대기] 발생한 화살표가 없습니다.")

        st.write("---")
        
        # 환율 표시
        krw = get_exchange_rate()
        col1, col2, col3 = st.columns(3)
        col1.metric("현재가", f"${cur_price:.2f}", f"{int(cur_price*krw):,}원", delta_color="off")
        col2.metric("단기 목표 (+1.5%)", f"${cur_price*1.015:.2f}", f"{int(cur_price*1.015*krw):,}원", delta_color="off")
        col3.metric("🛡️ 손절가", f"${stop_loss:.2f}", f"{int(stop_loss*krw):,}원", delta_color="off")

        st.line_chart(df_10m['Close'])

    except Exception as e:
        st.error(f"분석 오류: {e}")

render_dashboard()
