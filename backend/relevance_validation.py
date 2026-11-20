"""Document evidence and conservative identity-aware duplicate detection."""
import hashlib
import re
from difflib import SequenceMatcher

from .keyword_matcher import KeywordMatcher, bounded, words
from .search_constraints import compare


ALIASES = {
    'holiday': ('holiday', 'holidays', 'vacation', 'annual leave'),
    '.net': ('.net', 'dotnet', 'dot net', 'asp.net'),
    'ai': ('ai', 'artificial intelligence', 'machine learning', 'agentic ai', 'autonomous agents', 'language models', 'model training', 'model deployment', 'mlops'),
    'agentic ai': ('agentic ai', 'ai agents', 'autonomous agents', 'agent orchestration', 'multi-agent'),
    'ml': ('ml', 'machine learning', 'model training', 'model deployment', 'mlops'),
    'paid time off': ('paid time off', 'annual paid leave', 'annual leave', 'paid vacation'),
    'rag': ('rag', 'retrieval augmented generation', 'retrieval-augmented generation'),
    'healthcare rcm': ('healthcare rcm', 'revenue cycle management', 'medical billing', 'healthcare revenue cycle'),
    'rcm': ('rcm', 'revenue cycle management'),
    'react': ('react', 'reactjs', 'react.js'),
    'angular': ('angular', 'angularjs', 'angular.js'),
    'javascript': ('javascript', 'js'), 'typescript': ('typescript', 'ts'),
    'kubernetes': ('kubernetes', 'k8s'), 'node.js': ('node.js', 'nodejs'),
}
RELATED_CONCEPTS = {
    'sales': ('business development','account executive','lead generation','customer acquisition'),
    'bde': ('business development','sales development','prospecting'),
    'bdr': ('sales development','business development','prospecting'),
    'saas': ('software as a service','subscription software','cloud products'),
    'cloud': ('aws','azure','gcp','cloud infrastructure'),
    'lead generation': ('demand generation','prospecting','outbound campaigns'),
    'angular': ('react','vue.js','vuejs','svelte','frontend development','front-end development','typescript'),
    'react': ('angular','vue.js','vuejs','svelte','next.js','frontend development','front-end development'),
    '.net': ('c#','asp.net core','backend development','back-end development','spring boot'),
    'python': ('django','fastapi','flask','pytorch','pandas','data science'),
    'java': ('spring boot','kotlin','backend development'),
    'agentic ai': ('langgraph','langchain','tool calling','function calling','llm orchestration'),
    'rag': ('semantic retrieval','vector search','retrieval pipelines','document question answering'),
    'ai': ('deep learning','natural language processing','computer vision','predictive modeling'),
    'ml': ('deep learning','data science','predictive modeling','statistical modeling'),
    'digital marketing': ('seo','ppc','paid media','google ads','social media marketing','email marketing','search engine optimization'),
    'seo': ('search engine optimization','content marketing','organic search','search engine marketing'),
    'ppc': ('paid media','google ads','paid search','performance marketing'),
    'healthcare rcm': ('claims processing','denial management','medical coding','insurance reimbursement'),
    'rcm': ('claims processing','denial management','medical coding','insurance reimbursement'),
}
NEGATED = re.compile(r'\b(?:no|not|without|lack(?:s|ing)?|never|unfamiliar with|no experience (?:in|with))\s+(?:\w+\s+){0,3}$', re.I)
HANDS_ON = re.compile(r'\b(?:develop(?:ed|ing|s)?|built|build(?:s|ing)?|implement\w*|train\w*|deploy\w*|design\w*|orchestrat\w*|integrat\w*)\b', re.I)
TECHNICAL_WORK = re.compile(r'\b(?:models?|systems?|applications?|software|pipelines?|agents?|tools?|services?|mlops|inference|training|deployment|neural|llms?|rag)\b', re.I)
NON_EXPERIENCE = re.compile(r'\b(?:seeking|looking for|hiring|vacancy|job requirements|wanted|no experience|aspiring|recruiting)\b', re.I)


def normalized(text):
    return ' '.join(words(text))


def verified_candidate_heading(pages):
    heading = next((line.strip() for line in pages[0].splitlines() if line.strip()), '') if pages else ''
    if (2 <= len(heading.split()) <= 5 and len(heading) <= 80
            and re.fullmatch(r"[^\W\d_]+(?:[ .’'\-]+[^\W\d_]+)+\.?", heading)
            and not re.search(r'\b(?:resume|curriculum|vitae|engineer|developer|manager|summary|profile|sales|marketing|consultant)\b', heading, re.I)):
        return heading
    return None


