from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.mock_qms import MockQMSProvider


def test_health_and_audit_listing():
    client = TestClient(create_app(provider=MockQMSProvider(), explainer=None))

    health = client.get("/api/health")
    audits = client.get("/api/audits")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "data_source": "mock"}
    assert audits.status_code == 200
    assert len(audits.json()) == 3
    assert {row["status"] for row in audits.json()} == {"PENDING_ASSIGNMENT", "ASSIGNED", "IN_PROGRESS"}


def test_analysis_endpoint_returns_facts_recommendations_and_provenance():
    client = TestClient(create_app(provider=MockQMSProvider(), explainer=None))

    response = client.post("/api/audits/audit-1003/analysis")
    result = response.json()

    assert response.status_code == 200
    assert result["audit_code"] == "IA-2026-003"
    assert result["facts"]
    assert result["recommendations"]
    assert result["unresolved_policies"]
    assert result["llm_used"] is False
    assert result["facts"][0]["source_refs"]


def test_analysis_endpoint_supports_deterministic_only_mode():
    client = TestClient(create_app(provider=MockQMSProvider(), explainer=None))

    response = client.post("/api/audits/audit-1001/analysis?include_explanation=false")

    assert response.status_code == 200
    assert response.json()["explanation_source"] == "deterministic"
    assert response.json()["llm_used"] is False


def test_missing_audit_is_a_safe_404():
    client = TestClient(create_app(provider=MockQMSProvider(), explainer=None))

    response = client.post("/api/audits/not-here/analysis")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "audit_not_found"


def test_demo_is_served_by_local_api():
    client = TestClient(create_app(provider=MockQMSProvider(), explainer=None))

    response = client.get("/")

    assert response.status_code == 200
    assert "QMS Audit Assistant" in response.text
    assert "Analyze audit" in response.text
