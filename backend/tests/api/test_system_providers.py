class TestRoleBasedAccess:
    def test_a_plain_user_cannot_view_provider_status(self, client, auth_headers):
        res = client.get("/api/v1/system/providers", headers=auth_headers)
        assert res.status_code == 403

    def test_unauthenticated_requests_are_rejected(self, client):
        res = client.get("/api/v1/system/providers")
        assert res.status_code == 401

    def test_an_analyst_can_view_provider_status(self, client, make_user_with_role):
        headers = make_user_with_role("ANALYST")
        res = client.get("/api/v1/system/providers", headers=headers)
        assert res.status_code == 200


class TestProviderStatusContent:
    def test_reports_the_four_provider_categories_with_demo_env_defaults(
        self, client, make_user_with_role
    ):
        """In test/demo env (no external credentials configured), market
        data and news are the demo providers and fundamentals/macro are
        `none` — this must never silently claim a real provider is active
        when it isn't."""
        headers = make_user_with_role("ADMIN")
        res = client.get("/api/v1/system/providers", headers=headers)
        assert res.status_code == 200
        body = res.json()
        categories = {p["category"] for p in body["providers"]}
        assert categories == {"market_data", "news", "fundamentals", "macro"}

        market_data = next(p for p in body["providers"] if p["category"] == "market_data")
        assert market_data["configured_provider"] == "demo"
        assert market_data["credential_required"] is False

    def test_never_exposes_a_credential_value(self, client, make_user_with_role):
        headers = make_user_with_role("ADMIN")
        res = client.get("/api/v1/system/providers", headers=headers)
        # Only ever a boolean "is a credential configured", never the
        # credential itself — assert the exact, closed field set per row.
        for provider in res.json()["providers"]:
            assert set(provider.keys()) == {
                "category", "configured_provider", "credential_required",
                "credential_configured", "last_success_at", "last_failure_at",
                "last_failure_reason", "last_latency_seconds",
            }
