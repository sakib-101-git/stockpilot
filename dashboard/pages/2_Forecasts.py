"""Per-product forecast chart with SHAP explanation."""

import pandas as pd
import streamlit as st
from api_client import explain_forecast, get_forecast_summary, get_product_forecast

st.set_page_config(page_title="Forecasts", layout="wide")

if st.session_state.get("token") is None:
    st.warning("Please sign in first.")
    st.stop()

st.title("Forecasts")

try:
    summary = get_forecast_summary()
except Exception as exc:
    st.error(f"Could not load products: {exc}")
    st.stop()

if not summary:
    st.write("No forecasts available yet.")
    st.stop()

options = {row["sku"]: row["product_id"] for row in summary}
selected_sku = st.selectbox("Product", options=list(options.keys()))
product_id = options[selected_sku]

try:
    forecast_rows = get_product_forecast(product_id)
except Exception as exc:
    st.error(f"Could not load forecast: {exc}")
    st.stop()

if not forecast_rows:
    st.write("No forecast available for this product yet.")
    st.stop()

df = pd.DataFrame(forecast_rows)
df["target_date"] = pd.to_datetime(df["target_date"])
chart_df = df.set_index("target_date")[["point_estimate", "upper_bound"]]

st.subheader(f"28-day forecast: {selected_sku}")
st.line_chart(chart_df)

st.divider()

st.subheader("Why this forecast")
target_dates = df["target_date"].dt.strftime("%Y-%m-%d").tolist()
selected_date = st.selectbox("Explain the forecast for", options=target_dates)

if st.button("Explain"):
    try:
        explanation = explain_forecast(product_id, selected_date)
        st.dataframe(pd.DataFrame(explanation), use_container_width=True)
    except Exception as exc:
        st.error(f"Could not load explanation: {exc}")
