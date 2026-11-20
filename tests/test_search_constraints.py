import json
import pytest

from test_api import client, upload, FakeOllama
from backend.search_constraints import parse_query, compare
from backend.relevance_validation import validate, deduplicate


@pytest.mark.parametrize('query,subject,count,conditions', [
    ('Best for AI in all of this', 'ai', None, []),
    ('Find .NET developers', '.net', None, []),
    ('AI engineers with minimum 3 stars', 'ai engineers', None, [('rating', '>=', 3)]),
    ('Find candidates with 5+ years experience', '', None, [('experience', '>=', 5)]),
    ('Top 5 Python developers', 'python', 5, []),
    ('Best 3 ML engineers with 4+ stars', 'ml engineers', 3, [('rating', '>=', 4)]),
    ('Who has experience with healthcare RCM?', 'healthcare rcm', None, []),
    ('AI engineers above four stars and below 8 years experience', 'ai engineers', None, [('rating', '>', 4), ('experience', '<', 8)]),
    ('top five Python developers with at least three stars', 'python', 5, [('rating', '>=', 3)]),
])
def test_prompt_examples(query, subject, count, conditions):
    plan = parse_query(query)
    assert not plan.errors, plan
    assert plan.searchQuery == subject
    assert plan.requestedCount == count
    assert [(c['field'], c['operator'], c['value']) for c in plan.numericConditions] == conditions


