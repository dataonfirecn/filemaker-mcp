from app.services.service_directory import api_service_directory


def test_api_service_directory_lists_filemaker_integration_directions() -> None:
    payload = api_service_directory()

    services = payload["services"]
    assert len(services) == 8
    assert all(service["direction"] for service in services)
    assert all(service["authentication"] for service in services)

    endpoints = {
        endpoint["path"]
        for service in services
        for endpoint in service["endpoints"]
    }
    assert "/api/webviewer/session" in endpoints
    assert "/api/material-ids/filemaker-generate" in endpoints
    assert "/api/mes/callback" in endpoints
