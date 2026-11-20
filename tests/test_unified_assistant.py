import json
import pytest
from test_api import client, FakeOllama
from test_datasets import add
from backend.query_understanding import understand
from backend.ollama_service import Ollama


class IntentModel(FakeOllama):
    def __init__(self, intent='document_question', retrieval='education', subjects=(), needs=False):
        self.decision = dict(intent=intent,retrieval_query=retrieval,subjects=list(subjects),needs_criteria=needs)
        self.queries = []
        self.allowed = [0]
        self.extra = []
    def understand(self, query, dataset):
        self.queries.append((query,dataset))
        return self.decision
    def compose(self, query, sources, intent, needs_criteria=False):
        self.received = sources
        return {'claims':[{'text':'Alice studied science at Example University.',
                 'evidence':[{'source_id':sources[0]['source_id'],'quote':sources[0]['text']}]}] + self.extra,
                'needs_clarification':False}
    def verify(self, query, claims, sources):
        self.checked = claims
        return {'supported':self.allowed}


@pytest.mark.parametrize('endpoint',['search','ask'])
@pytest.mark.parametrize('query',['Walk me through her academic background',
                                'Interested in where she studied, any details?',
                                'Education details please'])
def test_same_model_pipeline_understands_unlisted_wording(client,endpoint,query):
    api, store = client
    selected = add(api,'alice.txt','General','ALICE SMITH\nEDUCATION\nBachelor of Science from Example University.')
    add(api,'outside.txt','Other','PRIVATE PERSON\nForbidden University.')
    model = IntentModel(); store.ollama = model
    body = api.post(f'/api/documents/{endpoint}',json={'query':query,'dataset':'General','mode':'keyword'}).json()
    assert model.queries == [(query,'General')]
    assert body['intent'] == 'document_question'
    assert 'Alice studied science' in body['answer'] and '[S1]' in body['answer']
    assert [item['id'] for item in body['sources']] == [selected]
    assert all('Forbidden' not in item['text'] for item in model.received)
    assert model.checked


def test_unsupported_paraphrases_and_invented_citations_are_not_displayed(client):
    api,store = client
    add(api,'alice.txt','General','ALICE SMITH\nEducation: Bachelor of Science from Example University.')
    model = IntentModel(); model.allowed = []
    model.extra = [{'text':'Alice is a surgeon.','evidence':[{'source_id':'S999','quote':'Invented citation'}]}]
    store.ollama = model
    body = api.post('/api/documents/ask',json={'query':'Describe her education','dataset':'General'}).json()
    assert 'Alice studied' not in body['answer'] and 'surgeon' not in body['answer']
    assert body['claims'] == []
    assert len(model.checked) == 1


def test_model_cannot_invent_or_relax_mandatory_requirements(client):
    api,store = client
    add(api,'sales.txt','General','ALICE SMITH\nSold AI products. 8 years experience.')
    engineer = add(api,'engineer.txt','General','BOB JONES\nAI Engineer built AI systems and Python applications. 6 years experience.')
    model = IntentModel('candidate_search','AI engineer',subjects=())
    store.ollama = model
    query = 'AI engineers with minimum 4 stars and 5+ years experience'
    body = api.post('/api/documents/search',json={'query':query,'dataset':'General'}).json()
    assert [item['id'] for item in body['results']] == [engineer]
    assert all(item['rating']['value'] >= 4 for item in body['results'])
    model.decision['subjects'] = ['Angular']
    body = api.post('/api/documents/search',json={'query':query,'dataset':'General'}).json()
    assert [item['id'] for item in body['results']] == [engineer]
    assert 'angular' not in body['validation']['criteria']['requiredSkills']


