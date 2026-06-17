import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import pytz
import requests
import plotly.graph_objects as go

st.set_page_config(layout="wide")

# 1. 캐싱 설정 (서버 차단 방지 및 속도 최적화)
@st.cache_data(ttl=600)
def get_exchange_rate():
    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        data = requests.get(url).json()
        return data['rates']['KRW']
    except: return 1400.0

@st.cache_data(ttl=3600)
def get_company_info(code):
    try:
        tk = yf.Ticker(code)
        info = tk.info
        return info.get('shortName', info.get('longName', code)), info.get('marketCap', 0)
    except: return code, 0

@st.cache_data(ttl=60)
def get_stock_history(code):
    try:
        tk = yf.Ticker(code)
        return tk.history(period="5d", interval="5m")
    except: return pd.DataFrame()

# 2. 세션 상태 초기화
if "current_stock" not in st.session_state: st.session_state.current_stock = ""
if "favorites" not in st.session_state: st.session_state.favorites = []
if "search_box" not in st.session_state: st.session_state.search_box = ""

def handle_search():
    input_val = st.session_state.get("search_box", "").strip().upper()
    if input_val:
        st.session_state.current_stock = input_val
        st.query_params["code"] = input_val
    st.session_state.search_box = ""

# 3. 사이드바 (관심종목)
st.sidebar.title("⭐ 관심 종목 (최대 6개)")
for fav in st.session_state.favorites[:]: # 복사본으로 순회
    if st.sidebar.button(f"🔍 {fav}"):
        st.session_state.current_stock = fav
        st.rerun()

st.title("🇺🇸 미국장 10분봉 필승 화살표 검색기")
st.text_input("미국 주식 티커 입력 후 엔터 (예: AAPL, TSLA)", key="search_box", on_change=handle_search)

# 4. 화면 렌더링
@st.fragment
def render_dashboard():
    code = st.session_state.current_stock
    if not code: return
    
    try:
        name, market_cap = get_company_info(code)
        
        # 상단 UI
        col_title, col_fav = st.columns([8, 2])
        with col_title:
            st.subheader(f"🏢 {name} ({code})")
        with col_fav:
            is_fav = code in st.session_state.favorites
            if st.button("⭐ 삭제" if is_fav else "☆ 추가"):
                if is_fav:
                    st.session_state.favorites.remove(code)
                    st.toast("북마크에서 제거되었습니다.", icon="✅")
                else:
                    if len(st.session_state.favorites) < 6:
                        if code not in st.session_state.favorites:
                            st.session_state.favorites.append(code)
                            st.toast("북마크에 추가되었습니다!", icon="⭐")
                    else:
                        st.toast("⚠️ 최대 6개까지만 가능합니다.", icon="⚠️")
                st.rerun()
        
        st.caption(f"⏱️ 마지막 갱신: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if st.button("🔄 정보만 갱신"): st.rerun()

        # 데이터 처리
        df_5m = get_stock_history(code)
        if df_5m.empty: return
        df_5m.ffill(inplace=True)
        df_10m = df_5m.resample('10min', label='right', closed='right').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last', 'Volume':'sum'}).dropna()

        # 지표
        delta = df_10m['Close'].diff()
        df_10m['RSI'] = 100 - (100 / (1 + (delta.clip(lower=0).rolling(14).mean() / -delta.clip(upper=0).rolling(14).mean())))
        L12, H12 = df_10m['Low'].rolling(12).min(), df_10m['High'].rolling(12).max()
        df_10m['SlowK'] = (100 * ((df_10m['Close'] - L12) / (H12 - L12))).rolling(5).mean()
        df_10m['SlowD'] = df_10m['SlowK'].rolling(5).mean()
        
        # 신호
        df_10m['Buy'] = (df_10m['SlowK'] <= 30) & (df_10m['SlowK'].shift(1) <= df_10m['SlowD'].shift(1)) & (df_10m['SlowK'] > df_10m['SlowD']) & (df_10m['RSI'] <= 45)
        df_10m['Sell'] = (df_10m['SlowK'] >= 70) & (df_10m['SlowK'].shift(1) >= df_10m['SlowD'].shift(1)) & (df_10m['SlowK'] < df_10m['SlowD'])

        # 차트
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_10m.index, y=df_10m['Close'], name='주가', line=dict(color='white', width=1)))
        b = df_10m[df_10m['Buy']]
        s = df_10m[df_10m['Sell']]
        fig.add_trace(go.Scatter(x=b.index, y=b['Close'], mode='markers', name='매수', marker=dict(color='red', size=10, symbol='triangle-up')))
        fig.add_trace(go.Scatter(x=s.index, y=s['Close'], mode='markers', name='매도', marker=dict(color='blue', size=10, symbol='triangle-down')))
        fig.update_layout(template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), height=400)
        st.plotly_chart(fig, use_container_width=True)

        # 결과
        last = df_10m.iloc[-1]
        is_small = (market_cap < 10_000_000_000) or ((last['Volume'] * last['Close']) < 5_000_000)
        
        if is_small: st.warning("⚠️ 중소형주 주의")
        if last['Buy']: st.error("🟥 [매수 포착] 진입 구간!")
        elif last['Sell']: st.info("🟦 [매도 포착] 익절 구간!")
        else: st.success("⚪ 대기 중")

        krw = get_exchange_rate()
        c1, c2, c3 = st.columns(3)
        c1.metric("현재가", f"${last['Close']:.2f}", f"{int(last['Close']*krw):,}원")
        c2.metric("목표가", f"${last['Close']*1.015:.2f}", f"{int(last['Close']*1.015*krw):,}원")
        c3.metric("손절가", f"${df_10m.iloc[-2]['Low']:.2f}", f"{int(df_10m.iloc[-2]['Low']*krw):,}원")

    except Exception as e: st.error(f"오류: {e}")

render_dashboard()
