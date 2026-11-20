"""Opt-in real local-model checks without touching the user's document library."""
import json
import tempfile
import sys
from time import perf_counter
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.store import Store
from backend.ollama_service import Ollama


def main():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        store=Store(root,Ollama())
        with TestClient(create_app(store=store,tokens={'smoke':'tester'})) as api:
            api.headers['Authorization']='Bearer smoke'
            history=[]
            cases=[('What is machine learning?','auto','general'),
                   ('Explain it with a simple example.','auto','general'),
                   ('How many resumes are in this dataset?','auto','document'),
                   ('What skills should an AI Engineer have?','auto','general'),
                   ('Compare these candidates against AI engineering best practices.','auto','hybrid')]
            for query,mode,expected in ([] if '--hybrid-only' in sys.argv else cases):
                started=perf_counter()
                result=api.post('/api/documents/ask',json={'query':query,'query_mode':mode,
                    'dataset':'General','history':history}).json()
                print(json.dumps({'query':query,'mode':result.get('query_mode'),
                    'seconds':round(perf_counter()-started,2),'answer':result.get('answer')},ensure_ascii=True),flush=True)
                assert result.get('query_mode')==expected,result
                assert result.get('answer') and result.get('sources')==[],result
                if expected=='general':
                    assert '[S1]' not in result['answer']
                if expected=='hybrid':
                    assert result.get('general_guidance') and not result.get('claims')
                history=(history+[{'role':'user','content':query,'dataset':'General'},
                    {'role':'assistant','content':result['answer'][:1500],'dataset':'General'}])[-6:]
            uploaded=api.post('/api/documents/upload',files={'file':('alice.txt',
                b'ALICE SMITH\nEDUCATION\nBachelor of Science from Example University.')},data={'category':'General'})
            assert uploaded.status_code==201,uploaded.text
            started=perf_counter()
            result=api.post('/api/documents/ask',json={'query':
                "Describe this candidate's education and give general interview preparation advice.",
                'dataset':'General','query_mode':'hybrid'}).json()
            print(json.dumps({'hybrid_with_document':result.get('answer'),
                'seconds':round(perf_counter()-started,2)},ensure_ascii=True),flush=True)
            assert result.get('claims') and '[S1]' in result['answer'],result
            assert result.get('general_guidance'),result


if __name__=='__main__':
    main()
