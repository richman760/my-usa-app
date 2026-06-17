import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import pytz
import requests

st.set_page_config(layout="wide")

# 💱 실시간 환율 가져오기 (10분마다 갱신)
@st.cache_data(ttl=600)
def get_exchange_rate():
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        data = requests.get(url).json()
        return data['rates']['KRW']
    except:
        return 1400.0 # API 오류 시 기본값

# 💾 새로고침(F5) 방어용 URL 세션 고정
if "current_stock" not in st.session_state:
    st.session_state.current_stock = ""
if "code" in st.query_params:
    st.session_state.current_stock = st.query_params["code"]
if "search_box" not in st.session_state:
    st.session_state.search_box = ""

# 🧹 검색 실행 후 검색창 깔끔하게 비우기
def handle_search():
    input_val = st.session_state.search_box.strip().upper()
    if input_val:
        st.session_state.current_stock = input_val
        st.query_params["code"] = input_val 
    st.session_state.search_box = ""

st.title("🇺🇸 미국장 10분봉 필승 화살표 검색기")
st.text_input("미국 주식 티커 입력 후 엔터 (예: AAPL, TSLA)", key="search_box", on_change=handle_search)

st.write("---")

# 🚀 [핵심] 화면 깜빡임 없이 데이터만 갱신하는 특수 구역 (Fragment)
@st.fragment
def render_dashboard():
    code = st.session_state.current_stock
    if not code:
        return
        
    try:
        ticker = yf.Ticker(code)
        info = ticker.info
        name = info.get('longName', code)
        
        # 🏢 상단 헤더 및 부분 갱신 버튼
        col_title, col_btn = st.columns([8, 2])
        with col_title:
            st.subheader(f"🏢 {name} ({code})")
            st.caption(f"⏱️ 마지막 데이터 갱신: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        with col_btn:
            if st.button("🔄 정보만 갱신 (깜빡임 없음)"):
                st.rerun() 
                
        # 데이터 수집 (5분봉 -> 10분봉 합성)
        df_5m = ticker.history(period="5d", interval="5m")
        if df_5m.empty:
            st.warning("데이터를 불러올 수 없거나 티커가 잘못되었습니다.")
            return
            
        df_10m = df_5m.resample('10T', label='right', closed='right').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        # 지표 계산 (RSI, 스토캐스틱)
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

        # 캔들 데이터 추출
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
        
        market_cap = info.get('marketCap', 0)
        trading_value = cur_vol * cur_price

        # 🕒 미국 동부 시간 제어 (09:30 ~ 09:39 차단)
        us_tz = pytz.timezone('US/Eastern')
        now_us = datetime.datetime.now(us_tz)
        is_opening_9_mins = (now_us.time() >= datetime.time(9, 30)) and (now_us.time() < datetime.time(9, 40))

        # 🤖 화살표 알고리즘 로직
        is_buy_signal = (cur_k <= 30) and (prev_k <= prev_d) and (cur_k > cur_d) and (cur_rsi <= 45)
        is_sell_signal = (cur_k >= 70) and (prev_k >= prev_d) and (cur_k < cur_d)

        # 💱 환율 변환 계산
        krw_rate = get_exchange_rate()
        target_usd = cur_price * 1.015  # 단기 1.5% 목표가
        
        price_krw = cur_price * krw_rate
        target_krw = target_usd * krw_rate
        stop_krw = stop_loss * krw_rate

        st.markdown("### 🎯 10분봉 화살표 알고리즘 결과")
        
        # 신호 출력부
        if is_opening_9_mins:
            st.warning("⏳ **[시간 제어 가동]** 장 시작 후 9분간은 뇌동매매 방지를 위해 대기(Hold)합니다.")
        elif market_cap < 10_000_000_000 or trading_value < 5_000_000:
            st.error("⚠️ **[대장주 필터 아웃]** 시가총액 또는 10분 거래대금 미달 (잡주 매매 금지)")
        else:
            if is_buy_signal:
                st.error("## 🟥 [매수 포착] 빨간색 화살표 발생! 🟥")
                st.info(f"**전략:** 30~50% 이분할 매수 / **손절 라인:** 직전 10분봉 최저가 **${stop_loss:.2f} ({int(stop_krw):,}원)**")
            elif is_sell_signal:
                st.info("## 🟦 [매도 포착] 파란색 고점 화살표 발생! 🟦")
                st.warning("**전략:** 과열권 데드크로스 발생. 분할 익절하세요.")
            else:
                st.success("## ⚪ [대기] 발생한 화살표가 없습니다. ⚪")
                st.write("기계적으로 다음 10분봉 정각을 기다리세요.")

        st.write("---")
        
        # 💵 달러와 원화 동시 표시 패널
        st.markdown(f"**💡 실시간 환율 적용: 1달러 = {krw_rate:,.1f}원**")
        
        # delta 기능을 이용해 아래에 원화를 회색(off)으로 깔끔하게 표시
        col1, col2, col3 = st.columns(3)
        col1.metric("현재가", f"${cur_price:.2f}", f"{int(price_krw):,}원", delta_color="off")
        col2.metric("단기 목표가 (+1.5%)", f"${target_usd:.2f}", f"{int(target_krw):,}원", delta_color="off")
        col3.metric("🛡️ 손절가", f"${stop_loss:.2f}", f"{int(stop_krw):,}원", delta_color="off")

        st.write("---")
        
        # 지표 표시
        col_i1, col_i2 = st.columns(2)
        col_i1.metric("RSI (14)", f"{cur_rsi:.1f}")
        col_i2.metric("Stoch %K", f"{cur_k:.1f}")

        # 차트 출력
        st.markdown("##### 📈 10분봉 주가 흐름")
        st.line_chart(df_10m['Close'])

    except Exception as e:
        st.error(f"데이터 분석 오류: {e}")

# 구역 렌더링 실행
render_dashboard()