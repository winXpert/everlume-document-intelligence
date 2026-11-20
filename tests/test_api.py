import json
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.store import Store


class FakeOllama:
    def embed(self, texts):
        # Deterministic semantic concept fixture; no model download in unit tests.
        return [[1., 0., 0.] if any(w in t.lower() for w in ['leave', 'holiday', 'vacation'])
                 else [0., 1., 0.] for t in texts]

    def answer(self, query, sources):
        return json.dumps({'claims': [
            {'text': 'Invented paraphrase', 'source_id': 'S1', 'quote': sources[0]['text']},
            {'text': 'Fabrication', 'source_id': 'S1', 'quote': 'Unverified made up evidence'},
            {'text': 'Wrong source', 'source_id': 'S999', 'quote': sources[0]['text']},
        ]})


@pytest.fixture
def client(tmp_path):
    store = Store(tmp_path, FakeOllama())
    with TestClient(create_app(store=store, tokens={'alice-token': 'alice', 'bob-token': 'bob'})) as test_client:
        test_client.headers['Authorization'] = 'Bearer alice-token'
        yield test_client, store


def upload(client, name='policy.txt', content=b'Annual leave eligibility: employees receive twenty days of paid vacation.'):
    result = client.post('/api/documents/upload', files={'file': (name, content)})
    assert result.status_code == 201, result.text
    return result.json()['id']


@pytest.mark.parametrize('query', ['eligibility', 'annual leave', 'twenty days'])
def test_keyword_words_and_phrase(client, query):
    api, _ = client
    doc_id = upload(api)
    result = api.post('/api/documents/search', json={'query': query, 'mode': 'keyword'}).json()
    assert result['results'][0]['id'] == doc_id
    assert result['results'][0]['page'] == 1


def test_semantic_and_hybrid(client):
    api, _ = client
    doc_id = upload(api)
    upload(api, 'invoices.txt', b'Quarterly invoices and accounts payable totals.')
    for mode in ['semantic', 'hybrid']:
        results = api.post('/api/documents/search', json={'query': 'holiday', 'mode': mode}).json()['results']
        assert results[0]['id'] == doc_id
    assert api.get('/api/documents/recommendations?query=holiday').json()['results'][0]['id'] == doc_id


def test_permissions_all_routes(client):
    api, _ = client
    doc_id = upload(api)
    api.headers['Authorization'] = 'Bearer bob-token'
    for path in [f'/api/documents/{doc_id}', f'/api/documents/{doc_id}/file']:
        assert api.get(path).status_code == 404
    assert api.delete(f'/api/documents/{doc_id}').status_code == 404
    assert not api.post('/api/documents/search', json={'query': 'leave'}).json()['results']
    assert not api.post('/api/documents/ask', json={'query': 'leave'}).json()['sources']
    assert not api.get('/api/documents/suggestions?query=policy').json()['suggestions']
    assert not api.get('/api/documents/recommendations?query=leave').json()['results']
    api.headers.clear()
    assert api.post('/api/documents/search', json={'query': 'leave'}).status_code == 401


def test_grounding_and_empty(client):
    api, _ = client
    upload(api)
    result = api.post('/api/documents/ask', json={'query': 'leave'}).json()
    assert len(result['claims']) == 1
    assert 'Invented' not in result['answer'] and 'Fabrication' not in result['answer']
    assert result['claims'][0]['text'] in result['sources'][0]['text']
    result = api.post('/api/documents/ask', json={'query': 'astronomy', 'mode': 'keyword'}).json()
    assert result['answer'] == 'No matching information was found.'


def test_update_delete_reconcile(client):
    api, store = client
    doc_id = upload(api)
    path = store.files / doc_id
    path.write_text('Updated holiday allowance is thirty days.')
    # Changed data must fail closed even before watcher runs.
    assert not api.post('/api/documents/search', json={'query': 'twenty', 'mode': 'keyword'}).json()['results']
    assert not store.reconcile()
    assert api.post('/api/documents/search', json={'query': 'thirty', 'mode': 'keyword'}).json()['results']
    assert not api.post('/api/documents/search', json={'query': 'twenty', 'mode': 'keyword'}).json()['results']
    assert api.delete(f'/api/documents/{doc_id}').status_code == 200
    assert not api.post('/api/documents/search', json={'query': 'holiday'}).json()['results']
    assert not store.vector.get(where={'doc_id': doc_id})['ids']


def test_deleted_source_and_restart(client):
    api, store = client
    doc_id = upload(api)
    (store.files / doc_id).unlink()
    store.reconcile()
    assert api.get(f'/api/documents/{doc_id}').status_code == 404


