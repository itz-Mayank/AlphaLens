"""Tests for `app.core.config.validate_production_config` — Phase 10's
"production must fail safely when required secrets/configuration are
missing" rule. Constructs `Settings` directly (never touches the process
env or `.env.test`) so these tests are independent of whatever this
process's actual environment happens to be.
"""

import pytest
from app.core.config import InsecureProductionConfigError, Settings, validate_production_config


def _settings(**overrides) -> Settings:
    defaults = dict(
        environment="production",
        jwt_secret="a-real-long-random-production-secret-not-the-default",
        database_url="postgresql+psycopg://alphalens:a-real-password@prod-db:5432/alphalens",
        cookie_secure=True,
        cors_origins="https://app.alphalens.example.com",
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestNonProductionEnvironmentsAreNeverValidated:
    @pytest.mark.parametrize("environment", ["development", "test", "research"])
    def test_an_insecure_config_is_allowed_outside_production(self, environment):
        settings = _settings(
            environment=environment,
            jwt_secret="insecure-dev-secret-change-me",
            cookie_secure=False,
        )
        validate_production_config(settings)  # must not raise


class TestProductionRejectsInsecureConfig:
    def test_the_default_jwt_secret_is_rejected(self):
        settings = _settings(jwt_secret="insecure-dev-secret-change-me")
        with pytest.raises(InsecureProductionConfigError, match="JWT_SECRET"):
            validate_production_config(settings)

    def test_the_default_database_password_is_rejected(self):
        settings = _settings(
            database_url="postgresql+psycopg://alphalens:changeme_local_dev_only@prod-db:5432/alphalens"
        )
        with pytest.raises(InsecureProductionConfigError, match="DATABASE_URL"):
            validate_production_config(settings)

    def test_insecure_cookies_are_rejected(self):
        settings = _settings(cookie_secure=False)
        with pytest.raises(InsecureProductionConfigError, match="COOKIE_SECURE"):
            validate_production_config(settings)

    def test_a_localhost_cors_origin_is_rejected(self):
        settings = _settings(cors_origins="http://localhost:5173")
        with pytest.raises(InsecureProductionConfigError, match="CORS_ORIGINS"):
            validate_production_config(settings)

    def test_a_wildcard_cors_origin_is_rejected(self):
        settings = _settings(cors_origins="*")
        with pytest.raises(InsecureProductionConfigError, match="CORS_ORIGINS"):
            validate_production_config(settings)

    def test_multiple_problems_are_all_reported_together(self):
        settings = _settings(jwt_secret="insecure-dev-secret-change-me", cookie_secure=False)
        with pytest.raises(InsecureProductionConfigError) as exc_info:
            validate_production_config(settings)
        assert "JWT_SECRET" in str(exc_info.value)
        assert "COOKIE_SECURE" in str(exc_info.value)


class TestProductionAcceptsSecureConfig:
    def test_a_fully_secure_production_config_passes(self):
        validate_production_config(_settings())  # must not raise

    def test_demo_mode_true_in_production_is_explicitly_allowed(self):
        """A publicly-hosted demo showcasing the architecture with
        synthetic, clearly-labeled data is a valid production deployment
        shape for this project — never forced to DEMO_MODE=false."""
        validate_production_config(_settings(demo_mode=True))  # must not raise
