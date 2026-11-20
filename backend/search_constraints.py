"""Query plans: explicit syntax is authoritative; model suggestions cannot relax it."""
import re
from dataclasses import asdict, dataclass, field
from .keyword_matcher import KeywordMatcher

NUMBER_WORDS = dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split(), range(21)))
COMPARATORS = {
    'above': '>', 'over': '>', 'more than': '>', 'greater than': '>', '>': '>',
    'below': '<', 'under': '<', 'less than': '<', '<': '<',
    'maximum': '<=', 'at most': '<=', 'up to': '<=', 'no more than': '<=', '<=': '<=',
    'exactly': '==', '=': '==', 'equal to': '==',
}
COMPARE = r'(?:no more than|more than|greater than|less than|at least|at most|minimum(?: of)?|maximum(?: of)?|up to|above|below|under|over|exactly|equal to|>=|<=|>|<|=)'
MEASURE = re.compile(r'(?P<op>' + COMPARE + r')?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<plus>\+)?\s*(?P<unit>stars?|years?|yrs?)\b(?:\s+(?:of\s+)?(?:experience|rating))?', re.I)


@dataclass
class Plan:
    original: str
    searchQuery: str = ''
    intent: str = 'document_search'
    requiredGroups: list = field(default_factory=list)
    roleRequirements: list = field(default_factory=list)
    excludedSkills: list = field(default_factory=list)
    preferredSkills: list = field(default_factory=list)
    numericConditions: list = field(default_factory=list)
    requestedCount: int | None = None
    sortBy: str = 'relevance'
    sortOrder: str = 'desc'
    errors: list = field(default_factory=list)
    interpretation: str = 'deterministic'
    matchingPolicy: str = 'all'

    def public(self):
        result = asdict(self)
        result['requiredSkills'] = list(dict.fromkeys(term for branch in self.requiredGroups for term in branch))
        result['booleanPolicy'] = ('Any one requested skill or supported related concept; exclusions and numeric conditions still apply'
                                 if self.matchingPolicy == 'any' else 'OR of AND branches in requiredGroups; exclusions apply to every branch')
        return result


def apply_matching_policy(plan, policy):
    plan.matchingPolicy = policy
    if policy != 'any':
        return plan
    # Keep meaningful phrases and job titles intact; split whitespace skill lists.
    skills = sorted({'agentic ai','machine learning','digital marketing','social media','healthcare rcm',
                     'ai engineer','ml engineer','artificial intelligence','revenue cycle management',
                     'python','java','react','angular','.net','c#','c++','javascript','typescript','sql',
                     'rag','ai','ml','langchain','langgraph','pytorch','tensorflow','fastapi','django',
                     'seo','sem','ppc','google ads','email marketing','aws','azure','docker','kubernetes'}, key=len, reverse=True)
    skills = sorted(set(skills) | {'business development','lead generation','demand generation','account management',
                    'sales development','customer success','performance marketing','content marketing','paid search',
                    'data science','deep learning','natural language processing','computer vision','annual leave',
                    'paid time off'},key=len,reverse=True)
    alternatives = []
    for term in dict.fromkeys(term for branch in plan.requiredGroups for term in branch):
        remaining = term
        found = []
        for skill in skills:
            pattern = re.compile(r'(?<!\w)' + re.escape(skill) + r'(?!\w)', re.I)
            if pattern.search(remaining):
                found.append(skill)
                remaining = pattern.sub(' ', remaining)
        # Unknown descriptive text is not silently discarded.
        if found and not remaining.strip(' /;:'):
            alternatives.extend(found)
        elif re.search(r'\b(?:engineers?|developers?|architects?|managers?|analysts?|scientists?)\b',term):
            alternatives.append(term)
        else:
            alternatives.extend(found + KeywordMatcher(remaining).terms)
    plan.requiredGroups = [[term] for term in dict.fromkeys(alternatives)]
    return plan


def clean(value):
    value = re.sub(r'\b(?:in all of this|all of these|who has|who have|can you|could you|would you|i want|i need|looking for|someone who|people who|related to)\b', ' ', value, flags=re.I)
    value = re.sub(r'\b(?:best|strongest|top|find|show|recommend|give|list|search|please|me|the|for|in all of this|all of these|who has|who have|documents?|profiles?|candidates?|people|developers?|experts?|specialists?|with|experience|experienced|skills?|related to|about|in)\b', ' ', value, flags=re.I)
    value = re.sub(r'\b(?:who|knows?|knowledge of|demonstrating|demonstrates|showing|using|working|work|as|a|an|all|this|these|that|those|some|any|our|my|has|have|can|you|i|want|need|someone)\b', ' ', value, flags=re.I)
    return re.sub(r'\s+', ' ', value).strip(' ,;:?!()"').rstrip('.')


