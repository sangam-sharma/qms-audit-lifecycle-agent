import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.graph import AuditOrchestrator
from app.domain.schemas import OrientationStatus
from app.main import create_app
from app.providers.base import (
    AuditNotFound, ProviderEndpointNotAllowed, ProviderForbidden,
    ProviderNotFound, ProviderTimeout, ProviderUnauthorized,
)
from app.providers.django_api import DjangoAPIProvider


TOKEN = "test-only-jwt-value"
BASE = "http://qms.test/api/"


def audit_row(code="IA-2026-037"):
    return {
        "id": 37, "audit_code": code, "project": 8,
        "project_name": "Northwind ERP Validation", "department": 3,
        "framework": 2, "framework_name": "ISO 9001:2015",
        "planned_start_date": "2026-11-10", "planned_end_date": "2026-11-12",
        "status": "IN_PROGRESS", "created_at": "2026-10-01T10:30:00Z",
        "progress": {"checklist": {"id": 90, "name": "ERP Controls", "item_count": 4,
                                    "compliant": 2, "non_compliant": 1, "pending": 1}},
    }


def api_handler(calls, *, status_for=None, raise_timeout=False):
    def handle(request: httpx.Request):
        calls.append(request)
        assert request.method == "GET"
        if raise_timeout:
            raise httpx.ReadTimeout("unit-test timeout", request=request)
        path = request.url.path.removeprefix("/api/")
        status = (status_for or {}).get(path)
        if status:
            return httpx.Response(status, json={"detail": "private server response"}, request=request)
        if path == "auth/me/":
            return httpx.Response(200, json={"id": 12, "username": "qms-test", "role": "QMS"}, request=request)
        if path == "audits/":
            return httpx.Response(200, json=[audit_row()], request=request)
        if path == "audits/37/":
            return httpx.Response(200, json=audit_row(), request=request)
        if path == "audits/37/assignments/":
            return httpx.Response(200, json=[{
                "id": 52, "audit": 37, "auditor": 21, "auditor_name": "auditor-one",
                "assignment_type": "PRIMARY", "assigned_by": 12,
            }], request=request)
        if path == "audits/37/schedule/":
            return httpx.Response(200, json=[{
                "id": 61, "audit": 37, "audit_code": "IA-2026-037",
                "scheduled_start": "2026-11-10T09:00:00Z", "scheduled_end": "2026-11-12T17:00:00Z",
                "status": "SCHEDULED",
            }], request=request)
        if path == "audits/37/confirmations/":
            return httpx.Response(200, json=[{
                "id": 73, "schedule": 61, "audit_code": "IA-2026-037",
                "confirmation_type": "COMBINED",
            }], request=request)
        if path == "orientations/":
            return httpx.Response(200, json=[{
                "id": 55, "assignment": 52, "auditor_name": "auditor-one",
                "audit_code": "IA-2026-037", "status": "COMPLETED",
            }], request=request)
        if path == "audits/37/ncs/":
            return httpx.Response(200, json=[{
                "id": 81, "checklist_item_id": 92, "item_code": "ERP-04",
                "question": "Are access reviews recorded?", "project_name": "Northwind ERP",
                "finding": "Review evidence is missing.",
                "risk_action": "Review access quarterly until action is verified.",
                "correction": "", "corrective_action": "Add quarterly review control.",
                "preventive_action": "Notify control owners before due dates.",
                "status": "SUBMITTED", "verified_by": 9,
                "verified_by_name": "auditor-nine",
                "verified_at": "2026-10-30T12:00:00Z",
                "verification_remarks": "Evidence reviewed.",
                "created_at": "2026-10-25T12:00:00Z", "updated_at": "2026-10-30T12:00:00Z",
            }], request=request)
        return httpx.Response(404, json={"detail": "not found"}, request=request)
    return handle


def make_provider(handler=None):
    transport = httpx.MockTransport(handler or api_handler([]))
    return DjangoAPIProvider(BASE, TOKEN, transport=transport)


def test_identity_validation_and_jwt_forwarding_are_request_scoped():
    calls = []
    provider = make_provider(api_handler(calls))
    with pytest.raises(ProviderUnauthorized):
        provider.list_audits()
    identity = provider.validate_identity()
    audits = provider.list_audits()

    assert identity["role"] == "QMS"
    assert audits[0].id == "37"
    assert [request.url.path for request in calls] == ["/api/auth/me/", "/api/audits/"]
    assert all(request.headers["Authorization"] == f"Bearer {TOKEN}" for request in calls)
    assert "test-only-jwt-value" not in repr(provider)
    provider.close()


@pytest.mark.parametrize("reference", ["37", "IA-2026-037"])
def test_resolves_id_or_audit_code_through_list_then_detail(reference):
    calls = []
    provider = make_provider(api_handler(calls))
    provider.validate_identity()
    audit = provider.get_audit(reference)

    assert audit.id == "37"
    assert audit.code == "IA-2026-037"
    assert [request.url.path for request in calls][-2:] == ["/api/audits/", "/api/audits/37/"]
    provider.close()


def test_new_audit_code_reaches_django_provider_unchanged():
    code = "AUD-2026-Q2"
    calls = []
    handler = api_handler(calls)
    original = handler

    def code_handler(request):
        response = original(request)
        if request.url.path in {"/api/audits/", "/api/audits/37/"} and response.status_code == 200:
            payload = response.json()
            if isinstance(payload, list):
                payload[0]["audit_code"] = code
            else:
                payload["audit_code"] = code
            return httpx.Response(200, json=payload, request=request)
        return response

    provider = make_provider(code_handler)
    provider.validate_identity()
    seen_references = []
    original_get_audit = provider.get_audit

    def recording_get_audit(audit_id, *, context=None):
        seen_references.append(audit_id)
        return original_get_audit(audit_id, context=context)

    provider.get_audit = recording_get_audit
    result = AuditOrchestrator(provider).execute_task(f"Analyze audit {code}", include_explanation=False)

    assert seen_references[0] == code
    assert result.audit_code == code
    provider.close()


