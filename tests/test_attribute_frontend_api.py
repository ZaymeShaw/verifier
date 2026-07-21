from fastapi.testclient import TestClient

from impl.server.app import create_app


def _attribute_payload(*, findings=True, unresolved_reason=""):
    return {
        "trace_id": "trace-api-1",
        "project_id": "QA",
        "case_id": "case-api-1",
        "findings": [{
            "finding_id": "finding-router",
            "affected_expectation_ids": ["exp-route"],
            "conclusion": "路由配置将目标请求错误映射到 fallback。",
            "evidence": [{
                "ref_id": "ev-router",
                "source": "context_unit",
                "kind": "runtime_result",
                "stage": "attribute-round-1-finalization",
                "summary": "重放结果稳定进入 fallback 分支。",
                "location": "cu-router-replay",
                "metadata": {"source_hash": "sha256:api-test"},
            }],
        }] if findings else [],
        "unresolved_reason": unresolved_reason,
        "summary": {
            "summary_text": "路由配置将目标请求错误映射到 fallback。" if findings else unresolved_reason,
            "finding_count": 1 if findings else 0,
            "attribution_status": "complete" if findings else "unresolved",
            "is_formal_attribution": findings,
        },
    }


def test_frontend_view_api_preserves_summary_findings_and_evidence():
    client = TestClient(create_app())
    response = client.post("/api/frontend_view", json={"project": "QA", "attribute": _attribute_payload()})

    assert response.status_code == 200
    body = response.json()
    assert body["attribute_panel"]["display_summary"] == "路由配置将目标请求错误映射到 fallback。"
    [finding] = body["expectation_attribution_panel"]["findings"]
    assert finding["finding_id"] == "finding-router"
    assert finding["evidence"][0]["location"] == "cu-router-replay"


def test_frontend_view_api_preserves_unresolved_summary_without_finding():
    client = TestClient(create_app())
    reason = "embedding 服务两次返回非法向量，材料未能注册为 ContextUnit。"
    response = client.post("/api/frontend_view", json={
        "project": "QA",
        "attribute": _attribute_payload(findings=False, unresolved_reason=reason),
    })

    assert response.status_code == 200
    body = response.json()
    assert body["attribute_panel"]["display_summary"] == reason
    assert body.get("expectation_attribution_panel", {}).get("findings", []) == []