def test_boolean_exclusion_and_counts_survive_interpretation():
    model = IntentModel('candidate_search','Python React',subjects=['Python','React'])
    decision = understand(model,'Top 2 Python and React without Angular with 5+ years experience','General','all')
    assert decision.plan.requiredGroups == [['python','react']]
    assert decision.plan.excludedSkills == ['angular']
    assert decision.plan.requestedCount == 2
    assert decision.plan.numericConditions[0]['value'] == 5


@pytest.mark.parametrize('intent,query',[('dataset_count','How much stuff have I already added?'),
                                       ('dataset_list','Whose CVs did I upload?')])
def test_metadata_operations_use_model_intent_not_wording(client,intent,query):
    api,store = client
    add(api,'alice.txt','General','ALICE SMITH\nSales experience.')
    add(api,'bob.txt','Other','BOB JONES\nOther experience.')
    store.ollama = IntentModel(intent,'uploaded documents')
    body = api.post('/api/documents/search',json={'query':query,'dataset':'General'}).json()
    assert body['count'] == 1
    assert 'BOB JONES' not in body['answer']


def test_comparison_requests_context_and_revalidates_sources(client):
    api,store = client
    doc = add(api,'alice.txt','General','ALICE SMITH\nEducation: Bachelor of Science from Example University.')
    class MovingModel(IntentModel):
        def compose(self,*args):
            result = super().compose(*args)
            store.update_metadata('alice',doc,'alice.txt','Other')
            return result
    store.ollama = MovingModel('comparison','education',needs=True)
    body = api.post('/api/documents/ask',json={'query':'Would taking them both on be sensible?', 'dataset':'General'}).json()
    assert body['sources'] == [] and body['results'] == []
    assert 'changed' in body['answer']


def test_structured_interpretation_cache_and_selected_dataset(monkeypatch):
    model = Ollama(); calls=[]
    def request(endpoint,payload):
        calls.append(payload)
        return {'message':{'content':json.dumps(dict(intent='document_question',retrieval_query='education',subjects=[],needs_criteria=False))}}
    monkeypatch.setattr(model,'request',request)
    model.understand('background?', 'General'); model.understand('background?', 'General')
    model.understand('background?', 'Other')
    assert len(calls) == 2
    assert all(payload['format']['properties']['intent']['enum'] for payload in calls)


def test_unanchored_paraphrases_never_become_filters():
    model=IntentModel('document_question','academic education',['academic credentials of professionals'])
    decision=understand(model,'Walk me through their background','General','any')
    assert decision.plan.requiredGroups == []
    assert decision.ignored_subjects == 1
    model.decision['subjects'] = [{'quote':'academic background','kind':'topic'}]
    decision=understand(model,'Walk me through their academic background','General','any')
    assert decision.plan.requiredGroups == []


def test_verifier_cannot_authorize_invented_quantities_or_evaluation_scales():
    from backend.assistant_service import supported_surface
    proof=[{'source_id':'S1','quote':'Alice has a Bachelor of Science degree. Bob has a Master of Business Administration degree. 5 years experience.'}]
    assert not supported_surface({'text':'Alice has a higher qualification than Bob.','evidence':proof})
    assert not supported_surface({'text':'Alice has 10 years experience.','evidence':proof})
    assert supported_surface({'text':'Alice has a Bachelor of Science degree.','evidence':proof})


def test_numeric_units_cannot_become_skills_or_penalize_relevance():
    model=IntentModel('candidate_search','AI engineers stars 4',subjects=['AI engineers','stars'])
    decision=understand(model,'AI engineers with at least four stars','Tech','any')
    assert decision.plan.requiredGroups == [['ai engineer']]
    assert decision.retrieval_query == 'ai engineer'
    assert decision.plan.numericConditions == [{'field':'rating','operator':'>=','value':4.0}]


def test_function_words_cannot_become_mandatory_skills():
    model=IntentModel('candidate_search','workplace suitability',subjects=['required'])
    decision=understand(model,'Tell me the required candidate criteria','General','any')
    assert decision.intent == 'clarification'
    assert decision.plan.requiredGroups == []
