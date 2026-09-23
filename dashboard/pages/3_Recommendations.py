"""Pending order recommendations: generate, approve, edit, reject."""

import streamlit as st
from api_client import (
    approve_recommendation,
    edit_recommendation,
    generate_recommendations,
    get_pending_recommendations,
    reject_recommendation,
)

st.set_page_config(page_title="Recommendations", layout="wide")

if st.session_state.get("token") is None:
    st.warning("Please sign in first.")
    st.stop()

st.title("Recommendations")

st.subheader("Generate new recommendations")
budget = st.number_input("Purchasing budget", min_value=0.0, value=1000.0, step=100.0)
if st.button("Generate"):
    try:
        created = generate_recommendations(budget)
        st.success(f"Generated {len(created)} recommendations.")
        st.rerun()
    except Exception as exc:
        st.error(f"Could not generate recommendations: {exc}")

st.divider()

st.subheader("Pending")
try:
    pending = get_pending_recommendations()
except Exception as exc:
    st.error(f"Could not load recommendations: {exc}")
    st.stop()

if not pending:
    st.write("No pending recommendations.")
else:
    for rec in pending:
        with st.container(border=True):
            cols = st.columns([2, 1, 1, 1, 1])
            cols[0].write(f"Product: {rec.get('sku') or rec['product_id']}")
            cols[1].write(f"Qty: {rec['suggested_quantity']}")
            cols[2].write(f"Cost: {rec['suggested_cost']}")

            if cols[3].button("Approve", key=f"approve_{rec['id']}"):
                try:
                    approve_recommendation(rec["id"])
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            if cols[4].button("Reject", key=f"reject_{rec['id']}"):
                try:
                    reject_recommendation(rec["id"])
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            new_qty = st.number_input(
                "Edit quantity",
                min_value=0,
                value=rec["suggested_quantity"],
                key=f"edit_qty_{rec['id']}",
            )
            if st.button("Save edit", key=f"edit_{rec['id']}"):
                try:
                    edit_recommendation(rec["id"], int(new_qty))
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
