"""Opt-in real-Ollama smoke checks; uses an isolated temporary document library."""
import json
import tempfile
from time import perf_counter
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.store import Store
from backend.ollama_service import Ollama


def main():
    class DiagnosticOllama(Ollama):
        def compose(self,*args):
            result=super().compose(*args)
            print(json.dumps({'draft':result},ensure_ascii=True),flush=True)
            return result
        def verify(self,*args):
            result=super().verify(*args)
            print(json.dumps({'verification':result},ensure_ascii=True),flush=True)
            return result
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        store = Store(root,DiagnosticOllama())
        with TestClient(create_app(store=store,tokens={'smoke':'tester'})) as api:
            api.headers['Authorization']='Bearer smoke'
            samples=[('alice.txt','Marketing','ALICE SMITH\nMarketing Team Head. Led marketing strategy and campaigns.\nEDUCATION\nBachelor of Science from Example University.'),
                     ('bob.txt','Marketing','BOB JONES\nSales Development Representative. Built SaaS sales pipelines.\nEDUCATION\nMaster of Business Administration from Sample College.'),
                     ('engineer.txt','Tech','DAN MILLER\nAI Engineer. Built AI systems and deployed machine learning models. 6 years experience.'),
                     ('sales.txt','Tech','CAROL BROWN\nSold AI products to enterprise buyers. 8 years experience.')]
            for name,dataset,text in samples:
                response=api.post('/api/documents/upload',files={'file':(name,text.encode())},data={'category':dataset})
                assert response.status_code==201,response.text
            checks=[('Whose CVs have I uploaded?','Marketing'),
                    ('Walk me through their education','Marketing'),
                    ('AI engineers with at least four stars','Tech'),
                    ('Would taking both of them on make sense?','Marketing')]
            for query,dataset in checks:
                started=perf_counter()
                response=api.post('/api/documents/search',json={'query':query,'dataset':dataset})
                assert response.status_code==200,response.text
                body=response.json()
                print(json.dumps({'query':query,'seconds':round(perf_counter()-started,3),
                      'intent':body.get('intent'),'answer':body.get('answer'),
                      'files':[s['filename'] for s in body.get('results',[])],
                      'understanding':body.get('validation',{}).get('understanding')},ensure_ascii=True),flush=True)
                assert all(source['category']==dataset for source in body.get('sources',[]))
                if dataset=='Tech':
                    assert [r['filename'] for r in body['results']]==['engineer.txt']
                elif body.get('intent')=='clarification':
                    raise AssertionError('An ordinary request was not understood')
                elif query.startswith('Whose'):
                    assert body['count']==2 and 'ALICE SMITH' in body['answer'] and 'BOB JONES' in body['answer']
                elif 'education' in query:
                    assert 'Bachelor of Science' in body['answer'] and 'Master of Business Administration' in body['answer']
                    assert body['validation']['answer_cited_documents']==2
                else:
                    assert 'criteria' in body['answer'] and 'higher' not in body['answer']


if __name__=='__main__':
    main()
