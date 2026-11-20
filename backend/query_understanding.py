"""One model-driven intent plan; literal constraints remain backend-owned."""
import re
from dataclasses import dataclass

from .keyword_matcher import bounded, STOPWORDS
from .search_constraints import parse_query, apply_matching_policy

INTENTS = {'document_question', 'comparison', 'candidate_search', 'candidate_recommendation',
           'dataset_count', 'dataset_list', 'clarification'}


@dataclass
class Understanding:
    intent: str
    retrieval_query: str
    plan: object
    needs_criteria: bool = False
    model_used: bool = True
    ignored_subjects: int = 0


def understand(model, query, dataset, policy, conversation_context=''):
    raw = (model.understand(query, dataset or '', conversation_context) if conversation_context
           else model.understand(query, dataset or ''))
    if not isinstance(raw, dict) or raw.get('intent') not in INTENTS:
        raise ValueError('The local model returned an invalid query intent')
    intent = raw['intent']
    original = parse_query(query)
    plan = apply_matching_policy(parse_query(query), policy)
    subjects = []
    ignored_subjects = 0
    proposed = raw.get('subjects', [])
    if not isinstance(proposed, list) or len(proposed) > 20:
        raise ValueError('Invalid subject evidence')
    for subject in proposed:
        kind = subject.get('kind') if isinstance(subject,dict) else 'explicit'
        quote = subject.get('quote') if isinstance(subject,dict) else subject
        if not isinstance(quote, str) or not 1 <= len(quote) <= 100:
            ignored_subjects += 1
            continue
        # The model may select user wording, never invent a mandatory skill.
        pattern = bounded(re.escape(quote).replace(r'\ ', r'\s+'))
        if not pattern.search(query):
            # An unanchored paraphrase can be a retrieval hint, never a new filter.
            # Preserve the user's deterministic requirements and ignore this span.
            ignored_subjects += 1
            continue
        if kind == 'topic' and intent not in {'candidate_search','candidate_recommendation'}:
            # A requested answer field (including unfamiliar synonyms) ranks
            # evidence; it is not a qualification every document must contain.
            continue
        term = parse_query(quote).searchQuery
        term = re.sub(r'\b(engineer|developer|architect|manager|analyst|scientist)s\b',r'\1',term)
        function_words = STOPWORDS | {'required','require','requires','must','should','need','needs','both',
                                     'either','neither','hire','hiring','say','said','we','us','they','them',
                                     'their','these','those','do','does','done'}
        if term and all(token in function_words for token in term.split()):
            continue
        if re.fullmatch(r'(?:stars?|years?|yrs?|rating|experience)',term):
            continue  # Measurements are enforced from the original numeric plan.
        if term in {'cv','cvs','resume','resumes','document','documents','file','files','candidate','candidates',
                    'profile','profiles','person','people','applicant','applicants','employee','employees',
                    'name','names','count','education','background','experience','qualifications','details'}:
            continue
        if term:
            subjects.append(term)
    # Preserve known explicit skills even if the interpreter omits one. This
    # reuses the existing backend vocabulary rather than trusting model silence.
    from .relevance_validation import ALIASES, RELATED_CONCEPTS
    known = set(ALIASES) | set(RELATED_CONCEPTS) | {'python','java','c#','c++','sql','rag','langchain',
                'langgraph','pytorch','tensorflow','aws','azure','docker','ai engineer','ml engineer'}
    normalized_query = re.sub(r'\b(engineer|developer)s\b', r'\1', query.casefold())
    remaining = re.sub(r'\b(engineer|developer)s\b', r'\1', original.searchQuery)
    # A category named as the search scope is not a skill requirement.
    if dataset:
        if re.search(r'\b(?:in|from|under)\s+(?:the\s+)?' + re.escape(dataset.casefold()) +
                     r'\s+(?:dataset|category|folder)\b', normalized_query):
            remaining = bounded(re.escape(dataset.casefold())).sub(' ', remaining)
    for term in sorted(known, key=len, reverse=True):
        pattern = bounded(re.escape(term).replace(r'\ ', r'\s+'))
        if pattern.search(remaining):
            subjects.append(term)
            remaining = pattern.sub(' ', remaining)
    subjects = list(dict.fromkeys(subjects))
    subjects = [term for term in subjects if term not in original.excludedSkills and term not in original.preferredSkills]
    if (not subjects and intent == 'candidate_search' and not
            (original.numericConditions or original.excludedSkills or original.roleRequirements)):
        # A classifier output without any valid content constraint is ambiguous;
        # never turn connective wording into skills or silently match everybody.
        intent = 'clarification'
    # Preserve original Boolean grouping while removing conversational filler.
    groups = []
    for branch in original.requiredGroups:
        cleaned = []
        for part in branch:
            part = re.sub(r'\b(engineer|developer)s\b', r'\1', part)
            cleaned.extend(term for term in subjects if bounded(re.escape(term).replace(r'\ ',r'\s+')).search(part))
        if cleaned:
            groups.append(list(dict.fromkeys(cleaned)))
    for term in subjects:
        if not any(term in branch for branch in groups):
            if groups and policy == 'all':
                groups = [branch + [term] for branch in groups]
            else:
                groups.append([term])
    if policy == 'any':
        groups = [[term] for term in subjects]
    if subjects:
        plan.requiredGroups = groups
        plan.searchQuery = ' '.join(subjects)
    elif intent not in {'candidate_search'}:
        plan.requiredGroups = []
        plan.searchQuery = raw.get('retrieval_query') or dataset or query
    # Hard filters come only from the user's original text, never from the model.
    plan.numericConditions = original.numericConditions
    plan.excludedSkills = original.excludedSkills
    plan.roleRequirements = original.roleRequirements
    plan.requestedCount = original.requestedCount
    plan.preferredSkills = original.preferredSkills
    # Context-only questions can legitimately have no explicit content topic.
    if dataset and intent != 'candidate_search':
        plan.errors = [error for error in plan.errors if error != 'Provide a topic, skill, role, or measurable requirement to search for.']
    plan.intent = 'candidate_recommendation' if intent.startswith('candidate_') else 'document_question'
    plan.interpretation = 'Ollama intent; anchored subjects; deterministic constraints'
    retrieval = raw.get('retrieval_query')
    if not isinstance(retrieval, str) or len(retrieval) > 500:
        raise ValueError('Invalid retrieval query')
    # Model retrieval text is a ranking hint, never a source of mandatory filters.
    if intent in {'candidate_search','candidate_recommendation'} and subjects:
        retrieval = ' '.join(subjects)
    return Understanding(intent, retrieval.strip() or dataset or plan.searchQuery or query, plan,
                         raw.get('needs_criteria') is True, ignored_subjects=ignored_subjects)
