"""Isolated real-model intent/constraint smoke test and 500-document backend check."""
import json
import platform
import tempfile
import time
from pathlib import Path

from backend import config
from backend.store import Store
from backend.ollama_service import Ollama


class CountingOllama(Ollama):
    def __init__(self):
        super().__init__()
        self.timings = []

    def request(self, endpoint, payload):
        start = time.perf_counter()
        response = super().request(endpoint, payload)
        self.timings.append({'endpoint': endpoint, 'model': payload['model'],
                             'seconds': round(time.perf_counter() - start, 3)})
        return response


def main():
    report = {'platform': platform.platform(), 'context_size': config.CONTEXT_SIZE,
              'models': [config.CHAT_MODEL, config.EMBED_MODEL], 'queries': []}
    model = CountingOllama()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        store = Store(directory, model)
        samples = {
            'alice': 'Alice Example\nalice@example.test\nAI Engineer built Agentic AI and RAG applications with Python. 6 years experience.',
            'alice-copy': 'Alice Example\nalice@example.test\nAI Engineer built Agentic AI and RAG applications with Python. 6 years experience.',
            'bob': 'Bob Example\nbob@example.test\nAI Engineer developed Agentic AI and RAG systems in Python. 7 years experience.',
            'sales': 'Carol Example\nSales engineer selling AI products and managing emails. 10 years experience.',
        }
        start = time.perf_counter()
        for key, text in samples.items():
            path = store.files / key
            path.write_text(text, encoding='utf-8')
            store.index('synthetic', key, path, key + '.txt', 'Synthetic', 'test')
        report['index_seconds'] = round(time.perf_counter() - start, 3)
        for query, expected in [
            ('Best 2 AI engineers with minimum 4 stars and 5+ years experience', 2),
            ('Best 3 AI engineers with minimum 4 stars', 0),
            ('Find Agentic AI and RAG experts without Angular', 2),
        ]:
            start = time.perf_counter()
            results = store.search('synthetic', query, 'hybrid', 3)
            entry = {'query': query, 'seconds': round(time.perf_counter()-start, 3),
                     'results': len(results), 'ids': [item['id'] for item in results],
                     'criteria': results.details['criteria'], 'duplicates_removed': results.details['duplicates_removed']}
            assert len(results) == expected, entry
            assert all(item['id'] != 'sales' for item in results), entry
            assert all(item['evidence'] for item in results), entry
            report['queries'].append(entry)
        report['model_calls'] = model.timings
    # A separate deterministic embedding fixture isolates backend scaling from model time.
    class Fixture:
        def embed(self, texts):
            return [[1., 0., 0.] for _ in texts]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        store = Store(directory, Fixture())
        for index in range(500):
            key = f'candidate-{index}'
            path = store.files / key
            path.write_text(f'Person {index}\nperson{index}@example.test\nPython developer builds production React applications. 6 years experience.', encoding='utf-8')
            store.index('synthetic', key, path, key + '.txt', 'Synthetic', 'test')
        measurements = []
        for _ in range(2):
            start = time.perf_counter()
            result = store.search('synthetic', 'Top 5 Python and React developers with 5+ years experience', 'hybrid', 3)
            assert len(result) == 5 and result.details['qualified_count'] == 500
            measurements.append(round(time.perf_counter() - start, 3))
        report['500_document_backend_seconds'] = measurements
        report['500_document_note'] = 'Real SQLite/Chroma and validation; deterministic embeddings, no language-model latency.'
    Path('intent-search-validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