def evidence(term, pages):
    term = re.sub(r'\b(engineer|developer|architect|manager|analyst|scientist)s\b', r'\1', term.casefold()).strip()
    role = re.search(r'\b(engineer|developer|architect|manager|analyst|scientist)\b', term)
    subject = term[:role.start()].strip() if role else term
    aliases = ALIASES.get(subject, (subject,))
    # Full document pages are available: constraints can be proven on different pages.
    for page_number, text in enumerate(pages, 1):
        for alias in aliases:
            for match in bounded(re.escape(alias).replace(r'\ ', r'\s+')).finditer(text):
                if match.start() >= 2 and text[match.start()-1] == '.' and text[match.start()-2].isalnum():
                    continue  # A domain suffix is not a demonstrated skill.
                start = max(text.rfind('\n', 0, match.start()), text.rfind('. ', 0, match.start())) + 1
                ends = [position for position in [text.find('\n', match.end()), text.find('. ', match.end())] if position >= 0]
                end = min(ends) + 1 if ends else len(text)
                context = text[start:end].strip()
                prefix = text[start:match.start()]
                if NEGATED.search(prefix) or NON_EXPERIENCE.search(context):
                    continue
                if role:
                    if role[1] in ('engineer', 'developer'):
                        title_role = r'(?:developers?|engineers?|programmers?)' if role[1] == 'developer' else r'engineers?'
                        title = any(bounded(re.escape(value).replace(r'\ ', r'\s+') + r'\s+' + title_role).search(context) for value in aliases)
                        if not title and not (HANDS_ON.search(context) and TECHNICAL_WORK.search(context)):
                            continue
                    elif not bounded(role[1] + r's?').search(context):
                        continue
                return {'requirement': term, 'page': page_number, 'text': context[:1000], 'matched_term': match[0]}
    # Complete words remain valid for a rearranged phrase, but never across roles.
    if not role and len(term.split()) > 1:
        for page_number, text in enumerate(pages, 1):
            for line in re.split(r'\n|(?<=[.!?])\s+', text):
                if not NON_EXPERIENCE.search(line) and not re.search(r'\b(?:no|not|without)\b', line, re.I) and KeywordMatcher(term).match(line)[1]:
                    return {'requirement': term, 'page': page_number, 'text': line[:1000], 'matched_term': term}
    return None


def experience(pages, scope=None):
    claims = []
    patterns = [
        r'(?:(?:over|more than|at least|approximately|about|total(?: of)?)\s+)?(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:(?:professional|relevant|industry|total|work|overall|hands.on|software development)\s+)*experience\b',
        r'\b(?:total |overall |professional |work )?experience\s*[:=-]\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b',
    ]
    if scope:
        patterns = [r'(?:(?:over|more than|at least)\s+)?(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+|in\s+)?' + re.escape(scope) + r'\s+(?:development\s+)?experience\b']
    for number, page in enumerate(pages, 1):
        for pattern in patterns:
            for match in re.finditer(pattern, page, re.I):
                prefix = page[max(0, match.start() - 65):match.start()]
                suffix = page[match.end():match.end() + 35]
                if NEGATED.search(prefix) or re.search(r'\b(?:required|minimum|maximum|seeking|must have|looking for|under|less than|about|approximately)\b', prefix, re.I) or re.match(r'\s*(?:is\s+)?required\b', suffix, re.I) or re.search(r'\b(?:about|approximately)\b', match[0], re.I):
                    continue
                value = float(match[1])
                if value <= 80:
                    lower_only = bool(re.search(r'\+|\b(?:over|more than|at least)\b', match[0], re.I))
                    claims.append({'years': value, 'upper': None if lower_only else value,
                                   'strict_lower': bool(re.search(r'\b(?:over|more than)\b', match[0], re.I)),
                                   'page': number, 'text': match[0]})
    # Conflicting totals are unverifiable; do not cherry-pick the larger value.
    if len({(claim['years'], claim['upper'], claim['strict_lower']) for claim in claims}) != 1:
        return None
    return claims[0] if claims else None


def experience_satisfies(claim, condition):
    if not claim:
        return False
    operator = condition['operator']
    if operator in ('<', '<=', '=='):
        return claim['upper'] is not None and compare(claim['upper'], condition)
    if operator == '>' and claim['strict_lower'] and claim['years'] == condition['value']:
        return True
    return compare(claim['years'], condition)


def related_evidence(term, pages):
    role = re.search(r'\b(engineers?|developers?)\b', term)
    subject = term[:role.start()].strip() if role else term
    for concept in RELATED_CONCEPTS.get(subject, ()):
        proof = evidence(concept + (' ' + role[0] if role else ''), pages)
        if proof:
            return {**proof, 'requirement': term, 'matched_term': concept, 'match_kind':'related',
                    'relationship': f'{concept} is related experience for {term}; the requested skill itself was not verified'}
    return None


