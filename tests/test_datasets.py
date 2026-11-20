import pytest
from test_api import client, FakeOllama


def add(api, name, category, text='Python developer builds production applications.'):
    response = api.post('/api/documents/upload', files={'file':(name,text.encode())}, data={'category':category})
    assert response.status_code == 201, response.text
    return response.json()['id']


@pytest.mark.parametrize('mode', ['keyword', 'semantic', 'hybrid'])
def test_dataset_restricts_every_retrieval_mode(client, mode):
    api, _ = client
    expected = add(api, 'dotnet.txt', '.NET')
    add(api, 'angular.txt', 'Angular')
    add(api, 'general.txt', 'General')
    response = api.post('/api/documents/search', json={'query':'Python', 'dataset':'.NET', 'mode':mode})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item['id'] for item in body['results']] == [expected]
    assert body['validation']['dataset'] == '.NET'


def test_answer_and_reranking_receive_only_selected_dataset(client):
    api, store = client
    class RecordingModel(FakeOllama):
        def __init__(self): self.reranked = []; self.sources = []
        def rerank(self, query, candidates): self.reranked = candidates; return {'results':[]}
        def answer(self, query, sources): self.sources = sources; return super().answer(query,sources)
    model = RecordingModel(); store.ollama = model
    expected = add(api, 'dotnet.txt', '.NET', 'Python developer builds selected applications.')
    add(api, 'other.txt', 'Angular', 'Python developer builds forbidden applications.')
    result = api.post('/api/documents/ask', json={'query':'Python', 'dataset':'.NET'}).json()
    assert [item['id'] for item in result['sources']] == [expected]
    assert model.reranked and all(item['id'] == expected for item in model.reranked)
    assert model.sources and all('forbidden' not in item['text'] for item in model.sources)
    assert 'forbidden' not in result['answer']


def test_empty_dataset_never_falls_back_and_count_is_scoped(client):
    api, _ = client
    add(api,'one.txt','.NET')
    add(api,'two.txt','Angular','Python developer builds different applications.')
    empty = api.post('/api/documents/search',json={'query':'Python','dataset':'Unknown'}).json()
    assert empty['results'] == [] and 'Other datasets were not searched' in empty['message']
    count = api.post('/api/documents/search',json={'query':'Top 2 Python','dataset':'.NET'}).json()
    assert count['results'] == [] and count['validation']['qualified_count'] == 1
    assert api.post('/api/documents/ask',json={'query':'Python','dataset':'Unknown'}).json()['sources'] == []


def test_recommendations_suggestions_datasets_and_ownership(client):
    api, _ = client
    expected = add(api,'dotnet.txt','.NET')
    add(api,'angular.txt','Angular')
    api.headers['Authorization'] = 'Bearer bob-token'
    add(api,'private.txt','.NET')
    add(api,'secret.txt','Secret domain')
    api.headers['Authorization'] = 'Bearer alice-token'
    assert api.get('/api/documents/datasets').json()['datasets'] == [
        {'name':'.NET','document_count':1},{'name':'Angular','document_count':1}]
    assert api.get('/api/documents/suggestions',params={'query':'','dataset':'.NET'}).json()['suggestions'] == ['dotnet.txt']
    response = api.get('/api/documents/recommendations',params={'query':'Python','dataset':'.NET'}).json()
    assert [item['id'] for item in response['results']] == [expected]
    api.headers.clear()
    assert api.get('/api/documents/datasets').status_code == 401


def test_metadata_move_changes_dataset_without_reembedding(client):
    api, _ = client
    doc = add(api,'profile.txt','General')
    assert api.patch('/api/documents/'+doc,json={'name':'profile.txt','category':'.NET'}).status_code == 200
    assert not api.post('/api/documents/search',json={'query':'Python','dataset':'General'}).json()['results']
    assert api.post('/api/documents/search',json={'query':'Python','dataset':'.NET'}).json()['results'][0]['id'] == doc


def test_dataset_change_during_rerank_fails_closed(client, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, 'SEARCH_AI_ENRICHMENT', True)
    api, store = client
    expected = add(api,'profile.txt','.NET')
    class MovingModel(FakeOllama):
        def rerank(self, query, candidates):
            store.update_metadata('alice',expected,'profile.txt','Angular')
            return {'results':[]}
    store.ollama = MovingModel()
    assert api.post('/api/documents/search',json={'query':'Python','dataset':'.NET'}).json()['results'] == []


@pytest.mark.parametrize('dataset',['',' ', 'x'*101, ['.NET']])
def test_invalid_dataset(client, dataset):
    api, _ = client
    assert api.post('/api/documents/search',json={'query':'Python','dataset':dataset}).status_code == 422


def test_unscoped_api_remains_compatible(client):
    api, _ = client
    add(api,'one.txt','.NET','Python developer builds one application.')
    add(api,'two.txt','Angular','Python developer builds another application.')
    assert len(api.post('/api/documents/search',json={'query':'Python'}).json()['results']) == 2
