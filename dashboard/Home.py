"""Stockpilot dashboard entry point: login, then Streamlit routes to the
pages/ directory automatically.
"""

import streamlit as st
from api_client import get_current_user, login

st.set_page_config(page_title="Stockpilot", layout="wide")

if "token" not in st.session_state:
    st.session_state.token = None
    st.session_state.tenant_id = None
    st.session_state.email = None

if st.session_state.token is None:
    st.title("Stockpilot")
    st.subheader("Sign in")

    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        result = login(email, password)
        if result is None:
            st.error("Invalid email or password.")
        else:
            st.session_state.token = result["access_token"]
            st.session_state.email = email
            user_info = get_current_user()
            st.session_state.tenant_id = user_info["tenant_id"]
            st.rerun()
else:
    st.title("Stockpilot")
    st.write(f"Signed in as {st.session_state.email}")
    st.write("Use the sidebar to navigate to Overview, Forecasts, Recommendations, or Assistant.")
    if st.button("Sign out"):
        st.session_state.token = None
        st.session_state.tenant_id = None
        st.rerun()
