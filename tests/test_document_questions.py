import pytest
from test_api import client, FakeOllama
from test_datasets import add
from backend.search_constraints import is_document_question


@pytest.mark.parametrize('query', ['What education does Alice have?', 'Where did Alice work?',
                                  'Explain the leave approval procedure', 'Summarize the uploaded documents',
                                  'Compare their career history', 'Candidate contact details',
                                  'i have to select one from digital marketing dataset suggest me one'])
def test_question_intent(query):
    assert is_document_question(query)


@pytest.mark.parametrize('query', ['Python and React', 'AI engineers with 4 stars',
                                  'Find developers without Angular', 'Top 5 Python developers'])
def test_filters_keep_strict_pipeline(query):
    assert not is_document_question(query)


@pytest.mark.parametrize('endpoint', ['ask', 'search'])
def test_general_question_uses_evidence_not_skill_constraints(client, endpoint):
    api, store = client
    selected = add(api, 'education.txt', 'General', 'ALICE SMITH\nEducation: Bachelor of Science from Example University.')
    add(api, 'other.txt', 'Private', 'ALICE SMITH\nEducation: secret qualification from Forbidden University.')
    class AnswerModel(FakeOllama):
        def answer(self, query, sources):
            assert 'Select evidence for any one requested skill' not in query
            assert all('Forbidden' not in source['text'] for source in sources)
            return super().answer(query, sources)
    store.ollama = AnswerModel()
    body = api.post(f'/api/documents/{endpoint}', json={
        'query':'What education does Alice have?', 'dataset':'General', 'mode':'keyword'}).json()
    assert body['validation']['criteria']['intent'] == 'document_question'
    assert [source['id'] for source in body['sources']] == [selected]
    assert 'Example University' in body['answer']
    assert 'Forbidden' not in body['answer']
    assert 'Fabrication' not in body['answer']
    if endpoint == 'search':
        assert body['results'] == body['sources']


def test_unanswerable_question_is_empty(client):
    api, _ = client
    add(api, 'doc.txt', 'General', 'Annual leave eligibility and vacation rules.')
    body = api.post('/api/documents/ask', json={
        'query':'Where is Atlantis located?', 'dataset':'General', 'mode':'keyword'}).json()
    assert body['sources'] == []
    assert body['answer'] == 'No matching information was found.'


def test_question_filler_does_not_outrank_education(client):
    api, store = client
    add(api, 'profile.txt', 'General', 'ALICE SMITH\nI have many candidates and resumes.\n' +
        'Sales duties and account coordination. ' * 45 + '\nEDUCATION\nBachelor of Science from Example University.')
    class CapturingModel(FakeOllama):
        def answer(self, query, sources):
            assert any('Bachelor of Science' in source['text'] for source in sources)
            return super().answer(query, sources)
    store.ollama = CapturingModel()
    body = api.post('/api/documents/ask', json={'query':'What education do these candidates have?',
        'dataset':'General', 'mode':'keyword'}).json()
    assert 'Bachelor of Science' in body['answer']


def test_empty_model_selection_uses_only_topic_evidence(client):
    api, store = client
    add(api, 'degree.txt', 'General', 'ALICE SMITH\nEDUCATION\nBachelor of Science from Example University.')
    class EmptyModel(FakeOllama):
        def answer(self, query, sources):
            return '{"claims":[]}'
    store.ollama = EmptyModel()
    body = api.post('/api/documents/ask', json={'query':'What education does Alice have?',
        'dataset':'General', 'mode':'keyword'}).json()
    assert 'Bachelor of Science' in body['answer']
    assert all(claim['text'] in source['text'] for claim in body['claims']
               for source in body['sources'] if source['source_id'] == claim['source_id'])


@pytest.mark.parametrize('endpoint', ['search', 'ask'])
@pytest.mark.parametrize('query', ['i have to select one from digital marketing dataset suggest me one',
                                  'suggest me one', 'select one', 'recommend me one from this dataset'])
def test_conversational_selection_returns_one_named_recommendation(client, endpoint, query):
    api, store = client
    first = add(api, 'marketing.txt', 'Digital Marketing', 'ALICE SMITH\nMarketing Team Head. Led marketing strategy and execution.')
    add(api, 'sales.txt', 'Digital Marketing', 'BOB JONES\nSales prospecting and account management.')
    class NoChat(FakeOllama):
        def answer(self, query, sources):
            raise AssertionError('Selection uses the verified ranking and source evidence')
    store.ollama = NoChat()
    body = api.post(f'/api/documents/{endpoint}', json={
        'query':query,
        'dataset':'Digital Marketing'}).json()
    assert len(body['sources']) == 1
    assert body['sources'][0]['id'] == first
    assert 'Suggested candidate: ALICE SMITH' in body['answer']
    assert 'Why:' in body['answer'] and 'Marketing Team Head' in body['answer']
    assert body['validation']['criteria']['requestedCount'] == 1
    assert body['sources'][0]['match_type'] == 'question_evidence'
    assert 'All meaningful query words match' not in ' '.join(body['sources'][0]['reasons'])


@pytest.mark.parametrize('query,count', [('select one',1), ('suggest me two',2), ('choose 3',3),
                                       ('recommend me four',4)])
def test_selection_counts(query, count):
    from backend.search_constraints import parse_query
    assert parse_query(query + ' candidates').requestedCount == count


def test_selected_dataset_context_never_proves_explicit_skill(client):
    from backend.search_constraints import is_dataset_selection
    assert is_dataset_selection('suggest me one', 'Digital Marketing')
    assert not is_dataset_selection('suggest me one Python candidate', 'Digital Marketing')
    assert not is_dataset_selection('select one with 5 years experience', 'Digital Marketing')
    api, _ = client
    add(api, 'marketing.txt', 'Digital Marketing', 'ALICE SMITH\nMarketing strategy and execution.')
    body = api.post('/api/documents/search', json={'query':'suggest me one', 'dataset':'.NET'}).json()
    assert body['sources'] == []
