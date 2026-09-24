"""Chat interface for the AI assistant."""

import uuid

import streamlit as st

st.set_page_config(page_title="Assistant", layout="wide")

if st.session_state.get("token") is None:
    st.warning("Please sign in first.")
    st.stop()

tenant_id = st.session_state.get("tenant_id")
if tenant_id is None:
    st.error("No tenant found for this session. Please sign out and sign in again.")
    st.stop()

st.title("Assistant")
st.write(
    "Ask about forecasts, reorder status, or purchasing recommendations. "
    "This assistant can look things up but cannot approve, reject, or "
    "edit any order on your behalf."
)

if st.session_state.get("assistant_tenant_id") != tenant_id:
    import sys
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from app.services.assistant import Assistant

    st.session_state.assistant = Assistant(uuid.UUID(tenant_id))
    st.session_state.assistant_tenant_id = tenant_id
    st.session_state.chat_history = []

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for role, message in st.session_state.chat_history:
    with st.chat_message(role):
        st.write(message)

question = st.chat_input("Ask a question")
if question:
    st.session_state.chat_history.append(("user", question))
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                answer = st.session_state.assistant.ask(question)
            except Exception as exc:
                answer = f"Something went wrong: {exc}"
        st.write(answer)

    st.session_state.chat_history.append(("assistant", answer))
