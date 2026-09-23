"""Landing page after login: quick orientation on what needs attention."""

import streamlit as st
from api_client import get_forecast_summary, get_pending_recommendations

st.set_page_config(page_title="Overview", layout="wide")

if st.session_state.get("token") is None:
    st.warning("Please sign in first.")
    st.stop()

st.title("Overview")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Pending recommendations")
    try:
        pending = get_pending_recommendations()
        st.metric("Awaiting your decision", len(pending))
    except Exception as exc:
        st.error(f"Could not load recommendations: {exc}")

with col2:
    st.subheader("Products with a forecast")
    try:
        summary = get_forecast_summary()
        st.metric("Tracked products", len(summary))
    except Exception as exc:
        st.error(f"Could not load forecast summary: {exc}")

st.divider()

st.subheader("Recent forecast summary")
try:
    summary = get_forecast_summary()
    if summary:
        st.dataframe(summary, use_container_width=True)
    else:
        st.write("No forecasts available yet.")
except Exception as exc:
    st.error(f"Could not load forecast summary: {exc}")
