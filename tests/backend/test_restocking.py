"""
Tests for restocking API endpoints (recommendations and submitted orders).
"""
import json

import pytest

import mock_data


@pytest.fixture(autouse=True)
def isolated_submitted_orders(tmp_path, monkeypatch):
    """Point persistence at a temp file and start each test with no submitted orders."""
    monkeypatch.setattr(mock_data, "SUBMITTED_ORDERS_PATH", str(tmp_path / "submitted_orders.json"))
    # Clear in place: main.py holds a reference to this same list object
    original = list(mock_data.submitted_orders)
    mock_data.submitted_orders.clear()
    yield
    mock_data.submitted_orders[:] = original


def max_budget(client):
    return client.get("/api/restocking/recommendations?budget=0").json()["max_budget"]


class TestRestockingRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_zero_budget_returns_no_items(self, client):
        """Test that a zero budget recommends nothing but still reports max_budget."""
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.status_code == 200

        data = response.json()
        assert data["items"] == []
        assert data["total_cost"] == 0
        assert data["max_budget"] > 0

    def test_recommendation_structure(self, client):
        """Test that recommendation items have the expected fields and types."""
        data = client.get(f"/api/restocking/recommendations?budget={max_budget(client)}").json()
        assert len(data["items"]) > 0

        for item in data["items"]:
            for field in ["item_sku", "item_name", "category", "trend", "shortfall",
                          "recommended_qty", "unit_cost", "line_cost", "lead_time_days"]:
                assert field in item
            assert isinstance(item["recommended_qty"], int)
            assert item["recommended_qty"] > 0
            assert item["recommended_qty"] <= item["shortfall"]
            assert item["lead_time_days"] > 0

    @pytest.mark.parametrize("fraction", [0.1, 0.25, 0.5, 0.9])
    def test_total_cost_never_exceeds_budget(self, client, fraction):
        """Test that recommended spend stays within the budget."""
        budget = round(max_budget(client) * fraction, 2)
        data = client.get(f"/api/restocking/recommendations?budget={budget}").json()

        assert data["total_cost"] <= budget
        assert abs(data["remaining"] - (budget - data["total_cost"])) < 0.01
        line_total = sum(i["line_cost"] for i in data["items"])
        assert abs(line_total - data["total_cost"]) < 0.01

    def test_max_budget_covers_every_shortfall(self, client):
        """Test that a budget equal to max_budget restocks every shortfall in full."""
        data = client.get(f"/api/restocking/recommendations?budget={max_budget(client)}").json()

        for item in data["items"]:
            assert item["recommended_qty"] == item["shortfall"]
        assert abs(data["remaining"]) < 0.01

    def test_items_ordered_by_urgency(self, client):
        """Test that fully funded items come back most urgent (largest uncovered share) first."""
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        data = client.get(f"/api/restocking/recommendations?budget={max_budget(client)}").json()

        urgencies = [
            i["shortfall"] / forecasts[i["item_sku"]]["forecasted_demand"] for i in data["items"]
        ]
        assert urgencies == sorted(urgencies, reverse=True)

    def test_items_with_no_shortfall_are_excluded(self, client):
        """Test that SKUs whose stock already covers forecast demand are not recommended."""
        forecasts = client.get("/api/demand").json()
        covered = {f["item_sku"] for f in forecasts if f["quantity_on_hand"] >= f["forecasted_demand"]}
        assert covered, "test data should include at least one fully stocked SKU"

        data = client.get(f"/api/restocking/recommendations?budget={max_budget(client)}").json()
        assert covered.isdisjoint({i["item_sku"] for i in data["items"]})

    def test_negative_budget_rejected(self, client):
        """Test that a negative budget fails validation."""
        response = client.get("/api/restocking/recommendations?budget=-5")
        assert response.status_code == 422


class TestRestockingOrders:
    """Test suite for POST and GET /api/restocking/orders."""

    def recommended_order(self, client, budget=None):
        budget = max_budget(client) if budget is None else budget
        recs = client.get(f"/api/restocking/recommendations?budget={budget}").json()
        return {
            "budget": budget,
            "items": [{"item_sku": i["item_sku"], "quantity": i["recommended_qty"]} for i in recs["items"]],
        }, recs

    def test_place_order_success(self, client):
        """Test that placing a recommended order returns 201 with lead time and delivery date."""
        payload, recs = self.recommended_order(client)
        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert abs(order["total_value"] - recs["total_cost"]) < 0.01
        assert len(order["items"]) == len(payload["items"])
        assert "T" in order["expected_delivery"]

    def test_lead_time_is_longest_item(self, client):
        """Test that the order lead time is the maximum across its items."""
        payload, recs = self.recommended_order(client)
        order = client.post("/api/restocking/orders", json=payload).json()

        assert order["lead_time_days"] == max(i["lead_time_days"] for i in recs["items"])

    def test_submitted_order_listed_newest_first(self, client):
        """Test that submitted orders appear in GET, newest first."""
        payload, _ = self.recommended_order(client)
        first = client.post("/api/restocking/orders", json=payload).json()
        second = client.post("/api/restocking/orders", json=payload).json()
        assert first["order_number"] != second["order_number"]

        data = client.get("/api/restocking/orders").json()
        assert [o["id"] for o in data] == [second["id"], first["id"]]

    def test_server_ignores_client_prices(self, client):
        """Test that unit prices come from server data even if the client sends its own."""
        payload, recs = self.recommended_order(client)
        payload["items"][0]["unit_price"] = 0.01
        order = client.post("/api/restocking/orders", json=payload).json()

        assert order["items"][0]["unit_price"] == recs["items"][0]["unit_cost"]

    def test_order_over_budget_rejected(self, client):
        """Test that an order costing more than its budget is rejected and not stored."""
        payload, _ = self.recommended_order(client)
        payload["budget"] = 1
        response = client.post("/api/restocking/orders", json=payload)

        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()
        assert client.get("/api/restocking/orders").json() == []

    def test_unknown_sku_rejected(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 1000, "items": [{"item_sku": "NOPE-000", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    @pytest.mark.parametrize("quantity", [0, -3])
    def test_non_positive_quantity_rejected(self, client, quantity):
        """Test that zero or negative quantities are rejected."""
        sku = client.get("/api/demand").json()[0]["item_sku"]
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 1000000, "items": [{"item_sku": sku, "quantity": quantity}]},
        )
        assert response.status_code == 400

    def test_empty_order_rejected(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restocking/orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

    def test_duplicate_sku_rejected(self, client):
        """Test that the same SKU twice in one order is rejected."""
        sku = client.get("/api/demand").json()[0]["item_sku"]
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 1000000, "items": [{"item_sku": sku, "quantity": 1}] * 2},
        )
        assert response.status_code == 400

    def test_order_persisted_to_file(self, client):
        """Test that a submitted order is written to the JSON file."""
        payload, _ = self.recommended_order(client)
        order = client.post("/api/restocking/orders", json=payload).json()

        with open(mock_data.SUBMITTED_ORDERS_PATH) as f:
            saved = json.load(f)
        assert [o["id"] for o in saved] == [order["id"]]

    def test_main_orders_unaffected(self, client):
        """Test that submitted orders do not leak into the main orders list."""
        before = len(client.get("/api/orders").json())
        payload, _ = self.recommended_order(client)
        client.post("/api/restocking/orders", json=payload)

        assert len(client.get("/api/orders").json()) == before