def search(api, query, **kwargs):
    response = api.post('/api/documents/search', json={'query': query, 'mode': 'keyword', **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def test_and_or_not_and_preferred(client):
    api, _ = client
    both = upload(api, 'both.txt', b'Alice develops Python and React applications. 6 years experience.')
    python = upload(api, 'python.txt', b'Bob develops Python services. 8 years experience.')
    upload(api, 'angular.txt', b'Carol develops React and Angular applications.')
    assert [r['id'] for r in search(api, 'Python and React', skill_match='all')['results']] == [both]
    assert {r['id'] for r in search(api, 'Candidates with Python or React')['results']} == {both, python, next(r['id'] for r in api.get('/api/documents').json()['documents'] if r['name']=='angular.txt')}
    result = search(api, 'Find React developers without Angular preferably Kubernetes')['results']
    assert [r['id'] for r in result] == [both]
    assert result[0]['missing_preferred'] == ['kubernetes']


def test_exact_count_after_validation_and_deduplication(client):
    api, _ = client
    upload(api, 'one.txt', b'Alice is a Python developer. 6 years experience.')
    upload(api, 'copy.txt', b'Alice is a Python developer. 6 years experience.')
    upload(api, 'low.txt', b'Bob is a Python developer. 2 years experience.')
    result = search(api, 'Top 2 Python developers with 5+ years experience')
    assert result['results'] == []
    assert result['validation']['qualified_count'] == 1
    assert result['validation']['duplicates_removed'] == 1
    assert 'only 1' in result['message']
    upload(api, 'two.txt', b'Carol builds Python services. 7 years experience.')
    assert len(search(api, 'Top 2 Python developers with 5+ years experience')['results']) == 2


def test_raw_rating_and_comparators(client):
    api, _ = client
    upload(api, 'profile.txt', b'Alice builds Python services.')
    assert len(search(api, 'Python with at least 4.5 stars')['results']) == 1
    assert search(api, 'Python above 4.5 stars')['results'] == []
    assert search(api, 'Python below 4.5 stars')['results'] == []
    assert len(search(api, 'Python at most 4.5 stars')['results']) == 1
    assert compare(3.9999, {'value':4, 'operator':'>='}) is False


def test_roles_and_unverified_experience_fail_closed(client):
    api, _ = client
    upload(api, 'sales.txt', b'Sales manager selling AI products. 10 years experience.')
    verified = upload(api, 'engineer.txt', b'AI Engineer built LLM and RAG applications. 6 years experience.')
    upload(api, 'unknown.txt', b'AI Engineer builds applications.')
    upload(api, 'requirements.txt', b'We are hiring an AI Engineer. Minimum 8 years experience required.')
    result = search(api, 'AI engineers with 5+ years experience and minimum 3 stars')
    assert [r['id'] for r in result['results']] == [verified]
    assert len(result['results'][0]['evidence']) >= 2


def test_document_level_and_across_pages():
    proofs, failures, _ = validate(parse_query('Agentic AI and RAG experts'), ['Built autonomous agents with tools.', 'Implemented retrieval augmented generation.'])
    assert not failures
    assert {p['page'] for p in proofs} == {1, 2}


def test_spelling_abbreviation_negation_and_punctuation(client):
    api, _ = client
    dotnet = upload(api, 'dotnet.txt', b'Alice develops ASP.NET applications in C#.')
    upload(api, 'internet.txt', b'Internet sales and email maintenance.')
    assert [r['id'] for r in search(api, 'Find .NET developers')['results']] == [dotnet]
    python = upload(api, 'python.txt', b'Bob builds Python software. No Angular experience.')
    assert [r['id'] for r in search(api, 'Find Pyhton developers without Angular')['results']] == [python]


def test_min_max_experience_and_unknown(client):
    api, _ = client
    good = upload(api, 'good.txt', b'Alice writes Python. Total experience: 5 years.')
    upload(api, 'unknown.txt', b'Bob writes Python. Joined company in 2018.')
    upload(api, 'too-many.txt', b'Carol writes Python. 9 years of professional experience.')
    assert [r['id'] for r in search(api, 'Python with at least 5 years and at most 7 years experience')['results']] == [good]


def test_model_cannot_override_constraints_or_invent_evidence(client):
    api, store = client
    class MaliciousModel(FakeOllama):
        def interpret(self, query):
            return {'searchQuery':'AI', 'requiredSkills': [], 'minimumExperienceYears':0, 'requestedCount':1}
        def rerank(self, query, candidates):
            return {'results':[{'id': c['id'], 'quote':'Invented experience', 'relevance':3} for c in candidates]}
    store.ollama = MaliciousModel()
    upload(api, 'junior.txt', b'AI Engineer developing RAG systems. 2 years experience.')
    assert search(api, 'Top 2 AI engineers with 5+ years experience')['results'] == []
    result = search(api, 'AI Engineer')['results'][0]
    assert 'rerank_evidence' not in result


def test_default_count_and_invalid_queries(client, monkeypatch):
    from backend import config
    api, _ = client
    for number in range(5):
        upload(api, f'profile-{number}.txt', f'Candidate {number} builds Python applications.'.encode())
    assert len(search(api, 'Python')['results']) == 5
    assert search(api, 'Top 6 Python')['results'] == []
    assert search(api, 'Best')['results'] == []
    assert search(api, 'Python minimum 8 stars')['results'] == []
    monkeypatch.setattr(config, 'MIN_RECOMMENDATIONS', 6)
    assert search(api, 'Python')['results'] == []


def test_candidate_versions_and_different_people():
    def row(key, name, email, extra=''):
        text = f'{name}\n{email}\nPython developer builds production systems with React and PostgreSQL. 6 years experience. {extra}'
        return {'id':key,'digest':key,'_pages':[text]}
    rows = {'a':row('a','Alice Smith','alice@example.com'),
            'b':row('b','Alice Smith','alice@example.com','Also uses Docker.'),
            'c':row('c','Bob Smith','bob@example.com')}
    results = [{'id':key,'score':score,'uploaded':'2026'} for key, score in [('a',.8),('b',.9),('c',.85)]]
    assert [r['id'] for r in deduplicate(results, rows, True)] == ['b','c']


def test_intervals_scoped_experience_and_parentheses():
    assert not validate(parse_query('Python minimum 5 years experience'), ['Python developer. Over 5 years experience.'])[1]
    assert validate(parse_query('Python maximum 5 years experience'), ['Python developer. 5+ years experience.'])[1]
    assert validate(parse_query('Python above 5 years experience'), ['Python developer. 5 years experience.'])[1]
    assert not validate(parse_query('Python above 5 years experience'), ['Python developer. Over 5 years experience.'])[1]
    assert validate(parse_query('Python with 5 years of Python experience'), ['Python developer. 7 years experience.'])[1]
    assert not validate(parse_query('Python with 5 years of Python experience'), ['Python developer. 6 years of Python experience.'])[1]
    plan = parse_query('(Python or Java) and React')
    assert not plan.errors
    assert plan.requiredGroups == [['python','react'],['java','react']]
    assert validate(plan, ['Python services without React.'])[1]
    assert not validate(plan, ['Java services. React applications.'])[1]


@pytest.mark.parametrize('query,operator,value', [
    ('AI rated above 4 stars', '>', 4), ('AI minimum rating 3.5', '>=', 3.5),
    ('AI rated not less than 3', '>=', 3), ('AI rated at most 4/5', '<=', 4),
    ('AI maximum rating 4', '<=', 4),
    ('best in ai and rating is more tha 2.5', '>', 2.5),
])
def test_rating_language(query, operator, value):
    plan = parse_query(query)
    assert not plan.errors
    assert plan.numericConditions == [{'field':'rating','operator':operator,'value':value}]


def test_filename_is_not_proof_and_sales_engineers_do_not_qualify(client):
    api, _ = client
    upload(api, 'AI-Engineer.txt', b'Emails maintenance familiar and quarterly sales.')
    upload(api, 'sales-engineer.txt', b'Sales engineer selling AI products. 8 years experience.')
    assert search(api, 'AI Engineer')['results'] == []


def test_best_ai_requires_technical_evidence_for_high_ratings(client):
    api, _ = client
    upload(api, 'sales.txt', b'Alice is a sales manager selling AI products. 8 years experience.')
    technical = upload(api, 'technical.txt', b'Bob is an AI Engineer building LLM and RAG systems.')
    result = search(api, 'Best in AI with minimum 4 stars')['results']
    assert [r['id'] for r in result] == [technical]
    assert result[0]['highlight_query'] == 'ai'
    all_results = search(api, 'AI')['results']
    assert all_results[0]['id'] == technical
    assert all_results[-1]['rating']['value'] < 3
    upload(api, 'domain.txt', b'Carol sells products using Instantly.ai and manages emails.')
    assert len(search(api, 'AI')['results']) == 2
    assert [r['id'] for r in search(api, 'Find AI developers')['results']] == [technical]


def test_general_terms_and_conversational_variations():
    assert parse_query('Can you recommend someone who knows FastAPI?').requiredGroups == [['fastapi']]
    assert parse_query('Python or').errors
    assert parse_query('Python 3.11').requiredGroups == [['python 3.11']]
    assert parse_query('twenty days').requiredGroups == [['twenty days']]
    assert not parse_query('Who has experience with healthcare RCM?').errors