def boolean_groups(text):
    """Small bounded AND/OR expression parser, returning disjunctive normal form."""
    tokens = [token.strip() for token in re.split(r'(\band\b|\bor\b|[(),])', text) if token.strip()]
    position = 0
    def atom():
        nonlocal position
        if position >= len(tokens):
            raise ValueError('Incomplete AND/OR condition.')
        token = tokens[position]
        position += 1
        if token == '(':
            result = expression()
            if position >= len(tokens) or tokens[position] != ')':
                raise ValueError('Unclosed condition parentheses.')
            position += 1
            return result
        if token in ('and', 'or', ',', ')'):
            raise ValueError('Incomplete AND/OR condition.')
        term = clean(token)
        return [[term]] if term else [[]]
    def conjunction():
        nonlocal position
        result = atom()
        while position < len(tokens) and tokens[position] in ('and', ','):
            position += 1
            right = atom()
            if len(result) * len(right) > 64:
                raise ValueError('Too many combined alternatives; simplify the query.')
            result = [list(dict.fromkeys(left + right_branch)) for left in result for right_branch in right]
        return result
    def expression():
        nonlocal position
        result = conjunction()
        while position < len(tokens) and tokens[position] == 'or':
            position += 1
            result += conjunction()
            if len(result) > 64:
                raise ValueError('Too many alternatives; simplify the query.')
        return result
    if not tokens:
        return []
    result = expression()
    if position != len(tokens):
        raise ValueError('Could not interpret the condition grouping.')
    return [branch for branch in result if branch]


