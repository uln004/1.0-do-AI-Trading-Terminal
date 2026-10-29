import time
from datetime import datetime, timezone
import requests
import pandas as pd
import streamlit as st

APP_NAME = "AI Trading Terminal"
API_BASE = "https://api.binance.com"
STARTING_CASH = 1000.0
FEE_RATE = 0.001  # estimativa de 0,10% por lado; não é uma taxa real cotada
MAX_POSITIONS = 5
RISK_PER_TRADE = 0.02
MAX_POSITION_FRACTION = 0.20
TOP_ASSETS = 40

st.set_page_config(page_title=APP_NAME, page_icon="📈", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px;}
.metric-card {border:1px solid rgba(128,128,128,.3); border-radius:12px; padding:14px;}
.small-muted {font-size: .85rem; opacity: .75;}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=45, show_spinner=False)
def get_tickers():
    r = requests.get(f"{API_BASE}/api/v3/ticker/24hr", timeout=15)
    r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data)
    df["quoteVolume"] = pd.to_numeric(df["quoteVolume"], errors="coerce")
    df["lastPrice"] = pd.to_numeric(df["lastPrice"], errors="coerce")
    df["priceChangePercent"] = pd.to_numeric(df["priceChangePercent"], errors="coerce")
    df = df[df["symbol"].str.endswith("USDT", na=False)]
    df = df[~df["symbol"].str.contains(r"UPUSDT|DOWNUSDT|BULLUSDT|BEARUSDT", regex=True)]
    return df.sort_values("quoteVolume", ascending=False).head(TOP_ASSETS).reset_index(drop=True)

