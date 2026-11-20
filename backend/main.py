import asyncio
import contextlib
import json
import logging
import secrets
import hashlib
import uuid
import time
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, Request, Response, Cookie, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import config
from .extraction import SUPPORTED
from .ollama_service import Ollama
from .store import Store
from .upload_queue import UploadQueue
from .search_constraints import is_document_question, parse_query
from .relevance_validation import verified_candidate_heading
from .assistant_service import respond as assistant_response
from .query_router import chat_response


def upload_name(file):
    name = (file.filename or '').replace('\\', '/').split('/')[-1]
    if not name or len(name) > 255 or Path(name).suffix.lower() not in SUPPORTED:
        raise HTTPException(415, 'Supported formats: PDF, DOCX, TXT, CSV, MD, JSON, LOG')
    return name


def write_upload(file, path):
    size = 0
    with path.open('wb') as output:
        while block := file.file.read(65536):
            size += len(block)
            if size > config.MAX_UPLOAD:
                raise HTTPException(413, 'File exceeds upload limit')
            output.write(block)


def create_app(store=None, tokens=None):
    credentials = tokens if tokens is not None else json.loads(config.TOKENS)
    local_mode = tokens is None and not credentials
    sessions = {}
    if not credentials:
        config.DATA.mkdir(parents=True, exist_ok=True)
        token_file = config.DATA / 'local-token.txt'
        if not token_file.exists():
            token_file.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        credentials = {token_file.read_text().strip(): 'local-user'}
    service = store

    @asynccontextmanager
    async def lifespan(app):
        nonlocal service
        if service is None:
            service = await asyncio.to_thread(Store, config.DATA, Ollama())
        app.state.store = service
        app.state.uploads = UploadQueue(service)
        stop_worker = asyncio.Event()

        async def indexing_worker():
            while not stop_worker.is_set():
                try:
                    worked = await asyncio.to_thread(app.state.uploads.process_next)
                except Exception:
                    logging.exception('Upload worker failed; durable queue retained')
                    worked = False
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop_worker.wait(), timeout=.05 if worked else .5)

        async def watch():
            while True:
                try:
                    failures = await asyncio.to_thread(service.reconcile)
                    if failures:
                        logging.warning('Reindex failed for %s documents; stale vectors disabled', len(failures))
                except Exception:
                    logging.exception('Index reconciliation failed')
                await asyncio.sleep(15)
        task = asyncio.create_task(watch())
        worker = asyncio.create_task(indexing_worker())
        yield
        # Finish the current file before releasing the application. Queued files
        # survive shutdown and will resume on the next start.
        stop_worker.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(asyncio.CancelledError):
            await worker

    app = FastAPI(title='Everlume Solutions Document Intelligence', lifespan=lifespan)

    def same_origin(request):
        origin = request.headers.get('origin')
        return (not origin or origin == str(request.base_url).rstrip('/')) and request.headers.get('sec-fetch-site') != 'cross-site'

    def user(request: Request, authorization: str = Header(default=''),
             session: str = Cookie(default='', alias='everlume_session')):
        if not authorization and session in sessions and sessions[session][1] > time.monotonic():
            if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not same_origin(request):
                raise HTTPException(403, 'Cross-origin request rejected')
            return sessions[session][0]
        token = authorization.removeprefix('Bearer ')
        for key, owner in credentials.items():
            if secrets.compare_digest(key, token):
                return owner
        raise HTTPException(401, 'A valid bearer token is required')

    @app.post('/api/session')
    def local_session(request: Request, response: Response):
        if (not local_mode or not request.client or request.client.host not in {'127.0.0.1', '::1'}
                or request.url.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or not same_origin(request) or request.headers.get('x-requested-with') != 'EverlumeWorkspace'):
            raise HTTPException(403, 'Automatic sessions are available only in the local workspace')
        session = request.cookies.get('everlume_session', '')
        for key, (_, expiry) in list(sessions.items()):
            if expiry <= time.monotonic():
                sessions.pop(key, None)
        if session not in sessions:
            session = secrets.token_urlsafe(32)
        # The credential never appears in JavaScript, HTML, URLs, or storage.
        sessions[session] = ('local-user', time.monotonic() + 8*60*60)
        response.set_cookie('everlume_session', session, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=8*60*60)
        response.headers['Cache-Control'] = 'no-store'
        return {'authenticated': True, 'mode': 'local', 'max_files': 200}

    @app.exception_handler(httpx.HTTPError)
    async def ollama_error(request, exc):
        return JSONResponse(status_code=503, content={'detail': 'Ollama unavailable or model missing. Check the local service and configured models.'})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={'detail': str(exc)})

    @app.get('/api/health')
    def health(owner=Depends(user)):
        return {'status': 'ready', 'generation_model': config.CHAT_MODEL, 'embedding_model': config.EMBED_MODEL}

    @app.get('/api/documents')
    def library(query: str = Query('', max_length=255), category: str = Query('', max_length=100),
                page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=50), owner=Depends(user)):
        return service.library(owner, query, category, page, page_size)

    @app.post('/api/documents/bulk-delete')
    def bulk_delete(body: DocumentIds, owner=Depends(user)):
        return {'results': [{'id': doc_id, 'deleted': service.delete(owner, doc_id)} for doc_id in dict.fromkeys(body.ids)]}

    @app.post('/api/documents/upload-jobs', status_code=201)
    def new_upload_job(body: UploadManifest, owner=Depends(user)):
        names = [name.replace('\\', '/').split('/')[-1] for name in body.filenames]
        return app.state.uploads.create(owner, names, body.category)

    @app.get('/api/documents/upload-jobs')
    def upload_jobs(owner=Depends(user)):
        return {'jobs': app.state.uploads.recent(owner)}

    @app.get('/api/documents/upload-jobs/{job_id}')
    def upload_job(job_id: str, owner=Depends(user)):
        job = app.state.uploads.get(owner, job_id)
        if not job:
            raise HTTPException(404, 'Upload job not found')
        return job

    @app.post('/api/documents/upload-jobs/{job_id}/cancel')
    def cancel_upload_job(job_id: str, owner=Depends(user)):
        job = app.state.uploads.cancel(owner, job_id)
        if not job:
            raise HTTPException(404, 'Upload job not found')
        return job

    @app.post('/api/documents/upload-jobs/{job_id}/items/{item_id}', status_code=202)
    def receive_upload(job_id: str, item_id: str, file: UploadFile = File(...), owner=Depends(user)):
        def writer(path, expected):
            name = upload_name(file)
            if name != expected:
                raise HTTPException(422, 'Filename does not match this upload slot')
            write_upload(file, path)
        try:
            item = app.state.uploads.receive(owner, job_id, item_id, writer)
        except (HTTPException, ValueError) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            app.state.uploads.fail_receipt(owner, job_id, item_id, detail)
            raise
        if not item:
            raise HTTPException(404, 'Upload item not found')
        return item

    @app.post('/api/documents/upload-jobs/{job_id}/items/{item_id}/retry', status_code=202)
    def retry_upload(job_id: str, item_id: str, owner=Depends(user)):
        item = app.state.uploads.retry(owner, job_id, item_id)
        if not item:
            raise HTTPException(404, 'Upload item not found')
        return item

    @app.post('/api/documents/upload', status_code=201)
    def upload(file: UploadFile = File(...), category: str = Form('General', max_length=100),
               source: str = Form('Upload', max_length=300), owner=Depends(user)):
        name = upload_name(file)
        doc_id = str(uuid.uuid4())
        path = service.files / doc_id
        try:
            write_upload(file, path)
            service.index(owner, doc_id, path, name, category, source)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {'id': doc_id, 'filename': name, 'status': 'indexed'}

    @app.post('/api/documents/upload/batch')
    def upload_batch(files: list[UploadFile] = File(..., min_length=1, max_length=20),
                     category: str = Form('General', max_length=100),
                     source: str = Form('Upload', max_length=300), owner=Depends(user)):
        results = []
        # Deliberately sequential: never load several inference batches at once.
        for file in files:
            try:
                results.append(upload(file, category, source, owner))
            except HTTPException as exc:
                results.append({'filename': file.filename, 'status': 'failed', 'error': exc.detail})
            except httpx.HTTPError:
                results.append({'filename': file.filename, 'status': 'failed', 'error': 'Ollama unavailable or model missing.'})
            except ValueError as exc:
                results.append({'filename': file.filename, 'status': 'failed', 'error': str(exc)})
            except Exception:
                logging.exception('Batch document indexing failed')
                results.append({'filename': file.filename, 'status': 'failed', 'error': 'Indexing failed. Check the server log.'})
        return {'results': results, 'indexed': sum(r['status'] == 'indexed' for r in results),
                'failed': sum(r['status'] == 'failed' for r in results)}

    @app.put('/api/documents/{doc_id}')
    def replace(doc_id: str, file: UploadFile = File(...), owner=Depends(user)):
        if not service.get(owner, doc_id):
            raise HTTPException(404, 'Document not found')
        name = upload_name(file)
        staged = service.root / (uuid.uuid4().hex + '.staging')
        try:
            write_upload(file, staged)
            if not service.replace(owner, doc_id, staged, name):
                raise HTTPException(404, 'Document not found')
        finally:
            staged.unlink(missing_ok=True)
        return {'id': doc_id, 'filename': name, 'status': 'indexed'}

    @app.get('/api/documents/datasets')
    def datasets(owner=Depends(user)):
        return {'datasets': service.datasets(owner)}

    def dataset_count_answer(body, owner, intent=None, selected_ids=None):
        query = body.query.strip().rstrip('?.!').casefold()
        assessment = intent is None and bool(re.search(r'\b(?:hire|hiring)\b', query) and re.search(r'\bboth\b', query))
        explicit = parse_query(query)
        assessment = assessment and not (explicit.numericConditions or explicit.excludedSkills or explicit.roleRequirements)
        if intent == 'dataset_list' or (intent is None and (assessment or (re.search(r'\b(?:candidate|resume|profile|applicant)s?\b', query) and re.search(r'\bnames?\b', query)))):
            remainder = re.sub(r'\b(?:please|show|list|give|me|the|all|what|are|is|who|candidate|candidates|resume|resumes|profile|profiles|applicant|applicants|name|names|in|from|under|dataset|category|folder|this|selected|current)\b', ' ', query)
            remainder = ' '.join(remainder.split())
            available = {item['name'].casefold(): item['name'] for item in service.datasets(owner)}
            if intent == 'dataset_list' or assessment or not remainder or remainder in available or (body.dataset and remainder == body.dataset.casefold()):
                dataset = body.dataset if intent else available.get(remainder, body.dataset)
                rows = service.rows(owner, dataset)
                if selected_ids is not None:
                    rows = [row for row in rows if row['id'] in selected_ids]
                candidates, lines = [], []
                for row in rows:
                    path = service.files / row['id']
                    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != row['digest']:
                        continue
                    pages = json.loads(row['pages'])
                    heading = next((line.strip() for line in pages[0].splitlines() if line.strip()), '') if pages else ''
                    # Only expose a plausible verbatim name heading; never infer a
                    # person's name from a filename or invent one through the LLM.
                    plausible = verified_candidate_heading(pages) is not None
                    name = heading if plausible else 'Candidate name could not be verified'
                    source_id = f'S{len(candidates) + 1}'
                    lines.append(f'{name} — {row["name"]} [{source_id}, page 1]')
                    candidates.append({'id':row['id'], 'filename':row['name'], 'category':row['category'],
                                       'page':1, 'text':heading or 'No name heading was found.', 'section':'Document heading',
                                       'source_id':source_id, 'candidate_name':heading if plausible else None,
                                       'metadata_only':True, 'highlight_query':'', 'reasons':['Listed because this document is in the requested dataset. This is not a skill qualification.'],
                                       'url':f'/api/documents/{row["id"]}/file#page=1'})
                scope = f'the {dataset} dataset' if dataset else 'your library'
                answer = '\n'.join(lines) or f'No indexed documents are available in {scope}.'
                if assessment and candidates:
                    answer = (f'I found {len(candidates)} indexed resumes in {scope}:\n' + answer +
                              '\n\nThe resumes identify these candidates, but do not establish whether both meet your hiring needs. '
                              'What role are you hiring for, and what are the required responsibilities, skills, and experience? '
                              'I can then compare each resume against those requirements and cite the supporting evidence.')
                return {'intent':'hiring_review' if assessment else 'dataset_names', 'dataset':dataset, 'count':len(candidates), 'answer':answer,
                        'message':f'{len(candidates)} indexed documents listed from {scope}.',
                        'results':candidates, 'sources':candidates, 'follow_up_questions':[],
                        'validation':{'dataset':dataset, 'count_basis':'Indexed files, not unique people'},
                        'answer_mode':'Verified document headings; unverified names explicitly labelled'}
        # Library questions count indexed files, not skill matches or candidates.
        match = re.fullmatch(r'(?:please\s+)?(?:how many|count(?: of)?|total(?: number of)?)\s+'
                             r'(?:resumes?|cvs?|documents?|files?)\s*'
                             r'(?:(?:are|is)\s+)?(?:(?:present|available|uploaded|indexed|there)\s*)?'
                             r'(?:(?:in|from|under)\s+(?:the\s+)?(.+?))?', query)
        if not match and intent != 'dataset_count':
            return None
        named = match[1] if match and intent is None else None
        dataset = body.dataset
        if named:
            named = re.sub(r'\s+(?:dataset|category|folder)$', '', named).strip()
            if named not in {'this', 'selected', 'current', 'this dataset', 'selected dataset', 'current dataset'}:
                available = {item['name'].casefold(): item['name'] for item in service.datasets(owner)}
                dataset = available.get(named, named)
        counts = service.datasets(owner)
        count = sum(item['document_count'] for item in counts
                    if dataset is None or item['name'].casefold() == dataset.casefold())
        scope = f'the {dataset} dataset' if dataset is not None else 'your library'
        answer = f'There {"is" if count == 1 else "are"} {count} indexed document{"" if count == 1 else "s"} in {scope}.'
        return {'intent': 'dataset_count', 'count': count, 'dataset': dataset,
                'answer': answer, 'message': answer, 'results': [], 'sources': [], 'claims': [],
                'follow_up_questions': [], 'answer_mode': 'Verified library metadata',
                'validation': {'dataset': dataset, 'count_basis': 'Indexed files; includes separately uploaded duplicate files'}}

    @app.post('/api/documents/search')
    def search(body: Search, owner=Depends(user)):
        if body.query_mode != 'document' or body.history:
            return chat_response(service,body,owner,dataset_count_answer)
        if callable(getattr(type(service.ollama), 'understand', None)):
            return assistant_response(service,body,owner,dataset_count_answer)
        count_answer = dataset_count_answer(body, owner)
        if count_answer is not None:
            return count_answer
        if is_document_question(body.query, body.dataset):
            answer = ask(body, owner)
            answer['results'] = answer['sources']
            return answer
        results = service.search(owner, body.query, body.mode, body.limit, dataset=body.dataset, skill_match=body.skill_match)
        details = getattr(results, 'details', {})
        return {'results': results, 'message': '' if results else details.get('message') or 'No matching information was found.',
                'validation': details,
                'score_label': 'Retrieval relevance; not a probability'}

    @app.get('/api/documents/recommendations')
    def recommendations(query: str = '', dataset: str | None = Query(None, min_length=1, max_length=100, pattern=r'\S'), skill_match: Literal['any','all'] = 'any', owner=Depends(user)):
        if not query.strip() or len(query) > 1000:
            raise HTTPException(422, 'Provide a query between 1 and 1000 characters')
        return search(Search(query=query, dataset=dataset, skill_match=skill_match), owner)

    @app.get('/api/documents/suggestions')
    def suggestions(query: str = '', dataset: str | None = Query(None, min_length=1, max_length=100, pattern=r'\S'), owner=Depends(user)):
        if len(query) > 1000:
            raise HTTPException(422, 'Query too long')
        return {'suggestions': [r['name'] for r in service.rows(owner, dataset) if query.casefold() in r['name'].casefold()][:8]}

    @app.post('/api/documents/ask')
    def ask(body: Search, owner=Depends(user)):
        if body.query_mode != 'document' or body.history:
            return chat_response(service,body,owner,dataset_count_answer,want_answer=True)
        if callable(getattr(type(service.ollama), 'understand', None)):
            return assistant_response(service,body,owner,dataset_count_answer,want_answer=True)
        count_answer = dataset_count_answer(body, owner)
        if count_answer is not None:
            return count_answer
        general_question = is_document_question(body.query, body.dataset)
        selection = general_question and bool(re.search(r'\b(?:select|choose|pick|suggest|recommend)\b', body.query, re.I))
        results = service.search(owner, body.query, body.mode, body.limit, dataset=body.dataset,
                                 skill_match=body.skill_match, enrich=not general_question, question=general_question)
        budget = max(500, config.CONTEXT_SIZE - 1400)
        evidence = []
        for i, result in enumerate(results):
            # Conservative one-character-per-token estimate keeps even non-English
            # evidence bounded; reserve space for instructions, query and output.
            allowance = budget if not general_question else min(budget, max(160, (config.CONTEXT_SIZE - 1400) // max(1, min(len(results), config.RETRIEVAL_LIMIT))))
            passage = result['text']
            if general_question:
                # Center the excerpt on the requested content, retaining its page.
                from .keyword_matcher import KeywordMatcher
                matcher = KeywordMatcher(body.query)
                question_filler = {'does','have','has','these','those','their','they','candidate','candidates','resume','resumes','uploaded','dataset','details'}
                hits = [match.start() for term, pattern in zip(matcher.terms, matcher.patterns)
                        if term not in question_filler for match in [pattern.search(passage)] if match]
                start = max(0, min(hits) - 120) if hits else 0
                start = min(start, max(0, len(passage) - allowance))
                passage = passage[start:]
            text = passage[:allowance]
            if len(text) < 12:
                break
            evidence.append({'source_id': f'S{i+1}', 'text': text})
            budget -= len(text)
        claims = []
        if evidence and not selection:
            answer_query = (body.query if general_question else
                            'Select evidence for any one requested skill or related experience; do not imply all skills are present. Query: ' + body.query
                            if body.skill_match == 'any' else body.query)
            raw = service.ollama.answer(answer_query, evidence)
            try:
                proposed = json.loads(raw).get('claims', [])
                for claim in proposed[:8]:
                    match = next((s for s in evidence if s['source_id'] == claim.get('source_id')), None)
                    quote = claim.get('quote', '')
                    if match and isinstance(quote, str) and len(quote.strip()) >= 12 and quote in match['text'] and not any(c['text'] == quote for c in claims):
                        # Display verified excerpts as the answer. Free-form model paraphrases
                        # cannot be mechanically proven entailed, so never display them.
                        claims.append({'text': quote, 'source_id': match['source_id']})
            except (ValueError, TypeError, AttributeError):
                pass
        if general_question and not selection and not claims:
            # A small local model can return an empty selection even when an
            # explicitly requested topic is present. Return labelled verbatim
            # evidence instead of inventing a paraphrase or a false empty answer.
            from .keyword_matcher import KeywordMatcher
            matcher = KeywordMatcher(body.query)
            filler = {'does','have','has','had','these','those','their','they','them','candidate','candidates',
                      'resume','resumes','uploaded','dataset','tell','explain','describe','summarize','summarise','compare','details'}
            patterns = [pattern for term, pattern in zip(matcher.terms, matcher.patterns) if term not in filler]
            for source in evidence:
                positions = [match.start() for pattern in patterns for match in [pattern.search(source['text'])] if match]
                if not positions:
                    continue
                start = source['text'].rfind('\n', 0, min(positions)) + 1
                quote = source['text'][start:start + 400].strip()
                if len(quote) >= 12:
                    claims.append({'text':quote, 'source_id':source['source_id']})
                if len(claims) >= 3:
                    break
        if body.dataset is not None and any(not (row := service.get(owner, result['id'])) or row['category'] != body.dataset for result in results):
            results = []
            claims = []
            results_message = 'Documents changed during answer generation. Please search the selected dataset again.'
        else:
            results_message = getattr(results, 'details', {}).get('message', '')
        sources = [{**r, 'source_id': f'S{i+1}'} for i, r in enumerate(results)]
        answer = '\n'.join(f"{c['text']} [{c['source_id']}]" for c in claims) or 'No matching information was found.'
        if selection and sources:
            recommendations = []
            for source in sources:
                row = service.get(owner, source['id'])
                if not row:
                    continue
                name = verified_candidate_heading(json.loads(row['pages']))
                label = name or f'{source["filename"]} (candidate name could not be verified)'
                # Name, rank and cited passage come from validated backend results.
                recommendations.append(f'Suggested candidate: {label}.\n'
                                       f'Why: the supporting evidence for this candidate includes: '
                                       f'“{source["text"][:600]}” [{source["source_id"]}, page {source["page"]}]')
                source['candidate_name'] = name
            answer = '\n\n'.join(recommendations) + '\n\nRanking reflects the uploaded evidence. Share specific role requirements for a more precise comparison.'
        return {'answer': answer,
                'validation': getattr(results, 'details', {}),
                'message': results_message,
                'claims': claims, 'sources': sources,
                'follow_up_questions': [f"What does {r['filename']} say about {body.query.rstrip('?.!')}?" for r in results[:3]],
                'answer_mode': 'Verified document excerpts' if general_question else 'AI-selected, verbatim verified excerpts'}

    @app.get('/api/documents/{doc_id}')
    def details(doc_id: str, owner=Depends(user)):
        row = service.get(owner, doc_id)
        if not row:
            raise HTTPException(404, 'Document not found')
        path = service.files / doc_id
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != row['digest']:
            raise HTTPException(409, 'Document changed; waiting for reindexing')
        return {k: json.loads(v) if k == 'pages' else v for k, v in row.items() if k not in {'owner', 'chunks', 'digest'}}

    @app.patch('/api/documents/{doc_id}')
    def metadata(doc_id: str, body: DocumentMetadata, owner=Depends(user)):
        if '/' in body.name or '\\' in body.name or body.name in {'.', '..'}:
            raise HTTPException(422, 'Provide a filename without a path')
        if not service.update_metadata(owner, doc_id, body.name, body.category):
            raise HTTPException(404, 'Document not found')
        return {'id': doc_id, 'name': body.name, 'category': body.category}

    @app.get('/api/documents/{doc_id}/file')
    def original(doc_id: str, owner=Depends(user)):
        row = service.get(owner, doc_id)
        if not row or not (service.files / doc_id).exists():
            raise HTTPException(404, 'Document not found')
        return FileResponse(service.files / doc_id, filename=row['name'], headers={'X-Content-Type-Options': 'nosniff'})

    @app.delete('/api/documents/{doc_id}')
    def delete(doc_id: str, owner=Depends(user)):
        if not service.delete(owner, doc_id):
            raise HTTPException(404, 'Document not found')
        return {'deleted': True}

    app.mount('/', StaticFiles(directory=Path(__file__).parent.parent / 'frontend', html=True), name='frontend')
    return app


class ChatTurn(BaseModel):
    role: Literal['user','assistant']
    content: str = Field(min_length=1, max_length=1500)
    dataset: str | None = Field(default=None, max_length=100)


class Search(BaseModel):
    query: str = Field(min_length=1, max_length=1000, pattern=r'\S')
    mode: Literal['keyword', 'semantic', 'hybrid'] = 'hybrid'
    limit: int | None = Field(default=None, ge=1, le=12)
    dataset: str | None = Field(default=None, min_length=1, max_length=100, pattern=r'\S')
    skill_match: Literal['any','all'] = 'any'
    query_mode: Literal['auto','general','document','hybrid'] = 'document'
    history: list[ChatTurn] = Field(default_factory=list, max_length=6)


class UploadManifest(BaseModel):
    filenames: list[str] = Field(min_length=1, max_length=200)
    category: str = Field(default='General', min_length=1, max_length=100)

    @field_validator('filenames')
    @classmethod
    def valid_names(cls, values):
        if any(not name.strip() or len(name) > 255 for name in values):
            raise ValueError('Each filename must contain 1–255 characters')
        return values


class DocumentIds(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


class DocumentMetadata(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r'\S')
    category: str = Field(min_length=1, max_length=100, pattern=r'\S')


app = create_app()
