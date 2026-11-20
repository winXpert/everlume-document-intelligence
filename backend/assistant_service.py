"""Shared intent -> scoped retrieval -> grounded answer pipeline for Search and Ask."""
import hashlib
import json
import logging
import re
from time import perf_counter

from . import config
from .query_understanding import understand
from .relevance_validation import verified_candidate_heading


def supported_surface(claim):
    """A small LLM must not invent quantities or unsupported evaluation scales."""
    proof = ' '.join(item['quote'] for item in claim['evidence'])
    if not set(re.findall(r'\d+(?:\.\d+)?',claim['text'])) <= set(re.findall(r'\d+(?:\.\d+)?',proof)):
        return False
    evaluations = re.findall(r'\b(?:better|best|worse|worst|higher|lower|stronger|weaker|superior|inferior|'
                             r'more|less|ideal|perfect)\b',claim['text'],re.I)
    return all(value.casefold() in proof.casefold() for value in evaluations)


def respond(store, body, owner, metadata_response, want_answer=False, conversation_context='', extractive=False):
    started = perf_counter()
    try:
        understood = understand(store.ollama, body.query, body.dataset, body.skill_match, conversation_context)
    except Exception:
        logging.exception('Structured query understanding failed')
        return {'results':[], 'sources':[], 'answer':'I could not reliably interpret this request. Please try again or clarify what you want to know.',
                'message':'Local query understanding is unavailable or returned an invalid plan.',
                'follow_up_questions':[], 'validation':{'stage':'query_understanding','dataset':body.dataset},
                'intent':'clarification'}
    plan, intent = understood.plan, understood.intent
    # A conversational referent can guide retrieval and phrasing, never create
    # a mandatory qualification or relax an explicit current-query condition.
    if conversation_context:
        understood.retrieval_query += ' ' + conversation_context
    answer_query = body.query + ('\nConversation topic: '+conversation_context if conversation_context else '')
    has_filters = bool(plan.requiredGroups or plan.numericConditions or plan.excludedSkills or plan.roleRequirements)
    if plan.errors:
        return {'results':[], 'sources':[], 'answer':' '.join(plan.errors), 'message':' '.join(plan.errors),
                'validation':{'criteria':plan.public(),'dataset':body.dataset}, 'follow_up_questions':[], 'intent':intent}
    if intent in {'dataset_count','dataset_list'} and not has_filters:
        response = metadata_response(body, owner, intent=intent)
        response['validation']['understanding'] = {'intent':intent,'retrieval_query':understood.retrieval_query}
        return response
    if intent == 'clarification':
        return {'results':[], 'sources':[], 'answer':'What would you like to find out from the selected documents?',
                'message':'Please provide the question or criteria you want assessed.', 'intent':intent,
                'validation':{'criteria':plan.public(),'dataset':body.dataset}, 'follow_up_questions':[]}
    question = intent in {'document_question','comparison'} or not has_filters
    results = store.search(owner, body.query, body.mode, body.limit, dataset=body.dataset,
                           skill_match=body.skill_match, enrich=False, question=question,
                           search_plan=plan, retrieval_hint=understood.retrieval_query)
    details = getattr(results, 'details', {})
    details['understanding'] = {'intent':intent,'retrieval_query':understood.retrieval_query,
                              'subjects':[term for group in plan.requiredGroups for term in group],
                              'needs_criteria':understood.needs_criteria}
    base = {'results':results, 'sources':[], 'intent':intent, 'validation':details,
            'message':details.get('message',''), 'follow_up_questions':[],
            'score_label':'Retrieval relevance; not candidate quality'}
    if intent == 'dataset_count':
        base.update(count=len(results), answer=f'{len(results)} unique documents satisfy the requested criteria in the selected dataset.')
        return base
    if not results:
        base.update(answer=base['message'] or 'No matching information was found.')
        return base
    if intent == 'dataset_list':
        response = metadata_response(body,owner,intent='dataset_list',selected_ids={item['id'] for item in results})
        response['validation'].update(details)
        return response
    if intent == 'candidate_search' and not want_answer:
        base['sources'] = [{**item,'source_id':f'S{index+1}'} for index,item in enumerate(results)]
        base['results'] = base['sources']
        shown = base['sources'][:config.RETRIEVAL_LIMIT]
        base['answer'] = f'Found {len(results)} matching documents in the selected dataset.\n' + '\n'.join(
            f"{item.get('candidate_name') or item['filename']} [{item['source_id']}]" for item in shown)
        details['answer_cited_documents'] = len(shown)
        details['total_matching_documents'] = len(results)
        base['answer_mode'] = 'Verified matching-document summary'
        details['elapsed_seconds'] = round(perf_counter() - started,3)
        return base

    # Evidence comes exclusively from revalidated, owner-scoped selected documents.
    budget = max(500, config.CONTEXT_SIZE - 1600)
    covered = min(len(results), max(1, config.RETRIEVAL_LIMIT))
    allowance = max(120, budget // covered)
    evidence, sources = [], []
    for result in results[:covered]:
        row = store.get(owner, result['id'])
        if not row or (body.dataset is not None and row['category'] != body.dataset):
            continue
        path = store.files / row['id']
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != row['digest']:
            continue
        pages = json.loads(row['pages'])
        name = verified_candidate_heading(pages)
        passage = result['text']
        # Rank the excerpt using the interpreted answer topic, not question filler.
        from .keyword_matcher import KeywordMatcher
        matcher = KeywordMatcher(understood.retrieval_query)
        offsets = [match.start() for pattern in matcher.patterns for match in [pattern.search(passage)] if match]
        start = max(0, min(offsets)-100) if offsets else 0
        start = min(start,max(0,len(passage)-allowance))
        heading = (name + '\n') if name else ''
        text = heading + passage[start:start + max(60,allowance-len(heading))]
        source_id = f'S{len(evidence)+1}'
        evidence.append({'source_id':source_id,'text':text})
        sources.append({**result,'source_id':source_id,'candidate_name':name,
                        'evidence':[{'requirement':'Document identity','page':1,'text':name}] if name else [],
                        '_digest':row['digest']})
    source_lookup = {source['id']:source for source in sources}
    base['sources'] = [{**item,'source_id':source_lookup.get(item['id'],{}).get('source_id'),
                        'candidate_name':source_lookup.get(item['id'],{}).get('candidate_name'),
                        'evidence':item.get('evidence',[]) + source_lookup.get(item['id'],{}).get('evidence',[])} for item in results]
    details['answer_context_count'] = len(evidence)
    details['total_matching_documents'] = len(results)
    claims = []
    if intent == 'dataset_list':
        base['answer'] = '\n'.join(f"{source['candidate_name'] or 'Name could not be verified'} — {source['filename']} [{source['source_id']}]" for source in sources)
    elif evidence:
        try:
            proposal = store.ollama.compose(answer_query,evidence,intent,understood.needs_criteria)
            lookup = {source['source_id']:source['text'] for source in evidence}
            candidates = []
            for claim in proposal.get('claims',[])[:6]:
                if not isinstance(claim,dict) or not isinstance(claim.get('text'),str) or not 1 <= len(claim['text']) <= 600:
                    continue
                proof = claim.get('evidence')
                if not isinstance(proof,list) or not 1 <= len(proof) <= 3:
                    continue
                if all(isinstance(item,dict) and isinstance(item.get('quote'),str)
                       and 12 <= len(item['quote'].strip()) <= 1000
                       and item['quote'] in lookup.get(item.get('source_id'),'') for item in proof):
                    candidate = {'text':claim['text'], 'evidence':proof}
                    if not supported_surface(candidate):
                        continue
                    candidates.append(candidate)
                    if len(json.dumps(candidates)) > max(500,config.CONTEXT_SIZE-2000):
                        candidates.pop()
                        break
            if candidates:
                verified = store.ollama.verify(answer_query,candidates,evidence)
                approved = verified.get('supported',[]) if isinstance(verified,dict) else []
                claims = [claim for index,claim in enumerate(candidates) if type(index) is int and
                          any(type(value) is int and value == index for value in approved)]
            if extractive:
                # In mixed-knowledge mode keep the document section strictly
                # extractive: a small model can otherwise attach valid quotes
                # to general advice and fool its own entailment verifier.
                unique = {}
                for claim in claims:
                    for item in claim['evidence']:
                        unique[(item['source_id'],item['quote'])] = {'text':item['quote'],'evidence':[item]}
                claims = list(unique.values())
            answer = '\n'.join(claim['text'] + ' ' + ' '.join(f"[{source_id}]" for source_id in
                              dict.fromkeys(item['source_id'] for item in claim['evidence'])) for claim in claims)
            needs_criteria = understood.needs_criteria or proposal.get('needs_clarification') is True or (intent == 'comparison' and not claims)
            if needs_criteria:
                answer += '\n\nWhat requirements or criteria should I use for this assessment?'
            if intent == 'candidate_recommendation' and sources:
                chosen = sources[0]
                label = chosen['candidate_name'] or chosen['filename']
                answer = f"Top retrieved match: {label} [{chosen['source_id']}].\n" + answer
            base['answer'] = answer.strip() or 'The selected documents do not provide a verified answer to this question.'
        except Exception:
            logging.exception('Grounded answer generation failed')
            base['answer'] = 'I found relevant documents, but could not verify an answer. Please try again.'
    else:
        base['answer'] = 'No matching information was found.'
    # Never expose a source moved/deleted/changed during model inference.
    for source in sources:
        current = store.get(owner,source['id'])
        path = store.files/source['id']
        if (not current or current['digest'] != source['_digest'] or not path.exists()
                or hashlib.sha256(path.read_bytes()).hexdigest() != source['_digest']
                or (body.dataset is not None and current['category'] != body.dataset)):
            base.update(results=[],sources=[],claims=[],answer='Documents changed while preparing the answer. Please search again.')
            return base
    for result in results:
        current = store.get(owner,result['id'])
        path = store.files/result['id']
        if (not current or current['digest'] != getattr(results,'versions',{}).get(result['id'])
                or not path.exists()
                or (body.dataset is not None and current['category'] != body.dataset)):
            base.update(results=[],sources=[],claims=[],answer='Documents changed while preparing the answer. Please search again.')
            return base
        stat = path.stat()
        stamp = (stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,current['digest'])
        if store._source_checks.get(result['id']) != stamp and hashlib.sha256(path.read_bytes()).hexdigest() != current['digest']:
            base.update(results=[],sources=[],claims=[],answer='Documents changed while preparing the answer. Please search again.')
            return base
    base['claims'] = claims
    for claim in claims:
        claim['source_id'] = claim['evidence'][0]['source_id']
    details['answer_cited_documents'] = len({item['source_id'] for claim in claims for item in claim['evidence']})
    base['results'] = base['sources']
    base['answer_mode'] = 'Model-composed answer; exact citations and independent entailment check'
    details['elapsed_seconds'] = round(perf_counter()-started,3)
    return base