@st.cache_data(ttl=60, show_spinner=False)
def get_klines(symbol, interval="15m", limit=100):
    r = requests.get(f"{API_BASE}/api/v3/klines",
                     params={"symbol": symbol, "interval": interval, "limit": limit},
                     timeout=15)
    r.raise_for_status()
    raw = r.json()
    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume","close_time",
        "quote_asset_volume","number_of_trades","taker_buy_base","taker_buy_quote","ignore"
    ])
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def indicators(df):
    x = df.copy()
    x["ema9"] = x["close"].ewm(span=9, adjust=False).mean()
    x["ema21"] = x["close"].ewm(span=21, adjust=False).mean()
    delta = x["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    x["rsi"] = 100 - (100 / (1 + rs))
    x["rsi"] = x["rsi"].fillna(50)
    x["avg_volume"] = x["volume"].rolling(20).mean()
    return x

def signal_for(df):
    if len(df) < 30:
        return "AGUARDAR", "Histórico insuficiente", None
    x = indicators(df)
    last = x.iloc[-2]  # última vela fechada
    prev = x.iloc[-3]
    close = float(last["close"])
    if pd.isna(last["ema9"]) or pd.isna(last["ema21"]):
        return "AGUARDAR", "Indicadores indisponíveis", close
    if prev["ema9"] <= prev["ema21"] and last["ema9"] > last["ema21"] and 40 <= last["rsi"] <= 68:
        return "COMPRA SIMULADA", "EMA 9 cruzou acima da EMA 21; RSI dentro da faixa definida", close
    if prev["ema9"] >= prev["ema21"] and last["ema9"] < last["ema21"]:
        return "VENDA SIMULADA", "EMA 9 cruzou abaixo da EMA 21", close
    if last["rsi"] > 72:
        return "AGUARDAR", "RSI elevado; evitar entrada por impulso", close
    return "AGUARDAR", "Sem gatilho de entrada/saída nesta vela", close

def init_state():
    if "cash" not in st.session_state:
        st.session_state.cash = STARTING_CASH
        st.session_state.positions = {}
        st.session_state.trades = []
        st.session_state.logs = []
        st.session_state.last_scan = None
        st.session_state.scan_results = pd.DataFrame()

def log_event(agent, symbol, action, reason):
    st.session_state.logs.insert(0, {
        "Horário UTC": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "Agente": agent, "Ativo": symbol, "Ação": action, "Motivo": reason
    })
    st.session_state.logs = st.session_state.logs[:300]

def portfolio_value(prices):
    total = float(st.session_state.cash)
    for sym, pos in st.session_state.positions.items():
        total += pos["qty"] * float(prices.get(sym, pos["entry"]))
    return total

def scan_market(universe):
    results, prices = [], {}
    for _, row in universe.iterrows():
        symbol = row["symbol"]
        try:
            kl = get_klines(symbol, "15m", 100)
            action, reason, price = signal_for(kl)
            if price is None:
                continue
            prices[symbol] = price
            results.append({
                "Ativo": symbol, "Preço": price, "Variação 24h (%)": float(row["priceChangePercent"]),
                "Volume 24h (USDT)": float(row["quoteVolume"]), "Sinal": action, "Motivo": reason
            })
        except Exception as e:
            results.append({
                "Ativo": symbol, "Preço": float(row["lastPrice"]), "Variação 24h (%)": float(row["priceChangePercent"]),
                "Volume 24h (USDT)": float(row["quoteVolume"]), "Sinal": "ERRO DE DADOS",
                "Motivo": str(e)[:120]
            })
    return pd.DataFrame(results), prices

def execute_simulated(results, prices, risk_pct):
    if results.empty:
        return
    for _, row in results.iterrows():
        symbol = row["Ativo"]
        signal = row["Sinal"]
        price = prices.get(symbol)
        if not price or price <= 0:
            continue
        if signal == "COMPRA SIMULADA" and symbol not in st.session_state.positions:
            if len(st.session_state.positions) >= MAX_POSITIONS:
                log_event("Dimensionador", symbol, "BLOQUEADO", "Limite de posições simultâneas atingido")
                continue
            equity = portfolio_value(prices)
            budget = min(st.session_state.cash, equity * min(MAX_POSITION_FRACTION, risk_pct * 5))
            cost = budget / (1 + FEE_RATE)
            if cost < 10:
                log_event("Dimensionador", symbol, "BLOQUEADO", "Saldo livre insuficiente para a posição mínima simulada")
                continue
            fee = cost * FEE_RATE
            qty = cost / price
            st.session_state.cash -= (cost + fee)
            st.session_state.positions[symbol] = {"qty": qty, "entry": price, "entry_cost": cost + fee, "opened": datetime.now(timezone.utc).isoformat()}
            st.session_state.trades.insert(0, {
                "Horário UTC": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "Ativo": symbol, "Operação": "COMPRA SIMULADA", "Preço": price,
                "Quantidade": qty, "Taxa estimada": fee, "P&L realizado": 0.0, "Motivo": row["Motivo"]
            })
            log_event("Executor simulado", symbol, "COMPRA SIMULADA", row["Motivo"])
        elif signal == "VENDA SIMULADA" and symbol in st.session_state.positions:
            pos = st.session_state.positions.pop(symbol)
            gross = pos["qty"] * price
            fee = gross * FEE_RATE
            proceeds = gross - fee
            pnl = proceeds - pos["entry_cost"]
            st.session_state.cash += proceeds
            st.session_state.trades.insert(0, {
                "Horário UTC": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "Ativo": symbol, "Operação": "VENDA SIMULADA", "Preço": price,
                "Quantidade": pos["qty"], "Taxa estimada": fee, "P&L realizado": pnl, "Motivo": row["Motivo"]
            })
            log_event("Executor simulado", symbol, "VENDA SIMULADA", f"{row['Motivo']}; P&L realizado estimado: {pnl:.2f} USDT")

init_state()

st.title("📈 AI Trading Terminal")
st.caption("Versão 1.0 • mercado real, operações fictícias • nenhuma ordem real é enviada")
st.warning("MODO SIMULAÇÃO PERMANENTE NESTA VERSÃO. Não insira chaves de API. Este aplicativo não envia ordens à corretora.")

with st.sidebar:
    st.header("Controles")
    risk_pct = st.slider("Orçamento por posição (% do patrimônio)", 1, 4, 2, 1) / 100
    interval_note = st.selectbox("Intervalo de análise", ["15 minutos"], index=0)
    auto_scan = st.checkbox("Atualizar dados ao abrir/recarregar", value=False)
    st.caption("O scanner analisa até 40 pares USDT de maior volume. Para evitar consumo excessivo da API, a análise é acionada manualmente.")
    scan_button = st.button("🔎 Consultar mercado e simular", type="primary", use_container_width=True)
    reset_button = st.button("♻️ Reiniciar simulação", use_container_width=True)
    st.caption("O estado da simulação fica na sessão do navegador e pode ser perdido ao reiniciar a aplicação.")

if reset_button:
    for key in ["cash", "positions", "trades", "logs", "last_scan", "scan_results"]:
        if key in st.session_state:
            del st.session_state[key]
    init_state()
    st.rerun()

try:
    tickers = get_tickers()
    live_prices = dict(zip(tickers["symbol"], tickers["lastPrice"]))
    st.caption(f"Dados de mercado via API pública • atualização do ticker em cache de até 45 s • {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} (hora do dispositivo)")
except Exception as e:
    tickers = pd.DataFrame()
    live_prices = {}
    st.error(f"Não foi possível consultar a API de mercado agora: {e}")
    st.info("Verifique a conexão e tente novamente. A API pode limitar solicitações ou estar indisponível.")

if scan_button and not tickers.empty:
    with st.spinner("Os agentes estão analisando os pares selecionados…"):
        results, prices = scan_market(tickers)
        st.session_state.scan_results = results
        st.session_state.last_scan = datetime.now(timezone.utc).isoformat()
        execute_simulated(results, prices, risk_pct)
        log_event("Scanner", "UNIVERSO USDT", "ANÁLISE CONCLUÍDA", f"{len(results)} ativos analisados; execução apenas simulada.")
    st.success(f"Análise concluída: {len(results)} ativos processados. Nenhuma ordem real foi enviada.")

results = st.session_state.scan_results
if not results.empty:
    for _, r in results.iterrows():
        live_prices[r["Ativo"]] = r["Preço"]

equity = portfolio_value(live_prices)
unrealized = 0.0
for sym, pos in st.session_state.positions.items():
    px = live_prices.get(sym, pos["entry"])
    unrealized += pos["qty"] * px - pos["entry_cost"]
realized = sum(float(t.get("P&L realizado", 0)) for t in st.session_state.trades)
total_pnl = equity - STARTING_CASH

c1, c2, c3, c4 = st.columns(4)
c1.metric("Patrimônio virtual", f"${equity:,.2f}", f"{total_pnl:+,.2f} USDT")
c2.metric("Saldo livre", f"${st.session_state.cash:,.2f}")
c3.metric("Posições abertas", str(len(st.session_state.positions)), f"limite {MAX_POSITIONS}")
c4.metric("P&L realizado", f"${realized:,.2f}")

tabs = st.tabs(["📊 Mercado", "🧠 Seis agentes", "💼 Carteira", "🧾 Histórico", "⚙️ Regras e limites"])
with tabs[0]:
    st.subheader("Scanner de mercado")
    st.caption("Os sinais são regras técnicas demonstrativas, não recomendações financeiras. Clique em “Consultar mercado e simular” para gerar uma rodada.")
    if not tickers.empty:
        market_view = tickers[["symbol","lastPrice","priceChangePercent","quoteVolume"]].copy()
        market_view.columns = ["Ativo","Preço atual (USDT)","Variação 24h (%)","Volume 24h (USDT)"]
        st.dataframe(market_view, use_container_width=True, hide_index=True)
    if not results.empty:
        st.subheader("Sinais da última análise")
        st.dataframe(results.sort_values(["Sinal","Volume 24h (USDT)"], ascending=[True,False]), use_container_width=True, hide_index=True)
    else:
        st.info("Ainda não há uma análise executada. Toque no botão da barra lateral para começar.")
with tabs[1]:
    st.subheader("Central dos agentes")
    agents = [
        ("1. Scanner","Busca pares USDT com maior volume e lê candles de 15 minutos.","Consulta dados públicos; não opera."),
        ("2. Filtro de risco","Exclui pares alavancados identificáveis pelo nome e exige volume de mercado.","Não detecta todos os golpes, riscos de contrato ou manipulações."),
        ("3. Dimensionador","Limita cada posição a até 20% do patrimônio e até cinco posições abertas.","Limite de posição não garante limite máximo de perda."),
        ("4. Executor simulado","Registra compras/vendas fictícias com taxa estimada de 0,10% por lado.","Não envia ordens reais nem usa credenciais."),
        ("5. Auditor","Guarda horário, ativo, ação e justificativa.","Os registros ficam na sessão e podem desaparecer ao reiniciar."),
        ("6. Gestor patrimonial","Calcula saldo, posições e P&L estimado.","Os valores dependem dos preços disponíveis.")
    ]
    for name, desc, limitation in agents:
        with st.expander(name, expanded=True):
            st.write(desc)
            st.caption("Limitação: " + limitation)
    if st.session_state.logs:
        st.subheader("Eventos recentes")
        st.dataframe(pd.DataFrame(st.session_state.logs), use_container_width=True, hide_index=True)
with tabs[2]:
    st.subheader("Carteira simulada")
    st.write(f"**Capital inicial virtual:** ${STARTING_CASH:,.2f} USDT")
    if st.session_state.positions:
        rows=[]
        for sym,pos in st.session_state.positions.items():
            px=float(live_prices.get(sym,pos["entry"]))
            market_value=pos["qty"]*px
            rows.append({"Ativo":sym,"Quantidade":pos["qty"],"Entrada (USDT)":pos["entry"],"Preço atual (USDT)":px,"Valor atual (USDT)":market_value,"P&L não realizado (USDT)":market_value-pos["entry_cost"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma posição virtual aberta.")
    st.caption("P&L não realizado é uma estimativa antes de eventuais custos de saída.")
with tabs[3]:
    st.subheader("Histórico de operações")
    if st.session_state.trades:
        st.dataframe(pd.DataFrame(st.session_state.trades), use_container_width=True, hide_index=True)
        csv = pd.DataFrame(st.session_state.trades).to_csv(index=False).encode("utf-8")
        st.download_button("Baixar histórico CSV", csv, "historico_simulado.csv", "text/csv")
    else:
        st.info("Nenhuma operação simulada registrada.")
with tabs[4]:
    st.subheader("Regras de segurança")
    st.markdown(f"""
- **Capital inicial fictício:** ${STARTING_CASH:,.2f} USDT.
- **Ativos:** até {TOP_ASSETS} pares USDT de maior volume identificados pelo scanner.
- **Sinal demonstrativo:** cruzamento EMA 9/EMA 21; filtro RSI para entrada.
- **Limite de posições:** {MAX_POSITIONS}.
- **Tamanho máximo por posição:** 20% do patrimônio virtual, respeitando o saldo disponível.
- **Taxa estimada:** {FEE_RATE*100:.2f}% por compra e por venda; substitua por custos reais em qualquer avaliação séria.
- **Sem stop-loss real ou garantia de execução:** o protótipo não simula integralmente spread, slippage, liquidez e latência.
- **Nenhuma ordem real:** não existe código de envio de ordens nem campo para chaves privadas.
""")
    st.error("Não use os resultados desta versão como evidência de rentabilidade. A estratégia não foi validada nem otimizada para negociação real.")

st.divider()
st.caption("AI Trading Terminal v1.0 • apenas simulação • dados de mercado sujeitos a disponibilidade da API.")