def test_all_supported_read_tools_map_responses_and_use_aggregate_checklist_only():
    calls = []
    provider = make_provider(api_handler(calls))
    provider.validate_identity()

    audit = provider.get_audit("IA-2026-037")
    progress = provider.get_checklist_progress(audit.id)
    assert provider.get_checklist(audit.id) == []
    assignments = provider.get_assignments(audit.id)
    schedule = provider.get_schedule(audit.id)
    confirmations = provider.get_confirmations(audit.id)
    ncs = provider.get_non_conformities(audit.id)

    assert progress and (progress.item_count, progress.non_compliant, progress.pending) == (4, 1, 1)
    assert assignments[0].orientation_status == OrientationStatus.COMPLETED
    assert schedule and schedule.confirmations == ["COMBINED"]
    assert confirmations == ["COMBINED"]
    assert ncs[0].corrective_action_submitted is True
    assert ncs[0].finding == "Review evidence is missing."
    assert ncs[0].question == "Are access reviews recorded?"
    assert ncs[0].project_name == "Northwind ERP"
    assert ncs[0].risk_action == "Review access quarterly until action is verified."
    assert ncs[0].correction == ""
    assert ncs[0].corrective_action == "Add quarterly review control."
    assert ncs[0].preventive_action == "Notify control owners before due dates."
    assert ncs[0].verified_by_id == "9"
    assert ncs[0].verified_by_name == "auditor-nine"
    assert ncs[0].verified_at is not None
    assert ncs[0].verification_remarks == "Evidence reviewed."
    assert ncs[0].created_at is not None and ncs[0].updated_at is not None
    assert {
        "finding", "risk_action", "correction", "corrective_action", "preventive_action",
        "verified_by", "verified_by_name", "verified_at", "verification_remarks",
    } <= ncs[0].returned_fields
    assert all(request.method == "GET" for request in calls)
    assert not any("checklist" in request.url.path for request in calls)
    assert {request.url.path for request in calls} >= {
        "/api/audits/", "/api/audits/37/", "/api/audits/37/assignments/",
        "/api/audits/37/schedule/", "/api/audits/37/confirmations/",
        "/api/orientations/", "/api/audits/37/ncs/",
    }
    provider.close()


def test_nc_mapping_distinguishes_explicit_empty_fields_from_omitted_fields():
    def sparse_handler(request):
        response = api_handler([])(request)
        if request.url.path == "/api/audits/37/ncs/":
            return httpx.Response(200, json=[{
                "id": 81, "checklist_item_id": 92, "item_code": "ERP-04",
                "status": "ACCEPTED", "finding": "", "correction": "",
            }], request=request)
        return response

    provider = make_provider(sparse_handler)
    provider.validate_identity()
    nc = provider.get_non_conformities("37")[0]

    assert nc.finding == ""
    assert nc.correction == ""
    assert nc.corrective_action is None
    assert nc.field_was_returned("finding")
    assert nc.field_was_returned("correction")
    assert not nc.field_was_returned("corrective_action")
    assert "corrective_action" not in nc.returned_fields
    provider.close()


def test_allowlist_rejects_checklist_routes_and_arbitrary_endpoints():
    calls = []
    provider = make_provider(api_handler(calls))
    for endpoint in ("audit_checklist", "audit_checklist_item", "anything"):
        with pytest.raises(ProviderEndpointNotAllowed):
            provider._get(endpoint, audit_id="37", pk="1")
    assert calls == []
    provider.close()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, ProviderUnauthorized), (403, ProviderForbidden), (404, ProviderNotFound)],
)
def test_http_authorization_and_not_found_errors_are_typed(status, expected):
    path = "auth/me/" if status == 401 else "audits/"
    provider = make_provider(api_handler([], status_for={path: status}))
    with pytest.raises(expected):
        provider.validate_identity() if status == 401 else (provider.validate_identity(), provider.list_audits())
    provider.close()


def test_audit_absent_from_authorized_list_is_not_found():
    def handle(request):
        if request.url.path.endswith("auth/me/"):
            return httpx.Response(200, json={"id": 12}, request=request)
        return httpx.Response(200, json=[], request=request)
    provider = make_provider(handle)
    provider.validate_identity()
    with pytest.raises(AuditNotFound):
        provider.get_audit("IA-UNKNOWN")
    provider.close()


def test_http_timeout_is_typed_and_does_not_retain_server_text():
    provider = make_provider(api_handler([], raise_timeout=True))
    with pytest.raises(ProviderTimeout):
        provider.validate_identity()
    provider.close()


def test_fastapi_django_mode_validates_and_forwards_incoming_bearer(monkeypatch):
    calls = []
    real_provider = DjangoAPIProvider

    class TestProvider(real_provider):
        def __init__(self, base_url, jwt, **kwargs):
            super().__init__(base_url, jwt, transport=httpx.MockTransport(api_handler(calls)))

    monkeypatch.setenv("QMS_DATA_PROVIDER", "django")
    monkeypatch.setenv("QMS_API_BASE_URL", BASE)
    monkeypatch.setattr("app.main.DjangoAPIProvider", TestProvider)
    client = TestClient(create_app(explainer=None))
    response = client.get("/api/audits", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.json()[0]["code"] == "IA-2026-037"
    assert [request.url.path for request in calls] == ["/api/auth/me/", "/api/audits/"]
    assert all(request.headers["Authorization"] == f"Bearer {TOKEN}" for request in calls)

