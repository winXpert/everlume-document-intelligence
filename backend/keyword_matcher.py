"""Literal matching rules, separate from embedding-based meaning."""
import re
import unicodedata

STOPWORDS = frozenset('a an and are as at be by can could do does for from how i in is it me of on or please related show the to was what when where which who with would you documents document find about many'.split())
QUERY_EXPANSION_VERSION = 3
CONCEPTS = {
    'agentic ai': 'AI agents, autonomous agents, agent orchestration, multi-agent workflows, tool-using language models',
    'ml engineer': 'Machine Learning Engineer, model training, model deployment, MLOps',
    'ai engineer': 'Artificial Intelligence Engineer, machine learning systems, language model applications',
    'ai': 'Artificial intelligence, machine learning, intelligent software systems',
}
CONTEXT_TERMS = {
    'agentic ai': ('agentic ai', 'ai agent', 'ai agents', 'autonomous agent', 'autonomous agents', 'agent orchestration', 'multi-agent'),
    'ml engineer': ('machine learning', 'model training', 'model deployment', 'mlops', 'ml engineer'),
    'ai engineer': ('artificial intelligence', 'machine learning', 'neural networks', 'language models',
                    'ai engineer', 'ai agents', 'autonomous agents', 'model training', 'model deployment', 'mlops'),
}
CONTEXT_TERMS['ai'] = CONTEXT_TERMS['ai engineer'] + ('agentic ai',)


def words(value):
    return re.findall(r'\.net\b|\w+(?:\+\+|#|\.js\b)?', unicodedata.normalize('NFKC', value).casefold())


def bounded(pattern):
    return re.compile(r'(?<!\w)(?:' + pattern + r')(?!\w)', re.IGNORECASE)


class KeywordMatcher:
    def __init__(self, query):
        tokens = words(query)
        self.terms = list(dict.fromkeys(t for t in tokens if len(tokens) <= 2 or t not in STOPWORDS))
        self.phrase = bounded(r'\s+'.join(re.escape(t) for t in tokens)) if tokens else None
        self.patterns = [bounded(re.escape(t)) for t in self.terms]
        normalized = ' '.join(tokens)
        # Only whole-query or whole-phrase concepts expand the embedding request.
        # No expansion participates in literal matching or highlighting.
        self.intent = next((concept for concept in sorted(CONCEPTS, key=len, reverse=True)
                            if bounded(re.escape(concept).replace(r'\ ', r'\s+')).search(normalized)), 'default')
        self.semantic_query = query
        if self.intent in CONCEPTS:
            self.semantic_query += '. Related concepts: ' + CONCEPTS[self.intent]

    def match(self, *fields):
        # Keep filename and body separate: never construct a phrase across fields.
        texts = [unicodedata.normalize('NFKC', value) for value in fields]
        phrase = bool(self.phrase and any(self.phrase.search(text) for text in texts))
        hits = [term for term, pattern in zip(self.terms, self.patterns)
                if any(pattern.search(text) for text in texts)]
        complete = bool(self.terms) and len(hits) == len(self.terms)
        return phrase, complete, hits

    def semantic_context(self, text):
        """Context is a threshold feature, never an automatic semantic match."""
        return any(bounded(re.escape(term).replace(r'\ ', r'\s+')).search(text)
                   for term in CONTEXT_TERMS.get(self.intent, ()))
