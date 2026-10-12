from fastapi.testclient import TestClient


def test_unknown_route_returns_problem_json(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"


def test_unhandled_exception_hides_internal_details(client: TestClient) -> None:
    response = client.get("/_test/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Internal Server Error"
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text
