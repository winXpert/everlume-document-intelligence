"""Route knowledge questions without weakening the existing document validator."""
import logging
from . import config
from .assistant_service import respond


def chat_response(store, body, owner, metadata_response, want_answer=False):
    # History is bounded and scoped to the currently selected dataset. It is
    # conversational context only: it never becomes source evidence.
    history = [{'role':item.role,'content':item.content} for item in body.history
               if item.dataset == body.dataset][-6:]
    budget = min(6000,max(1000,(config.CONTEXT_SIZE-1200)*3))
    while history and sum(len(item['content']) for item in history)>budget:
        history.pop(0)
    mode = body.query_mode
    context = ''
    try:
        if mode == 'auto' or (history and mode in {'document','hybrid'}):
            decision = store.ollama.route(body.query, body.dataset, history)
            mode = decision.get('mode') if mode == 'auto' else mode
            context = decision.get('context', '')
            if mode not in {'general','document','hybrid'} or not isinstance(context,str) or len(context)>500:
                raise ValueError('Invalid routing decision')
        if mode == 'general':
            return {'query_mode':mode,'intent':'general_answer','answer':store.ollama.chat(body.query,history),
                    'answer_mode':'General knowledge · not based on uploaded documents',
                    'results':[],'sources':[],'claims':[],'follow_up_questions':[],
                    'message':'Answered using the local model’s general knowledge.', 'validation':{}}
        guidance = None
        if mode == 'hybrid':
            try:
                guidance = store.ollama.chat(body.query, (), guidance=True)
            except Exception:
                logging.exception('General guidance unavailable')
        # Generate guidance first so the document pipeline's final source and
        # permission checks happen immediately before the response is returned.
        # Keep the user's complete original wording and all explicit filters.
        # Context adds only a referent for conversational follow-up questions.
        result = respond(store,body,owner,metadata_response,want_answer,conversation_context=context,extractive=mode=='hybrid')
        result['query_mode'] = mode
        result['answer_mode'] = 'Verified document evidence'
        if mode == 'hybrid':
            if guidance:
                result['general_guidance'] = guidance
                result['answer'] = 'DOCUMENT FINDINGS\n' + result.get('answer','No verified findings.') + '\n\nGENERAL GUIDANCE (MODEL KNOWLEDGE)\n' + guidance
                result['answer_mode'] = 'Document evidence + separate general guidance'
            else:
                result['answer'] = result.get('answer','') + '\n\nGeneral guidance is currently unavailable.'
        return result
    except Exception:
        logging.exception('AI routing or general chat failed')
        return {'query_mode':mode if mode in {'general','document','hybrid'} else 'auto',
                'intent':'clarification','results':[],'sources':[],'claims':[],
                'answer':'The local AI could not complete this request. Please retry or select a mode explicitly.',
                'message':'Local AI unavailable or invalid routing response.','follow_up_questions':[], 'validation':{}}
