"""Measure the actual Ollama model against a labeled local relevance corpus.

python -m scripts.calibrate_relevance [--write]
Only --write updates the deployed calibration; reports never read user documents.
"""
import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from backend import config
from backend.keyword_matcher import KeywordMatcher, QUERY_EXPANSION_VERSION
from backend.ollama_service import Ollama
from backend.search_constraints import parse_query
import re

ROOT = Path(__file__).resolve().parent.parent


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x*x for x in a) * sum(y*y for y in b))


def measure(pairs, threshold):
    tp = sum(score >= threshold and relevant for score, relevant in pairs)
    fp = sum(score >= threshold and not relevant for score, relevant in pairs)
    fn = sum(score < threshold and relevant for score, relevant in pairs)
    return {'true_positive': tp, 'false_positive': fp, 'false_negative': fn,
            'precision': round(tp / max(1, tp + fp), 4), 'recall': round(tp / max(1, tp + fn), 4)}


def choose_threshold(pairs):
    # Precision first: select above observed negative examples, then maximize
    # recall. This is measured per model and intent, never a universal cosine.
    negatives = [score for score, relevant in pairs if not relevant]
    positives = [score for score, relevant in pairs if relevant]
    floor = min(positives) - .03 if positives else 0.
    return round(min(1., max(negatives) + .015 if negatives else max(0., floor)), 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    corpus = json.loads((ROOT / 'tests/fixtures/relevance-corpus.json').read_text())
    ollama = Ollama()
    started = time.perf_counter()
    names = list(corpus['documents'])
    document_vectors = ollama.embed([config.DOCUMENT_PREFIX + corpus['documents'][name] for name in names])
    queries = corpus['queries'] + corpus['held_out_queries']
    matchers = [KeywordMatcher(re.sub(r'\bengineers\b', 'engineer', parse_query(item['query']).searchQuery)) for item in queries]
    query_vectors = ollama.embed([config.QUERY_PREFIX + matcher.semantic_query for matcher in matchers])
    samples, groups, context_groups = [], {}, {}
    for index, (item, vector) in enumerate(zip(queries, query_vectors)):
        matcher = matchers[index]
        intent = matcher.intent
        pairs = [(cosine(vector, embedding), name in item['relevant']) for name, embedding in zip(names, document_vectors)]
        contextual = [matcher.semantic_context(corpus['documents'][name]) for name in names]
        held_out = index >= len(corpus['queries'])
        samples.append({'query': item['query'], 'intent': intent, 'held_out': held_out,
                        'scores': {name: round(score, 4) for name, (score, _) in zip(names, pairs)},
                        'relevant': item['relevant'], '_pairs': pairs, '_contextual': contextual})
        if not held_out:
            groups.setdefault(intent, []).extend(pairs)
            context_groups.setdefault(intent, []).extend(pair for pair, context in zip(pairs, contextual) if context)
    thresholds = {intent: choose_threshold(pairs) for intent, pairs in groups.items()}
    context_thresholds = {intent: min(thresholds[intent], choose_threshold(pairs)) for intent, pairs in context_groups.items() if pairs}
    for sample in samples:
        threshold = thresholds.get(sample['intent'], thresholds['default'])
        sample['threshold'] = threshold
        contextual_threshold = context_thresholds.get(sample['intent'], threshold)
        sample['context_threshold'] = contextual_threshold
        pairs = sample.pop('_pairs')
        contexts = sample.pop('_contextual')
        sample['contextual_documents'] = [name for name, context in zip(names, contexts) if context]
        # Normalize each score by its applicable threshold for aggregate metrics.
        sample['metrics'] = measure([(score - (contextual_threshold if context else threshold), relevant)
                                     for (score, relevant), context in zip(pairs, contexts)], 0)
    report = {'model': config.EMBED_MODEL, 'document_prefix': config.DOCUMENT_PREFIX,
              'query_prefix': config.QUERY_PREFIX, 'expansion_version': QUERY_EXPANSION_VERSION,
              'created': datetime.now(timezone.utc).isoformat(), 'thresholds': thresholds, 'context_thresholds': context_thresholds,
              'seconds': round(time.perf_counter() - started, 3), 'samples': samples}
    target = ROOT / 'relevance-calibration-report.json'
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    if args.write:
        config.CALIBRATION_PATH.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'thresholds': thresholds, 'samples': [{k: s[k] for k in ['query', 'held_out', 'metrics']} for s in samples],
                      'report': str(target), 'seconds': report['seconds']}, indent=2))


if __name__ == '__main__':
    main()
