"""Thin wrapper around the Stockpilot API, carrying the JWT from Streamlit's
session state. No business logic lives here — every call maps directly to
an existing, tested endpoint.
"""

import os

import requests
import streamlit as st

API_BASE = os.environ.get("STOCKPILOT_API_URL", "http://localhost:8000")


def _headers() -> dict:
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def login(email: str, password: str) -> dict | None:
    response = requests.post(
        f"{API_BASE}/auth/login", data={"username": email, "password": password}
    )
    if response.status_code != 200:
        return None
    return response.json()


def get_forecast_summary() -> list[dict]:
    response = requests.get(f"{API_BASE}/forecasts/summary", headers=_headers())
    response.raise_for_status()
    return response.json()


def get_product_forecast(product_id: str) -> list[dict]:
    response = requests.get(f"{API_BASE}/products/{product_id}/forecast", headers=_headers())
    response.raise_for_status()
    return response.json()


def explain_forecast(product_id: str, target_date: str) -> list[dict]:
    response = requests.get(
        f"{API_BASE}/products/{product_id}/forecast/{target_date}/explain",
        headers=_headers(),
    )
    response.raise_for_status()
    return response.json()


def get_pending_recommendations() -> list[dict]:
    response = requests.get(f"{API_BASE}/recommendations/pending", headers=_headers())
    response.raise_for_status()
    return response.json()


def generate_recommendations(budget: float) -> list[dict]:
    response = requests.post(
        f"{API_BASE}/recommendations/generate",
        json={"budget": budget},
        headers=_headers(),
    )
    response.raise_for_status()
    return response.json()


def approve_recommendation(rec_id: str) -> dict:
    response = requests.post(f"{API_BASE}/recommendations/{rec_id}/approve", headers=_headers())
    response.raise_for_status()
    return response.json()


def edit_recommendation(rec_id: str, new_quantity: int) -> dict:
    response = requests.post(
        f"{API_BASE}/recommendations/{rec_id}/edit",
        json={"new_quantity": new_quantity},
        headers=_headers(),
    )
    response.raise_for_status()
    return response.json()


def reject_recommendation(rec_id: str) -> dict:
    response = requests.post(f"{API_BASE}/recommendations/{rec_id}/reject", headers=_headers())
    response.raise_for_status()
    return response.json()


def get_current_user() -> dict:
    response = requests.get(f"{API_BASE}/auth/me", headers=_headers())
    response.raise_for_status()
    return response.json()
