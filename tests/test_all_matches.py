import json
from test_api import client, upload, FakeOllama


def test_all_matches_and_explicit_limits(client):
    api, store = client
    expected = {upload(api, f'policy-{i}.txt',
                       f'Leave policy for department {i}: unique entitlement {i * 17} days.'.encode())
                for i in range(25)}
    response = api.post('/api/documents/search', json={'query': 'leave', 'mode': 'hybrid'}).json()
    assert {item['id'] for item in response['results']} == expected
    assert response['validation']['qualified_count'] == 25
    limited = api.post('/api/documents/search', json={'query': 'leave', 'limit': 7}).json()
    assert len(limited['results']) == 7
    assert len(api.post('/api/documents/search', json={'query': 'Top 5 leave documents'}).json()['results']) == 5


def test_fast_search_skips_advisory_chat_calls(client):
    api, store = client
    class SlowChatModel(FakeOllama):
        chat_calls = 0
        def interpret(self, query):
            self.chat_calls += 1
            raise AssertionError('Ordinary search must not wait for chat interpretation')
        def rerank(self, query, candidates):
            self.chat_calls += 1
            raise AssertionError('Ordinary search must not wait for chat reranking')
    model = SlowChatModel()
    store.ollama = model
    doc = upload(api, 'policy.txt', b'Leave policy provides annual holiday entitlement.')
    for mode in ('keyword', 'hybrid', 'semantic'):
        response = api.post('/api/documents/search', json={'query':'leave', 'mode':mode}).json()
        assert [item['id'] for item in response['results']] == [doc]
        assert 'language_interpretation' not in response['validation']
        assert 'reranking' not in response['validation']
    assert model.chat_calls == 0


def test_query_cache_does_not_cache_document_results(client):
    api, store = client
    class CountingModel(FakeOllama):
        calls = 0
        def embed(self, texts):
            self.calls += 1
            return super().embed(texts)
    model = CountingModel()
    store.ollama = model
    first = upload(api, 'first.txt', b'Leave policy department alpha entitlement 24 days.')
    payload = {'query': 'leave', 'mode': 'hybrid'}
    api.post('/api/documents/search', json=payload)
    calls = model.calls
    api.post('/api/documents/search', json=payload)
    assert model.calls == calls
    second = upload(api, 'second.txt', b'Leave policy department beta entitlement 47 days.')
    assert {r['id'] for r in api.post('/api/documents/search', json=payload).json()['results']} == {first, second}
    api.delete(f'/api/documents/{first}')
    assert [r['id'] for r in api.post('/api/documents/search', json=payload).json()['results']] == [second]


def test_semantic_scan_is_batched_without_3000_chunk_cutoff(client):
    api, store = client
    upload(api, 'policy.txt', b'Leave policy explains holiday entitlement and approval.')
    original = store.vector
    row = store.rows('alice')[0]
    part = json.loads(row['chunks'])[0]
    parts = [{**part, 'vector_id': f'padding-{i}'} for i in range(3072)] + [part]
    store.db.execute('UPDATE documents SET chunks=? WHERE id=?', (json.dumps(parts), row['id']))
    store.db.commit()
    calls = []
    class PagedVectors:
        def get(self, **kwargs):
            calls.append(kwargs)
            if kwargs['offset'] < 3072:
                start = kwargs['offset']
                return {'ids': [f'padding-{i}' for i in range(start, start + 512)],
                        'embeddings': [[0., 1., 0.]] * 512}
            return original.get(where=kwargs['where'], include=['embeddings'])
    store.vector = PagedVectors()
    result = store.search('alice', 'leave', 'semantic')
    assert len(result) == 1
    assert calls and all(call['limit'] == 512 for call in calls)
    assert calls[-1]['offset'] == 3072
