import pytest
from test_api import client
from test_datasets import add
from backend import config


def search(api,query,**options):
    response=api.post('/api/documents/search',json={'query':query,'mode':'hybrid','dataset':'General',**options})
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.parametrize('query',['Python and React','Python, React','Python or React','Python React'])
def test_any_one_skill_is_enough_and_complete_matches_rank_first(client,query):
    api,_=client
    both=add(api,'both.txt','General','Alice builds Python and React applications.')
    python=add(api,'python.txt','General','Bob builds Python applications.')
    react=add(api,'react.txt','General','Carol builds React applications.')
    add(api,'irrelevant.txt','General','Dan manages email maintenance and invoices.')
    result=search(api,query,mode='keyword')['results']
    assert {row['id'] for row in result}=={both,python,react}
    assert result[0]['id']==both
    assert next(row for row in result if row['id']==python)['missing_skills']==['react']
    assert next(row for row in result if row['id']==python)['match_type']=='partial_keywords'


def test_related_profiles_are_labelled_without_claiming_missing_skills(client):
    api,_=client
    direct=add(api,'angular.txt','General','Alice develops Angular web applications.')
    nearby=add(api,'react.txt','General','Bob develops React web applications.')
    add(api,'accounts.txt','General','Carol manages invoices and maintenance emails.')
    rows=search(api,'Angular developers')['results']
    assert [row['id'] for row in rows]==[direct,nearby]
    related=rows[1]
    assert related['match_type']=='related_profile'
    assert related['matched_skills']==[] and related['missing_skills']==['angular']
    assert related['related_skills']==['react']
    assert any('requested skill itself was not verified' in reason for reason in related['reasons'])
    assert any(proof.get('match_kind')=='related' and proof['page']==1 for proof in related['evidence'])
    assert [row['id'] for row in search(api,'Angular developers',mode='keyword')['results']]==[direct]


def test_related_profiles_need_similarity_and_content_not_category_alone(client,monkeypatch):
    api,_=client
    add(api,'react.txt','General','Alice develops React applications.')
    add(api,'other.txt','General','Bob handles invoices and emails.')
    monkeypatch.setenv('SEMANTIC_THRESHOLD','1')
    monkeypatch.setattr(config,'SEMANTIC_THRESHOLD',1.01)
    assert search(api,'Angular')['results']==[]


def test_any_skill_retains_dataset_experience_exclusions_and_ratings(client):
    api,_=client
    good=add(api,'good.txt','General','Alice builds Python services. 6 years experience.')
    add(api,'junior.txt','General','Bob builds Python services. 2 years experience.')
    add(api,'excluded.txt','General','Carol builds React and Angular applications. 7 years experience.')
    add(api,'outside.txt','.NET','Dan builds Python applications. 8 years experience.')
    rows=search(api,'Python and React without Angular with 5+ years experience',mode='keyword')['results']
    # Experience following an exclusion is parsed before exclusion extraction.
    assert [row['id'] for row in rows]==[good]
    assert search(api,'Python and React minimum 4 stars',mode='keyword')['results']==[]


def test_strict_mode_remains_available(client):
    api,_=client
    add(api,'python.txt','General','Alice builds Python services.')
    assert len(search(api,'Python and React',mode='keyword')['results'])==1
    assert search(api,'Python and React',skill_match='all')['results']==[]


def test_no_substrings_and_no_generic_engineer_broadening(client):
    api,_=client
    add(api,'operations.txt','General','Emails maintenance familiar and HTML templates.')
    add(api,'civil.txt','General','Civil Engineer managing bridges and roads.')
    assert search(api,'AI and RAG')['results']==[]
    assert search(api,'AI Engineer')['results']==[]


def test_answer_sources_and_count_use_flexible_matches(client):
    api,_=client
    one=add(api,'one.txt','General','Alice builds Python services.')
    two=add(api,'two.txt','General','Bob builds React applications.')
    result=search(api,'Top 2 Python and React')['results']
    assert {row['id'] for row in result}=={one,two}
    assert search(api,'Top 3 Python and React')['results']==[]
    answer=api.post('/api/documents/ask',json={'query':'Python and React','dataset':'General'}).json()
    assert {row['id'] for row in answer['sources']}=={one,two}


def test_unlisted_words_are_alternatives_without_fragment_matching(client):
    api,_=client
    expected=add(api,'saas.txt','General','Alice sold SaaS products.')
    add(api,'other.txt','General','Emails familiar maintenance routines.')
    assert [row['id'] for row in search(api,'SaaS cloud sales',mode='keyword')['results']]==[expected]
