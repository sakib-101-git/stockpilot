# loadtest/locustfile.py
"""Load test against the real Stockpilot API.

Run: uv run locust -f loadtest/locustfile.py --host http://localhost:8000
Then open http://localhost:8089 to configure users/spawn rate and start.
"""

from locust import HttpUser, between, task


class ShopOwner(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        response = self.client.post(
            "/auth/login",
            data={"username": "owner@example.com", "password": "correct-horse-9"},
        )
        token = response.json()["access_token"]
        self.client.headers.update({"Authorization": f"Bearer {token}"})

    @task(5)
    def view_forecast_summary(self):
        self.client.get("/forecasts/summary", name="/forecasts/summary")

    @task(4)
    def view_pending_recommendations(self):
        self.client.get("/recommendations/pending", name="/recommendations/pending")

    @task(1)
    def run_budget_optimization(self):
        self.client.get("/optimize-budget?budget=3000", name="/optimize-budget")
