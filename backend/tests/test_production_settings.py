"""Production startup validation (Render deployment).

Every rule here fails at process start, with a message that names the
variable but never prints a value, instead of failing on the first request.
"""

import pytest
from pydantic import ValidationError

from app.config.settings import Settings

SECRETS = {
    "SECRET_KEY": "k" * 40 + "SECRETKEYVALUE",
    "DATABASE_URL": "postgresql://user:DBPASSWORDVALUE@ep-x.neon.tech/db?sslmode=require",
    "JINA_API_KEY": "jina_JINAKEYVALUE",
    "QDRANT_API_KEY": "QDRANTKEYVALUE",
    "GEMINI_API_KEY": "GEMINIKEYVALUE",
}

VALID = {
    "ENVIRONMENT": "production",
    "GOOGLE_CLIENT_ID": "123-abc.apps.googleusercontent.com",
    "QDRANT_URL": "https://abc.cloud.qdrant.io:6333",
    "DOCUMENT_STORAGE_BACKEND": "r2",
    "CORS_ORIGINS": "https://lumora.vercel.app",
    **SECRETS,
}


@pytest.fixture
def prod_env(monkeypatch):
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_a_complete_production_configuration_is_accepted(prod_env):
    settings = Settings.get_instance()
    assert settings.is_production()
    assert settings.cors_origin_list == ["https://lumora.vercel.app"]


@pytest.mark.parametrize(
    "name", ["JINA_API_KEY", "QDRANT_URL", "QDRANT_API_KEY", "GEMINI_API_KEY"]
)
@pytest.mark.parametrize("blank", ["", "   "])
def test_each_required_service_variable_is_enforced(prod_env, name, blank):
    prod_env.setenv(name, blank)
    with pytest.raises(ValueError, match=name):
        Settings.get_instance()


def test_all_missing_variables_are_reported_together(prod_env):
    for name in ("JINA_API_KEY", "QDRANT_URL", "GEMINI_API_KEY"):
        prod_env.setenv(name, "")
    with pytest.raises(ValueError) as info:
        Settings.get_instance()
    for name in ("JINA_API_KEY", "QDRANT_URL", "GEMINI_API_KEY"):
        assert name in str(info.value)


@pytest.mark.parametrize("backend", ["local", "", "LOCAL"])
def test_production_refuses_local_document_storage(prod_env, backend):
    prod_env.setenv("DOCUMENT_STORAGE_BACKEND", backend)
    with pytest.raises(ValueError, match="DOCUMENT_STORAGE_BACKEND must be 'r2'"):
        Settings.get_instance()


def test_r2_backend_name_is_case_insensitive(prod_env):
    prod_env.setenv("DOCUMENT_STORAGE_BACKEND", " R2 ")
    assert Settings.get_instance().is_production()


def test_development_does_not_require_the_production_variables(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    for name in ("JINA_API_KEY", "QDRANT_URL", "QDRANT_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOCUMENT_STORAGE_BACKEND", "local")
    assert not Settings.get_instance().is_production()


def test_production_requires_cors_origins_to_be_set_explicitly(prod_env):
    prod_env.delenv("CORS_ORIGINS")
    with pytest.raises(ValueError, match="CORS_ORIGINS must be set explicitly"):
        Settings.get_instance()


@pytest.mark.parametrize("value", ["*", "https://a.example.com,*", " , "])
def test_production_refuses_wildcard_or_empty_cors(prod_env, value):
    prod_env.setenv("CORS_ORIGINS", value)
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings.get_instance()


def test_cors_origin_trailing_slash_is_normalised(monkeypatch):
    """A pasted "https://app.example.com/" would never match the browser's Origin."""
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com/, https://b.example.com//")
    assert Settings.get_instance().cors_origin_list == [
        "https://app.example.com",
        "https://b.example.com",
    ]


@pytest.mark.parametrize(
    "broken",
    [
        {"SECRET_KEY": "short" + "SECRETKEYVALUE"},
        {"JINA_API_KEY": ""},
        {"DOCUMENT_STORAGE_BACKEND": "local"},
        {"CORS_ORIGINS": "*"},
    ],
)
def test_validation_errors_never_print_secret_values(prod_env, broken):
    """pydantic normally appends the offending input (start of the settings
    dict) to the error; that would put secrets into the host's logs."""
    for key, value in broken.items():
        prod_env.setenv(key, value)
    with pytest.raises(ValidationError) as info:
        Settings.get_instance()

    # str() is what a traceback (and so the host's log) prints.
    text = str(info.value)
    for secret in ("SECRETKEYVALUE", "DBPASSWORDVALUE", "JINAKEYVALUE", "QDRANTKEYVALUE", "GEMINIKEYVALUE"):
        assert secret not in text
    assert "input_value" not in text