def test_replace_and_failure_rollback(client):
    api, store = client
    doc_id = upload(api)
    result = api.put(f'/api/documents/{doc_id}', files={'file': ('new.txt', b'Annual leave now includes thirty paid days.')})
    assert result.status_code == 200
    assert api.get(f'/api/documents/{doc_id}').json()['name'] == 'new.txt'
    assert not api.post('/api/documents/search', json={'query': 'twenty', 'mode': 'keyword'}).json()['results']
    assert api.put(f'/api/documents/{doc_id}', files={'file': ('bad.txt', b'')}).status_code == 422
    assert 'thirty' in api.get(f'/api/documents/{doc_id}').json()['pages'][0]
    api.headers['Authorization'] = 'Bearer bob-token'
    assert api.put(f'/api/documents/{doc_id}', files={'file': ('new.txt', b'changed')}).status_code == 404


@pytest.mark.parametrize('body', [{'query': ''}, {'query': '   '}, {'query': 'x', 'mode': 'invalid'}, {'query': 'x', 'limit': 99}])
def test_validation(client, body):
    assert client[0].post('/api/documents/search', json=body).status_code == 422


def test_upload_invalid(client):
    api, _ = client
    assert api.post('/api/documents/upload', files={'file': ('app.exe', b'bad')}).status_code == 415
    assert api.post('/api/documents/upload', files={'file': ('empty.txt', b'')}).status_code == 422
    assert api.post('/api/documents/upload', files={'file': ('bad.txt', b'\xff')}).status_code == 422


def test_multiple_upload_partial_failure_and_permissions(client):
    api, _ = client
    response = api.post('/api/documents/upload/batch', files=[
        ('files', ('leave.txt', b'Annual leave policy provides twenty paid days.')),
        ('files', ('benefits.csv', b'benefit,days\nvacation,20')),
        ('files', ('invalid.exe', b'unsupported')),
        ('files', ('empty.txt', b'')),
    ])
    assert response.status_code == 200
    data = response.json()
    assert data['indexed'] == 2 and data['failed'] == 2
    ids = [r['id'] for r in data['results'] if r['status'] == 'indexed']
    assert all(api.get(f'/api/documents/{doc_id}').status_code == 200 for doc_id in ids)
    api.headers['Authorization'] = 'Bearer bob-token'
    assert all(api.get(f'/api/documents/{doc_id}').status_code == 404 for doc_id in ids)
    api.headers.clear()
    assert api.post('/api/documents/upload/batch', files=[('files', ('x.txt', b'text'))]).status_code == 401


def test_multiple_upload_limit(client):
    response = client[0].post('/api/documents/upload/batch', files=[('files', (f'{i}.txt', b'text')) for i in range(21)])
    assert response.status_code == 422


def test_ollama_failure_and_size_limit(client, monkeypatch):
    import httpx
    from backend import config
    api, store = client
    doc_id = upload(api)
    def unavailable(texts):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(store.ollama, 'embed', unavailable)
    assert api.post('/api/documents/search', json={'query': 'leave'}).status_code == 503
    assert api.post('/api/documents/search', json={'query': 'leave', 'mode': 'keyword'}).json()['results']
    assert api.put(f'/api/documents/{doc_id}', files={'file': ('update.txt', b'Updated leave allowance.')}).status_code == 503
    assert 'twenty' in api.get(f'/api/documents/{doc_id}').json()['pages'][0]
    monkeypatch.setattr(config, 'MAX_UPLOAD', 4)
    assert api.post('/api/documents/upload', files={'file': ('large.txt', b'too large')}).status_code == 413


def test_empty_library_needs_no_inference(client, monkeypatch):
    def unavailable(texts):
        raise AssertionError('Empty library should not invoke a model')
    api, store = client
    monkeypatch.setattr(store.ollama, 'embed', unavailable)
    assert api.post('/api/documents/search', json={'query': 'anything'}).json()['results'] == []


def test_question_stopwords_do_not_produce_false_keyword_match(client):
    api, _ = client
    upload(api)
    assert api.post('/api/documents/search', json={'query': 'What is astronomy about?', 'mode': 'keyword'}).json()['results'] == []


def test_multi_page_and_docx(client, tmp_path):
    from docx import Document
    from pypdf import PdfWriter
    from backend.extraction import chunks
    parts = chunks(['Page one', 'Second page text'])
    assert [p['page'] for p in parts] == [1, 2]
    doc = Document(); doc.add_paragraph('Annual leave approval procedure requires manager consent.')
    path = tmp_path / 'hr.docx'; doc.save(path)
    upload(client[0], 'hr.docx', path.read_bytes())
    writer = PdfWriter(); writer.add_blank_page(width=300, height=300)
    path = tmp_path / 'scan.pdf'; writer.write(path)
    assert client[0].post('/api/documents/upload', files={'file': ('scan.pdf', path.read_bytes())}).status_code == 422
