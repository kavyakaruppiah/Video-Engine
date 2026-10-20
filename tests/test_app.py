from fastapi.testclient import TestClient
from backend.app import app

client = TestClient(app)

def test_health():
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'

def test_prompt_validation_and_supported_plan():
    assert client.post('/api/plan', json={'prompt': ''}).status_code == 422
    response = client.post('/api/plan', json={'prompt': 'make it vertical and add text "Launch day"'})
    assert response.status_code == 200
    assert any(item['type'] == 'crop_resize' for item in response.json()['operations'])

def test_create_project():
    response = client.post('/api/projects', json={'name': 'Test project'})
    assert response.status_code == 200
    assert response.json()['name'] == 'Test project'
