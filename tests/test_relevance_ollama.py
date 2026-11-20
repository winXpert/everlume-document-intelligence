"""Opt-in integration test against the actual local embedding model."""
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.ollama_service import Ollama
from backend.store import Store


@pytest.mark.skipif(os.getenv('RUN_OLLAMA_TESTS') != '1', reason='Set RUN_OLLAMA_TESTS=1 to exercise the real local model')
def test_labeled_corpus_with_real_ollama(tmp_path):
    corpus = json.loads((Path(__file__).parent / 'fixtures/relevance-corpus.json').read_text())
    store = Store(tmp_path, Ollama())
    with TestClient(create_app(store, {'integration-token': 'relevance-test'})) as api:
        api.headers['Authorization'] = 'Bearer integration-token'
        ids = {}
        for key, text in corpus['documents'].items():
            response = api.post('/api/documents/upload', files={'file': (key + '.txt', text.encode())})
            assert response.status_code == 201, response.text
            ids[key] = response.json()['id']
        for sample in corpus['queries'] + corpus['held_out_queries']:
            for mode in ['hybrid', 'semantic']:
                response = api.post('/api/documents/search', json={'query': sample['query'], 'mode': mode, 'limit': 12})
                assert response.status_code == 200, response.text
                actual = {r['id'] for r in response.json()['results']}
                expected = {ids[key] for key in sample['relevant']}
                assert actual == expected, (sample['query'], mode, response.json())
