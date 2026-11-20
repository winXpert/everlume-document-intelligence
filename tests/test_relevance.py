"""Regression checks for whole-word retrieval and technical query relevance."""
import pytest
from test_api import client, upload, FakeOllama
from backend import config
from backend.keyword_matcher import KeywordMatcher


class TechnicalOllama(FakeOllama):
    def embed(self, texts):
        result = []
        for text in texts:
            if text.startswith(config.QUERY_PREFIX):
                result.append([1., 0., 0.])
            elif 'related candidate' in text:
                result.append([.8, .6, 0.])
            elif 'weak semantic' in text:
                result.append([.4, .9165, 0.])
            else:
                result.append([0., 1., 0.])
        return result


@pytest.mark.parametrize('query', ['AI', 'Agentic AI', 'ML Engineer', 'AI Engineer'])
def test_unrelated_substrings_are_not_keywords(client, query):
    api, _ = client
    upload(api, 'operations.txt', b'Emails, maintenance and familiar routines. HTML engineer maintains email templates.')
    results = api.post('/api/documents/search', json={'query': query, 'mode': 'keyword'}).json()['results']
    assert results == []


def test_phrase_then_complete_words(client):
    api, _ = client
    phrase = upload(api, 'exact.txt', b'An Agentic AI specialist builds production systems.')
    words = upload(api, 'words.txt', b'Agentic workflows supported by AI systems.')
    upload(api, 'generic.txt', b'AI assists email maintenance workflows.')
    results = api.post('/api/documents/search', json={'query': 'Agentic AI', 'mode': 'keyword'}).json()['results']
    assert [r['id'] for r in results] == [phrase, words]


def test_case_punctuation_and_page_preserved(client):
    api, _ = client
    doc_id = upload(api, 'profile.txt', b'Skills: (aI), ML Engineer; machine learning.')
    for query in ['AI', 'ml engineer', 'Machine Learning']:
        result = api.post('/api/documents/search', json={'query': query, 'mode': 'keyword'}).json()['results'][0]
        assert result['id'] == doc_id and result['page'] == 1
    assert api.get(f'/api/documents/{doc_id}').json()['pages'][0].startswith('Skills:')


@pytest.mark.parametrize('query,synonym', [
    ('Agentic AI', 'Autonomous agents with tool execution and agent orchestration'),
    ('ML Engineer', 'Machine Learning Engineer with model training and MLOps'),
])
def test_semantic_synonyms_and_unrelated_filtering(client, query, synonym):
    api, store = client
    store.ollama = TechnicalOllama()
    expected = upload(api, 'relevant.txt', (synonym + '. A related candidate.').encode())
    upload(api, 'operations.txt', b'Emails maintenance familiar HTML engineer. A weak semantic candidate.')
    for mode in ['semantic', 'hybrid']:
        results = api.post('/api/documents/search', json={'query': query, 'mode': mode}).json()['results']
        assert [r['id'] for r in results] == [expected]
        assert results[0]['match_type'] == 'semantic'
        assert results[0]['semantic_similarity'] == pytest.approx(.8, abs=.001)
    assert api.get('/api/documents/recommendations', params={'query': query}).json()['results'][0]['id'] == expected
    assert api.post('/api/documents/ask', json={'query': query}).json()['sources'][0]['id'] == expected


def test_hybrid_priorities_override_cosine_score(client):
    api, store = client
    store.ollama = TechnicalOllama()
    phrase = upload(api, 'exact.txt', b'Agentic AI research and implementation.')
    complete = upload(api, 'words.txt', b'Agentic workflows are supported by AI systems.')
    semantic = upload(api, 'related.txt', b'Autonomous agents with tool calling. A related candidate.')
    results = api.post('/api/documents/search', json={'query': 'Agentic AI'}).json()['results']
    assert [r['id'] for r in results] == [phrase, complete, semantic]
    assert [r['match_type'] for r in results] == ['exact_phrase', 'complete_keywords', 'semantic']
    assert results[0]['score'] > results[1]['score'] > results[2]['score']


def test_threshold_override_filters_semantics_not_exact(client, monkeypatch):
    api, store = client
    store.ollama = TechnicalOllama()
    exact = upload(api, 'exact.txt', b'Agentic AI research and implementation.')
    upload(api, 'related.txt', b'Autonomous agents with tool calling. A related candidate.')
    monkeypatch.setenv('SEMANTIC_THRESHOLD', '.95')
    monkeypatch.setattr(config, 'SEMANTIC_THRESHOLD', .95)
    assert api.post('/api/documents/search', json={'query': 'Agentic AI', 'mode': 'semantic'}).json()['results'] == []
    assert [r['id'] for r in api.post('/api/documents/search', json={'query': 'Agentic AI'}).json()['results']] == [exact]


def test_calibration_is_model_specific(tmp_path, monkeypatch):
    import json
    path = tmp_path / 'calibration.json'
    from backend.keyword_matcher import QUERY_EXPANSION_VERSION
    path.write_text(json.dumps({'model': config.EMBED_MODEL, 'document_prefix': config.DOCUMENT_PREFIX,
        'query_prefix': config.QUERY_PREFIX, 'expansion_version': QUERY_EXPANSION_VERSION,
        'thresholds': {'default': .67, 'ai': .72}, 'context_thresholds': {'ai': .64}}))
    monkeypatch.delenv('SEMANTIC_THRESHOLD', raising=False)
    monkeypatch.setattr(config, 'CALIBRATION_PATH', path)
    assert config.semantic_threshold('ai') == .72
    assert config.semantic_threshold('ai', contextual=True) == .64
    monkeypatch.setattr(config, 'EMBED_MODEL', 'a-different-model')
    assert config.semantic_threshold('ai') == config.SEMANTIC_THRESHOLD


@pytest.mark.parametrize('query,text', [('AI', 'Emails maintenance familiar'), ('ML', 'HTML XML'), ('AI', 'éAI AIé _AI AI_')])
def test_unicode_boundaries(query, text):
    assert KeywordMatcher(query).match(text) == (False, False, [])


def test_phrase_whitespace_and_no_cross_field_phrase():
    assert KeywordMatcher('Agentic AI').match('Agentic\nAI')[0]
    phrase, complete, _ = KeywordMatcher('Agentic AI').match('Agentic', 'AI')
    assert complete and not phrase
