import pytest
from test_api import client
from test_datasets import add


@pytest.mark.parametrize('endpoint', ['search', 'ask'])
@pytest.mark.parametrize('query', ['how many resume are present in digital marketing dataset',
                                  'How many resumes are in this dataset?',
                                  'Count documents', 'Total number of files in Digital Marketing'])
def test_library_count_without_model(client, endpoint, query):
    api, store = client
    add(api, 'one.txt', 'Digital Marketing', 'Business development and outbound sales.')
    add(api, 'two.txt', 'Digital Marketing', 'Sales prospecting and account management.')
    add(api, 'other.txt', 'General', 'General document.')
    class NoInference:
        def __getattr__(self, name):
            raise AssertionError('Metadata counts must not call Ollama')
    store.ollama = NoInference()
    body = api.post(f'/api/documents/{endpoint}', json={'query':query, 'dataset':'Digital Marketing'}).json()
    assert body['intent'] == 'dataset_count'
    assert body['count'] == 2 and body['dataset'] == 'Digital Marketing'
    assert '2 indexed documents' in body['answer']
    assert body['results'] == [] and body['sources'] == []
    api.headers['Authorization'] = 'Bearer bob-token'
    body = api.post(f'/api/documents/{endpoint}', json={'query':query, 'dataset':'Digital Marketing'}).json()
    assert body['count'] == 0


def test_named_dataset_and_empty_counts(client):
    api, _ = client
    add(api, 'one.txt', 'Digital Marketing')
    for name, expected in [('Digital Marketing', 1), ('.NET', 0)]:
        body = api.post('/api/documents/ask', json={
            'query':f'How many resumes are in {name} dataset?', 'dataset':'General'}).json()
        assert body['count'] == expected
        assert body['dataset'].casefold() == name.casefold()
    # A skill-specific count must still go through document evidence validation.
    body = api.post('/api/documents/search', json={
        'query':'How many Python resumes are in Digital Marketing dataset?', 'dataset':'Digital Marketing', 'mode':'keyword'}).json()
    assert body.get('intent') != 'dataset_count'


@pytest.mark.parametrize('endpoint', ['search', 'ask'])
@pytest.mark.parametrize('query', ['cane we hire both candidate what you say', 'Can we hire both candidates?'])
def test_hiring_question_requests_criteria(client, endpoint, query):
    api, _ = client
    add(api, 'first.txt', 'Digital Marketing', 'ALICE SMITH\nMarketing leadership.')
    add(api, 'second.txt', 'Digital Marketing', 'BOB JONES\nSales prospecting.')
    add(api, 'outside.txt', 'Other', 'OUTSIDE PERSON\nOther skills.')
    body = api.post(f'/api/documents/{endpoint}', json={'query':query, 'dataset':'Digital Marketing'}).json()
    assert body['intent'] == 'hiring_review'
    assert 'ALICE SMITH' in body['answer'] and 'BOB JONES' in body['answer']
    assert 'What role are you hiring for' in body['answer']
    assert 'OUTSIDE PERSON' not in body['answer']
    assert len(body['sources']) == 2
    assert all(source['metadata_only'] for source in body['sources'])


@pytest.mark.parametrize('endpoint', ['search', 'ask'])
@pytest.mark.parametrize('query', ['Digital marketing candidate name', 'List candidate names in this dataset'])
def test_dataset_candidate_names_with_sources(client, endpoint, query):
    api, store = client
    first = add(api, 'first.txt', 'Digital Marketing', 'ALICE SMITH\nBusiness development and sales.')
    second = add(api, 'second.txt', 'Digital Marketing', 'BOB JONES\nOutbound prospecting.')
    add(api, 'unverified.txt', 'Digital Marketing', 'PROFESSIONAL SUMMARY\nSales experience.')
    add(api, 'private.txt', 'General', 'OTHER PERSON\nOther category.')
    body = api.post(f'/api/documents/{endpoint}', json={'query':query, 'dataset':'Digital Marketing'}).json()
    assert body['intent'] == 'dataset_names'
    assert 'ALICE SMITH' in body['answer'] and 'BOB JONES' in body['answer']
    assert 'OTHER PERSON' not in body['answer']
    assert 'Candidate name could not be verified' in body['answer']
    assert {first, second} <= {item['id'] for item in body['sources']}
    assert all(item['page'] == 1 and item['metadata_only'] for item in body['sources'])
    api.headers['Authorization'] = 'Bearer bob-token'
    assert api.post(f'/api/documents/{endpoint}', json={'query':query, 'dataset':'Digital Marketing'}).json()['count'] == 0
