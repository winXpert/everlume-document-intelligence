import time

from fastapi.testclient import TestClient
from backend.main import create_app
from backend.store import Store
from backend.upload_queue import UploadQueue
from test_api import FakeOllama, client, upload


def wait_job(api, job_id, predicate=lambda job: job['finished'], timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = api.get('/api/documents/upload-jobs/' + job_id)
        assert response.status_code == 200, response.text
        job = response.json()
        if predicate(job):
            return job
        time.sleep(.03)
    raise AssertionError('Upload job did not reach the expected state: ' + str(job['counts']))


def test_local_session_is_automatic_private_and_origin_checked(tmp_path):
    store = Store(tmp_path, FakeOllama())
    with TestClient(create_app(store), base_url='http://127.0.0.1:8000', client=('127.0.0.1', 1234)) as api:
        assert api.get('/api/documents').status_code == 401
        assert api.post('/api/session').status_code == 403
        response = api.post('/api/session', headers={'X-Requested-With': 'EverlumeWorkspace'})
        assert response.status_code == 200
        assert 'token' not in response.json() and 'credential' not in response.json()
        cookie = response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie
        assert api.get('/api/documents').status_code == 200
        assert api.post('/api/documents/upload-jobs', json={'filenames': ['policy.txt']},
                        headers={'Origin': 'https://foreign.example'}).status_code == 403
        assert api.post('/api/session', headers={'X-Requested-With': 'EverlumeWorkspace', 'Origin': 'http://localhost:9999'}).status_code == 403
        assert api.post('/api/session', headers={'X-Requested-With': 'EverlumeWorkspace', 'Host': 'foreign.example'}).status_code == 403


def test_remote_clients_and_multiuser_mode_cannot_bootstrap(tmp_path):
    store = Store(tmp_path, FakeOllama())
    with TestClient(create_app(store), base_url='http://127.0.0.1:8000', client=('192.168.1.20', 1234)) as api:
        assert api.post('/api/session', headers={'X-Requested-With': 'EverlumeWorkspace'}).status_code == 403
    with TestClient(create_app(store, {'secret': 'alice'}), base_url='http://127.0.0.1:8000', client=('127.0.0.1', 1234)) as api:
        assert api.post('/api/session', headers={'X-Requested-With': 'EverlumeWorkspace'}).status_code == 403


def test_library_pagination_metadata_and_owner_scoping(client):
    api, _ = client
    first = upload(api, 'one.txt')
    upload(api, 'two.txt')
    assert api.patch('/api/documents/' + first, json={'name': 'renamed.txt', 'category': 'HR'}).status_code == 200
    assert api.patch('/api/documents/' + first, json={'name': 'renamed.pdf', 'category': 'HR'}).status_code == 422
    assert api.patch('/api/documents/' + first, json={'name': '../bad.txt', 'category': 'HR'}).status_code == 422
    page = api.get('/api/documents?page_size=1').json()
    assert len(page['documents']) == 1 and page['total'] == 2
    assert 'pages' not in page['documents'][0] and 'chunks' not in page['documents'][0]
    assert api.get('/api/documents?query=renamed&category=HR').json()['total'] == 1
    api.headers['Authorization'] = 'Bearer bob-token'
    assert api.get('/api/documents').json()['total'] == 0
    assert api.patch('/api/documents/' + first, json={'name': 'x.txt', 'category': 'HR'}).status_code == 404
    assert not api.post('/api/documents/bulk-delete', json={'ids': [first]}).json()['results'][0]['deleted']


def test_result_ratings_and_evidence_reasons(client):
    api, _ = client
    upload(api)
    result = api.post('/api/documents/search', json={'query': 'annual leave'}).json()['results'][0]
    assert 0 <= result['rating']['value'] <= 5
    assert result['rating']['out_of'] == 5
    assert result['reasons'] and any('page 1' in reason for reason in result['reasons'])
    assert any('exact phrase' in reason for reason in result['reasons'])
    assert 'probability' in result['rating']['basis']


def test_queue_permissions_failure_retry_and_cancellation(client):
    api, _ = client
    job = api.post('/api/documents/upload-jobs', json={'filenames': ['empty.txt', 'later.txt']}).json()
    first, second = job['items']
    api.headers['Authorization'] = 'Bearer bob-token'
    assert api.get('/api/documents/upload-jobs/' + job['id']).status_code == 404
    assert not api.get('/api/documents/upload-jobs').json()['jobs']
    assert api.post(f"/api/documents/upload-jobs/{job['id']}/items/{first['id']}", files={'file': ('empty.txt', b'text')}).status_code == 404
    assert api.post(f"/api/documents/upload-jobs/{job['id']}/cancel").status_code == 404
    api.headers['Authorization'] = 'Bearer alice-token'
    endpoint = f"/api/documents/upload-jobs/{job['id']}/items/{first['id']}"
    assert api.post(endpoint, files={'file': ('wrong.txt', b'text')}).status_code == 422
    assert api.post(endpoint, files={'file': ('empty.txt', b'')}).status_code == 202
    wait_job(api, job['id'], lambda j: j['counts']['failed'] == 1)
    assert api.post(endpoint, files={'file': ('empty.txt', b'Annual leave eligibility is twenty days.')}).status_code == 202
    wait_job(api, job['id'], lambda j: j['counts']['indexed'] == 1)
    cancelled = api.post(f"/api/documents/upload-jobs/{job['id']}/cancel").json()
    assert cancelled['counts']['cancelled'] == 1 and cancelled['counts']['indexed'] == 1
    assert cancelled['finished']


def test_two_hundred_file_queue_and_bulk_management(client):
    api, _ = client
    names = [f'policy-{i:03}.txt' for i in range(200)]
    response = api.post('/api/documents/upload-jobs', json={'filenames': names, 'category': 'Batch test'})
    assert response.status_code == 201
    job = response.json()
    assert job['total'] == 200
    assert api.post('/api/documents/upload-jobs', json={'filenames': names + ['extra.txt']}).status_code == 422
    for item in job['items']:
        response = api.post(f"/api/documents/upload-jobs/{job['id']}/items/{item['id']}", files={'file': (item['name'], b'Annual leave policy provides twenty days.')})
        assert response.status_code == 202, response.text
    completed = wait_job(api, job['id'])
    assert completed['counts']['indexed'] == 200 and completed['counts']['failed'] == 0
    page = api.get('/api/documents?page=4&page_size=50&category=Batch%20test').json()
    assert page['total'] == 200 and len(page['documents']) == 50
    ids = [item['id'] for item in job['items']]
    response = api.post('/api/documents/bulk-delete', json={'ids': ids})
    assert len(response.json()['results']) == 200
    assert all(item['deleted'] for item in response.json()['results'])
    assert api.get('/api/documents').json()['total'] == 0


def test_queue_restart_recovery_is_idempotent(tmp_path):
    store = Store(tmp_path, FakeOllama())
    queue = UploadQueue(store)
    job = queue.create('alice', ['policy.txt'], 'HR')
    item = job['items'][0]
    queue.receive('alice', job['id'], item['id'], lambda path, name: path.write_text('Annual leave policy text.'))
    queue.db.execute("UPDATE items SET state='indexing' WHERE id=?", (item['id'],))
    queue.db.commit()
    recovered = UploadQueue(store)
    assert recovered.process_next()
    assert recovered.get('alice', job['id'])['counts']['indexed'] == 1
    # Simulate a restart after metadata commit but before queue state commit.
    recovered.db.execute("UPDATE items SET state='indexing' WHERE id=?", (item['id'],))
    recovered.db.commit()
    again = UploadQueue(store)
    assert again.process_next()
    assert len(store.rows('alice')) == 1
    assert store.get('alice', item['id'])['name'] == 'policy.txt'


def test_failed_indexing_retries_from_durable_received_file(client, monkeypatch):
    import httpx
    api, store = client
    original = store.ollama.embed
    def offline(texts):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(store.ollama, 'embed', offline)
    job = api.post('/api/documents/upload-jobs', json={'filenames': ['leave.txt']}).json()
    item = job['items'][0]
    endpoint = f"/api/documents/upload-jobs/{job['id']}/items/{item['id']}"
    assert api.post(endpoint, files={'file': ('leave.txt', b'Annual leave policy provides twenty days.')}).status_code == 202
    failed = wait_job(api, job['id'])
    assert failed['counts']['failed'] == 1 and failed['items'][0]['can_retry']
    assert (store.root / 'upload-queue' / (item['id'] + '.ready')).exists()
    monkeypatch.setattr(store.ollama, 'embed', original)
    assert api.post(endpoint + '/retry').status_code == 202
    ready = wait_job(api, job['id'])
    assert ready['counts']['indexed'] == 1
    assert api.get('/api/documents/' + item['id']).status_code == 200
    assert not (store.root / 'upload-queue' / (item['id'] + '.ready')).exists()
