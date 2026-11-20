import os
import json
from pathlib import Path

DATA = Path(os.getenv('DOCUMENT_DATA', 'data')).resolve()
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')
CHAT_MODEL = os.getenv('CHAT_MODEL', 'qwen2.5:3b')
EMBED_MODEL = os.getenv('EMBED_MODEL', 'nomic-embed-text')
DOCUMENT_PREFIX = os.getenv('DOCUMENT_PREFIX', 'search_document: ' if EMBED_MODEL.startswith('nomic-embed-text') else '')
QUERY_PREFIX = os.getenv('QUERY_PREFIX', 'search_query: ' if EMBED_MODEL.startswith('nomic-embed-text') else '')
CONTEXT_SIZE = max(2048, int(os.getenv('CONTEXT_SIZE', '4096')))
RETRIEVAL_LIMIT = min(12, max(1, int(os.getenv('RETRIEVAL_LIMIT', '3'))))
MIN_RECOMMENDATIONS = max(1, int(os.getenv('MIN_RECOMMENDATIONS', '1')))
RERANK_LIMIT = min(20, max(1, int(os.getenv('RERANK_LIMIT', '8'))))
SEARCH_AI_ENRICHMENT = os.getenv('SEARCH_AI_ENRICHMENT', 'false').lower() in {'true', '1', 'yes'}
EMBED_KEEP_ALIVE = os.getenv('EMBED_KEEP_ALIVE', '5m')
CHAT_KEEP_ALIVE = os.getenv('CHAT_KEEP_ALIVE', '5m')
MAX_UPLOAD = int(os.getenv('MAX_UPLOAD_MB', '20')) * 1024 * 1024
MAX_CHUNKS = int(os.getenv('MAX_CHUNKS', '2000'))
SEMANTIC_THRESHOLD = float(os.getenv('SEMANTIC_THRESHOLD', '0.55'))
if not 0 <= SEMANTIC_THRESHOLD <= 1:
    raise ValueError('SEMANTIC_THRESHOLD must be between 0 and 1')
CALIBRATION_PATH = Path(os.getenv('RELEVANCE_CALIBRATION', str(Path(__file__).parent / 'relevance-calibration.json')))


def semantic_threshold(intent='default', contextual=False):
    """Explicit environment override wins; calibration only applies to its model."""
    if 'SEMANTIC_THRESHOLD' in os.environ:
        return SEMANTIC_THRESHOLD
    try:
        profile = json.loads(CALIBRATION_PATH.read_text(encoding='utf-8'))
        from .keyword_matcher import QUERY_EXPANSION_VERSION
        if (profile['model'] == EMBED_MODEL and profile['document_prefix'] == DOCUMENT_PREFIX
                and profile['query_prefix'] == QUERY_PREFIX and profile['expansion_version'] == QUERY_EXPANSION_VERSION):
            thresholds = profile.get('context_thresholds', {}) if contextual else profile['thresholds']
            value = float(thresholds.get(intent, profile['thresholds'].get(intent, profile['thresholds']['default'])))
            if 0 <= value <= 1:
                return value
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return SEMANTIC_THRESHOLD
# Map opaque bearer tokens to stable user IDs, e.g. {"long-random-token":"alice"}.
TOKENS = os.getenv('DOCUMENT_TOKENS', '{}')