def parse_query(query):
    text = query.casefold()
    text = re.sub(r'\b(?:not|no) less than\b', 'at least', text)
    text = re.sub(r'\bnot more than\b', 'at most', text)
    def number_word(match):
        prefix, suffix = text[:match.start()], text[match.end():]
        if re.search(r'\b(?:top|best|first|exactly|show|recommend(?: me)?|suggest(?: me)?|select|choose|pick|find|give me)\s*$', prefix) or re.match(r'\s*(?:\+\s*)?(?:stars?|years?|yrs?|documents?|profiles?|candidates?|results?)\b', suffix):
            return str(NUMBER_WORDS[match[0]])
        return match[0]
    text = re.sub(r'\b(' + '|'.join(NUMBER_WORDS) + r')\b', number_word, text)
    text = re.sub(r'\b(?:pyhton|phyton)\b', 'python', text)
    text = re.sub(r'\b(?:machin learning|machine learing)\b', 'machine learning', text)
    text = re.sub(r'\bmore\s+th(?:a|n|en)\b', 'more than', text)
    text = re.sub(r'\b(?:higher|greater) than\b', 'more than', text)
    text = re.sub(r'\b(?:lower|fewer) than\b', 'less than', text)
    text = re.sub(r'\b(rating|rated|experience)\s+(?:is|should be|must be)\b', r'\1', text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*/\s*5\b', r'\1 stars', text)
    text = text.replace('★', ' stars ')
    text = re.sub(r'\b(minimum|maximum)\s+(?:star\s+)?rating\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)\b', r'\1 \2 stars', text)
    text = re.sub(r'\b(minimum|maximum)\s+experience\s*(?:of|:|=)?\s*(\d+(?:\.\d+)?)(?!\w)(?!\s*(?:years?|yrs?)\b)', r'\1 \2 years experience', text)
    text = re.sub(r'\b(?:rated|rating)\s*(?:of|:)?\s*(' + COMPARE + r')?\s*(\d+(?:\.\d+)?)(?!\w)(?!\s*stars?\b)', r'\1 \2 stars', text)
    text = re.sub(r'\bexperience\s*(' + COMPARE + r')\s*(\d+(?:\.\d+)?)(?!\w)(?!\s*(?:years?|yrs?)\b)', r'\1 \2 years experience', text)
    plan = Plan(query)
    if re.search(r'\b(?:engineers?|developers?|candidates?|profiles?|experts?)\b', text):
        plan.intent = 'candidate_recommendation'
    counts = list(re.finditer(r'\b(?:top|best|first|exactly|show|recommend(?: me)?|suggest(?: me)?|select|choose|pick|find|give me)\s+(\d+)\b(?!\s*(?:\+\s*)?(?:stars?|years?|yrs?)\b)|\b(\d+)\s+(?:documents?|profiles?|candidates?|results?|recommendations?)\b', text))
    if counts:
        values = {int(m[1] or m[2]) for m in counts}
        if len(values) != 1 or not 1 <= next(iter(values)) <= 100:
            plan.errors.append('Specify one result count between 1 and 100.')
        else:
            plan.requestedCount = values.pop()
        for match in reversed(counts):
            text = text[:match.start()] + ' ' + text[match.end():]
    def measure(match):
        unit = 'rating' if match['unit'].startswith('star') else 'experience'
        operator = COMPARATORS.get((match['op'] or '').replace(' of', ''), '>=')
        value = float(match['value'])
        if unit == 'rating' and value > 5:
            plan.errors.append('Relevance ratings must be between 0 and 5.')
        condition = {'field': unit, 'operator': operator, 'value': value}
        suffix = text[match.end():]
        scope = re.match(r'\s*(?:of|in|with)\s+([\w.+# -]{1,50}?)\s+(?:development\s+)?experience\b', suffix)
        if scope and unit == 'experience':
            condition['scope'] = scope[1].strip()
        plan.numericConditions.append(condition)
        return ' '
    text = MEASURE.sub(measure, text)
    # A range contributes both bounds, and must never become a result count.
    ranges = re.compile(r'\b(?:between\s+)?(\d+(?:\.\d+)?)\s*(?:-|to|and)\s*(\d+(?:\.\d+)?)\s*(stars?|years?|yrs?)\b')
    # Process ranges on the original query before single-value matches.
    for match in ranges.finditer(query.casefold()):
        field_name = 'rating' if match[3].startswith('star') else 'experience'
        plan.numericConditions = [c for c in plan.numericConditions if not (c['field'] == field_name and c['value'] == float(match[2]))]
        plan.numericConditions.extend([{'field': field_name, 'operator': '>=', 'value': float(match[1])}, {'field': field_name, 'operator': '<=', 'value': float(match[2])}])
        text = re.sub(r'\b(?:between\s+)?' + re.escape(match[1]) + r'\s*(?:-|to|and)\s*', ' ', text)
    # Reject leftover quantitative syntax instead of silently ignoring it.
    if re.search(r'[<>]=?|\b\d+\s*\+?\s*(?:stars?|years?|yrs?)\b', text):
        plan.errors.append('A numerical condition could not be interpreted; use years, stars, or Top N explicitly.')
    preferred = re.search(r'\b(?:preferably|preferred|nice to have|ideally)\b(.+)', text)
    if preferred:
        plan.preferredSkills = [clean(s) for s in re.split(r'\band\b|\bor\b|,', preferred[1]) if clean(s)]
        text = text[:preferred.start()]
    exclusions = re.search(r'\b(?:without|excluding|exclude|but not|not|no)\b(.+)', text)
    if exclusions:
        plan.excludedSkills = [clean(s) for s in re.split(r'\band\b|\bor\b|,', exclusions[1]) if clean(s)]
        text = text[:exclusions.start()]
        if not plan.excludedSkills:
            plan.errors.append('An exclusion was specified without a skill.')
    text = re.sub(r'\b(?:minimum|maximum|at least|at most|rating|rated|of|a|an|has|have|is|are)\b', ' ', text)
    # Remove dangling connectors left by stripped numerical conditions only.
    if re.search(r'\bdevelopers?\b', text):
        plan.roleRequirements.append('developer')
    if plan.numericConditions or plan.excludedSkills:
        text = re.sub(r'\b(?:and|with)\s*$', '', text).strip()
    try:
        plan.requiredGroups = boolean_groups(text)
    except (ValueError, RecursionError) as exc:
        plan.errors.append(str(exc) if isinstance(exc, ValueError) else 'Condition grouping is too deeply nested.')
    plan.searchQuery = ' '.join(dict.fromkeys(t for branch in plan.requiredGroups for t in branch))
    if not plan.searchQuery and not plan.numericConditions:
        plan.errors.append('Provide a topic, skill, role, or measurable requirement to search for.')
    return plan


def compare(actual, condition):
    if actual is None:
        return False
    return {'>=': actual >= condition['value'], '>': actual > condition['value'],
            '<=': actual <= condition['value'], '<': actual < condition['value'],
            '==': actual == condition['value']}[condition['operator']]


def is_dataset_selection(query, dataset=None):
    text = query.strip().casefold().rstrip('?.!')
    if not re.search(r'\b(?:select|choose|pick|suggest|recommend)\b', text):
        return False
    plan = parse_query(query)
    if plan.numericConditions or plan.excludedSkills or plan.roleRequirements:
        return False
    if dataset:
        text = re.sub(r'(?<!\w)' + re.escape(dataset.casefold()) + r'(?!\w)', ' ', text)
    text = re.sub(r'\b(?:' + '|'.join(NUMBER_WORDS) + r'|\d+)\b', ' ', text)
    text = re.sub(r'\b(?:i|have|need|want|would|like|to|can|could|you|please|select|choose|pick|suggest|recommend|me|a|an|the|from|in|of|this|that|selected|current|dataset|category|folder|candidate|candidates|resume|resumes|profile|profiles|best|suitable)\b', ' ', text)
    return not text.strip()


def is_document_question(query, dataset=None):
    """Question intent is distinct from a request to filter candidate skills."""
    text = re.sub(r'^cane\b', 'can', query.strip().casefold())
    plan = parse_query(query)
    # Explicit filters continue through the existing strict validation pipeline.
    if plan.numericConditions or plan.excludedSkills or plan.roleRequirements:
        return False
    return bool(is_dataset_selection(query, dataset) or re.search(r'^(?:what|where|when|why|how|who\s+(?:is|are)|tell\s+me|describe|explain|summari[sz]e|compare|i\s+(?:have|need|want|would)|(?:can|could|should|would|do|does|are|is)\s+(?:we|i|you|they|these|both|it))\b', text)
                or re.search(r'\b(?:education|qualifications|employers?|universit(?:y|ies)|colleges?|locations?|contact details|email addresses|project details|career history)\b', text))
