class TestGetMacroSeries:
    def test_unauthenticated_requests_are_rejected(self, client):
        res = client.get("/api/v1/macro/FEDFUNDS")
        assert res.status_code == 401

    def test_an_unrecognized_series_is_reported_unavailable_not_404(self, client, auth_headers):
        """A macro series isn't a tracked entity the way a security is —
        never fabricate data for it, but also never 404 as if the endpoint
        itself doesn't exist."""
        res = client.get("/api/v1/macro/NOT_A_REAL_SERIES", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["available"] is False
        assert body["observations"] == []

    def test_series_id_is_normalized_to_uppercase(self, client, auth_headers):
        res = client.get("/api/v1/macro/fedfunds", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["series_id"] == "FEDFUNDS"
