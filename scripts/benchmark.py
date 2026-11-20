"""Run real Ollama indexing, retrieval, and grounded answer checks on this machine."""
import json
import platform
import tempfile
import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.ollama_service import Ollama
from backend.store import Store
from backend import config


def main():
    report = {'platform': platform.platform(), 'processor': platform.processor(),
              'models': [config.EMBED_MODEL, config.CHAT_MODEL], 'context_size': config.CONTEXT_SIZE,
              'retrieval_limit': config.RETRIEVAL_LIMIT, 'measurements': {}}
    # Chroma's native Windows index keeps file handles until process exit.
    # Ignore temporary sample cleanup failures rather than hiding test results.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
        store = Store(Path(temp), Ollama())
        with TestClient(create_app(store, {'benchmark-token': 'benchmark'})) as client:
            client.headers['Authorization'] = 'Bearer benchmark-token'
            start = time.perf_counter()
            result = client.post('/api/documents/upload', files={'file': ('leave.txt',
                b'Employee Leave Policy\nEmployees receive twenty days of annual paid leave. Leave requests need manager approval. Sick leave is five days per year.')})
            result.raise_for_status()
            report['measurements']['index_seconds'] = round(time.perf_counter() - start, 3)
            for mode in ['keyword', 'semantic', 'hybrid']:
                start = time.perf_counter()
                response = client.post('/api/documents/search', json={'query': 'paid time off', 'mode': mode})
                response.raise_for_status()
                report['measurements'][mode] = {'seconds': round(time.perf_counter() - start, 3),
                    'matches': len(response.json()['results'])}
            start = time.perf_counter()
            response = client.post('/api/documents/ask', json={'query': 'How many annual leave days do employees receive?'})
            response.raise_for_status()
            report['measurements']['answer_seconds'] = round(time.perf_counter() - start, 3)
            report['answer'] = response.json()
            report['grounded_answer_passed'] = bool(response.json()['claims']) and all(
                any(c['text'] in s['text'] and c['source_id'] == s['source_id'] for s in response.json()['sources'])
                for c in response.json()['claims'])
    Path('benchmark-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    if not report['grounded_answer_passed']:
        raise SystemExit('Model failed to return a supported answer; see benchmark-result.json')


if __name__ == '__main__':
    main()