def validate(plan, pages, allow_related=False):
    verified, failures = [], []
    if plan.roleRequirements and not plan.requiredGroups:
        generic = next(({'requirement': 'developer work', 'page': number, 'text': page[:1000]}
                        for number, page in enumerate(pages, 1)
                        if not NON_EXPERIENCE.search(page) and
                        (bounded(r'developer|engineer|programmer').search(page) or (HANDS_ON.search(page) and TECHNICAL_WORK.search(page)))), None)
        if generic:
            verified.append(generic)
        else:
            failures.append('Developer work could not be verified')
    if plan.requiredGroups:
        branches = [[evidence(term, pages) for term in branch] for branch in plan.requiredGroups]
        if plan.matchingPolicy == 'any':
            passing = [proof for branch in branches for proof in branch if proof]
            if not passing and allow_related:
                passing = [proof for branch in plan.requiredGroups for term in branch if (proof := related_evidence(term,pages))]
            passing = passing or None
        else:
            passing = next((branch for branch in branches if all(branch)), None)
        if passing is None:
            failures.append('Required topic, skill, or role could not be verified: ' + ' OR '.join(' AND '.join(branch) for branch in plan.requiredGroups))
        else:
            verified.extend(passing)
            for role in plan.roleRequirements:
                role_proof = next((proof for item in passing if (proof := evidence(
                    (item['matched_term'] if item.get('match_kind') == 'related' else item['requirement']) + ' ' + role, pages))), None)
                if role_proof:
                    verified.append(role_proof)
                else:
                    failures.append(f'Required {role} work could not be verified for the matching skills')
    for term in plan.excludedSkills:
        found = evidence(term, pages)
        if found:
            failures.append('Excluded skill is present: ' + term)
    for condition in plan.numericConditions:
        if condition['field'] == 'experience':
            years = experience(pages, condition.get('scope'))
            if not experience_satisfies(years, condition):
                failures.append(f"Experience {condition['operator']} {condition['value']}: not verified")
            elif years:
                verified.append({'requirement': f"Experience {condition['operator']} {condition['value']} years", 'page': years['page'], 'text': years['text']})
    return verified, failures, [term for term in plan.preferredSkills if not evidence(term, pages)]


def identity(pages):
    text = '\n'.join(pages).casefold()
    emails = set(re.findall(r'[\w.+-]+@[\w.-]+\.[a-z]{2,}', text))
    # Shared recruitment addresses are deliberately not an identity key.
    emails = {value for value in emails if not re.match(r'(?:hr|jobs|careers|recruit\w*|info|contact|admin)@', value)}
    phones = {re.sub(r'\D', '', value) for value in re.findall(r'(?<!\d)(?:\+?\d[\d ()-]{8,}\d)(?!\d)', text)}
    phones = {value for value in phones if 10 <= len(value) <= 15}
    return emails, phones


def candidate_name(pages):
    if not pages:
        return None
    for line in pages[0].splitlines()[:8]:
        value = re.sub(r'^(?:name|candidate)\s*:\s*', '', line.strip(), flags=re.I)
        if re.fullmatch(r'[^\W\d_]+(?:[ .\'-]+[^\W\d_]+){1,3}', value, re.UNICODE):
            if not re.search(r'\b(?:engineer|developer|resume|curriculum|summary|skills|experience|profile|contact|details|learning|manager|sales|systems|python|java|react|education|professional|technical|architect)\b', value, re.I):
                return normalized(value)
    return None


def deduplicate(results, rows, candidate_context=False):
    kept, signatures = [], []
    for result in sorted(results, key=lambda item: (item['score'], item['uploaded'], item['id']), reverse=True):
        row = rows[result['id']]
        pages = row['_pages']
        text = normalized('\n'.join(pages))
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        people = identity(pages)
        name = candidate_name(pages)
        tokens = set(text.split())
        duplicate = False
        for previous in signatures:
            if row['digest'] == previous['digest'] or fingerprint == previous['fingerprint']:
                duplicate = True
            elif (people[0] & previous['identity'][0] or people[1] & previous['identity'][1]) and name and name == previous['name']:
                # Contact alone is insufficient; versions must also share most content.
                union = tokens | previous['tokens']
                similarity = len(tokens & previous['tokens']) / max(1, len(union))
                duplicate = similarity >= .72
            elif len(text) > 300 and len(previous['text']) > 300:
                # Require an identical opening identity block to protect similar CVs.
                same_header = text.split()[:12] == previous['text'].split()[:12]
                if same_header and (not candidate_context or (any(people) and people == previous['identity'])):
                    duplicate = SequenceMatcher(None, text, previous['text'], autojunk=False).quick_ratio() >= .96 and SequenceMatcher(None, text, previous['text'], autojunk=False).ratio() >= .94
            if duplicate:
                break
        if not duplicate:
            kept.append(result)
            signatures.append({'digest': row['digest'], 'fingerprint': fingerprint, 'identity': people, 'name': name, 'tokens': tokens, 'text': text})
    return kept
