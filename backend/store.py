import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .extraction import extract, chunks
from .keyword_matcher import KeywordMatcher, CONTEXT_TERMS, bounded
from .search_constraints import parse_query, compare, apply_matching_policy, is_dataset_selection
from .relevance_validation import validate, deduplicate, evidence, verified_candidate_heading
import re


class SearchResults(list):
    def __init__(self, values=(), **details):
        super().__init__(values)
        self.details = details


class Store:
    def __init__(self, root, ollama):
        import chromadb
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.files = self.root / 'files'
        self.files.mkdir(exist_ok=True)
        self.ollama = ollama
        self.lock = threading.RLock()
        self._source_checks = {}
        self._query_embeddings = OrderedDict()
        self.db = sqlite3.connect(self.root / 'metadata.db', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, owner TEXT, name TEXT, category TEXT, uploaded TEXT, source TEXT, digest TEXT, pages TEXT, chunks TEXT)')
        from chromadb.config import Settings
        client = chromadb.PersistentClient(path=str(self.root / 'chroma'), settings=Settings(anonymized_telemetry=False))
        collection_name = 'documents-' + hashlib.sha256((config.EMBED_MODEL + config.DOCUMENT_PREFIX + config.QUERY_PREFIX).encode()).hexdigest()[:12]
        self.vector = client.get_or_create_collection(collection_name, metadata={'hnsw:space': 'cosine'}, embedding_function=None)

    def rows(self, owner, dataset=None):
        with self.lock:
            sql, params = 'SELECT * FROM documents WHERE owner=?', [owner]
            if dataset is not None:
                sql += ' AND category=?'
                params.append(dataset)
            return [dict(r) for r in self.db.execute(sql, params)]

    def datasets(self, owner):
        with self.lock:
            return [dict(row) for row in self.db.execute(
                'SELECT category AS name,count(*) AS document_count FROM documents WHERE owner=? GROUP BY category ORDER BY category COLLATE NOCASE', (owner,))]

    def get(self, owner, doc_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM documents WHERE owner=? AND id=?', (owner, doc_id)).fetchone()
            return dict(row) if row else None

    def library(self, owner, query='', category='', page=1, page_size=25):
        where, params = 'owner=?', [owner]
        if query:
            where += ' AND instr(lower(name),lower(?))>0'
            params.append(query)
        if category:
            where += ' AND category=?'
            params.append(category)
        with self.lock:
            total = self.db.execute('SELECT count(*) FROM documents WHERE ' + where, params).fetchone()[0]
            overall = self.db.execute('SELECT count(*) FROM documents WHERE owner=?', (owner,)).fetchone()[0]
            categories = [r[0] for r in self.db.execute('SELECT DISTINCT category FROM documents WHERE owner=? ORDER BY category', (owner,))]
            rows = self.db.execute('SELECT id,name,category,uploaded,source FROM documents WHERE ' + where +
                                   ' ORDER BY uploaded DESC,id LIMIT ? OFFSET ?', params + [page_size, (page-1)*page_size]).fetchall()
            return {'documents': [dict(r) for r in rows], 'total': total, 'overall_total': overall,
                    'page': page, 'page_size': page_size, 'categories': categories}

    def update_metadata(self, owner, doc_id, name, category):
        with self.lock:
            row = self.get(owner, doc_id)
            if not row:
                return False
            if Path(name).suffix.lower() != Path(row['name']).suffix.lower():
                raise ValueError('Keep the original file extension when renaming')
            self.db.execute('UPDATE documents SET name=?,category=? WHERE id=? AND owner=?', (name, category, doc_id, owner))
            self.db.commit()
            return True

    def index(self, owner, doc_id, path, name, category, source, uploaded=None):
        with self.lock:
            return self._index(owner, doc_id, path, name, category, source, uploaded)

    def _index(self, owner, doc_id, path, name, category, source, uploaded=None):
        try:
            pages = extract(path, Path(name).suffix.lower())
        except Exception as exc:
            raise ValueError('Unable to extract this document. Check its format, encoding, and encryption.') from exc
        parts = chunks(pages)
        if not parts:
            raise ValueError('No extractable text. Scanned PDFs require OCR before upload.')
        if len(parts) > config.MAX_CHUNKS:
            raise ValueError('Document exceeds configured chunk limit')
        embeddings = self.ollama.embed([config.DOCUMENT_PREFIX + p['text'] for p in parts])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        # Retrieval shares this lock, so partially replaced chunks are never visible.
        with self.lock:
            version = uuid.uuid4().hex
            new_ids = [f'{doc_id}:{digest}:{i}:{version}' for i in range(len(parts))]
            for i, part in enumerate(parts):
                part['vector_id'] = new_ids[i]
            try:
                for start in range(0, len(parts), 100):
                    batch = parts[start:start + 100]
                    self.vector.add(ids=new_ids[start:start + 100],
                                    embeddings=embeddings[start:start + 100],
                                    metadatas=[{'owner': owner, 'doc_id': doc_id, 'page': p['page'], 'version': version} for p in batch])
                self.db.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?,?,?)',
                                (doc_id, owner, name, category, uploaded or datetime.now(timezone.utc).isoformat(),
                                 source, digest, json.dumps(pages), json.dumps(parts)))
                self.db.commit()
            except Exception:
                self.db.rollback()
                self.vector.delete(ids=new_ids)
                raise
            try:
                self.vector.delete(where={'$and': [{'doc_id': doc_id}, {'version': {'$ne': version}}]})
            except Exception:
                logging.exception('Old vector cleanup deferred for %s', doc_id)

    def replace(self, owner, doc_id, staged, name):
        with self.lock:
            row = self.get(owner, doc_id)
            if not row:
                return False
            original = self.files / doc_id
            backup = self.root / (doc_id + '.backup')
            original.replace(backup)
            try:
                staged.replace(original)
                self.index(owner, doc_id, original, name, row['category'], row['source'], row['uploaded'])
            except Exception:
                original.unlink(missing_ok=True)
                backup.replace(original)
                raise
            backup.unlink(missing_ok=True)
            return True

    def delete(self, owner, doc_id):
        with self.lock:
            row = self.get(owner, doc_id)
            if not row:
                return False
            self.vector.delete(where={'doc_id': doc_id})
            self.db.execute('DELETE FROM documents WHERE id=? AND owner=?', (doc_id, owner))
            self.db.commit()
            (self.files / doc_id).unlink(missing_ok=True)
            self._source_checks.pop(doc_id, None)
            return True

    def reconcile(self):
        errors = []
        with self.lock:
            all_rows = [dict(r) for r in self.db.execute('SELECT * FROM documents')]
        for row in all_rows:
            path = self.files / row['id']
            with self.lock:
                row = self.get(row['owner'], row['id'])
                if not row:
                    continue
                try:
                    if not path.exists():
                        self.delete(row['owner'], row['id'])
                    elif hashlib.sha256(path.read_bytes()).hexdigest() != row['digest'] or not self.vector.get(where={'doc_id': row['id']}, limit=1)['ids']:
                        self.index(row['owner'], row['id'], path, row['name'], row['category'], row['source'], row['uploaded'])
                except Exception:
                    errors.append(row['id'])
                    # Changed files must not retain searchable stale evidence.
                    self.vector.delete(where={'doc_id': row['id']})
        return errors

    def search(self, owner, query, mode, limit=None, dataset=None, skill_match='any', enrich=None, question=False,
               search_plan=None, retrieval_hint=None):
        enrich = config.SEARCH_AI_ENRICHMENT if enrich is None else enrich
        plan = search_plan or apply_matching_policy(parse_query(query), skill_match)
        if question and search_plan is None:
            # Question words describe the requested answer, not mandatory skills.
            plan.requiredGroups = []
            plan.searchQuery = query
            plan.intent = 'document_question'
            if dataset and is_dataset_selection(query, dataset):
                plan.errors = [error for error in plan.errors if error != 'Provide a topic, skill, role, or measurable requirement to search for.']
        details = {'criteria': plan.public(), 'rejections': {}, 'qualified_count': 0,
                   'duplicates_removed': 0, 'dataset': dataset, 'message': ''}
        if plan.errors:
            return SearchResults(message=' '.join(plan.errors), criteria=plan.public())
        rows = self.rows(owner, dataset)
        if not rows:
            if dataset is not None:
                details['message'] = f'No indexed documents are available in dataset “{dataset}”. Other datasets were not searched.'
            return SearchResults(**details)
        # Model interpretation assists retrieval, never changes explicit conditions.
        if enrich and hasattr(self.ollama, 'interpret'):
            try:
                interpretation = self.ollama.interpret(query)
                details['language_interpretation'] = interpretation if isinstance(interpretation, dict) else {}
                plan.interpretation = 'ollama-assisted; deterministic constraints enforced'
            except Exception:
                logging.warning('Query interpretation unavailable; using explicit query constraints')
                plan.interpretation = 'deterministic fallback; language model unavailable'
        details['criteria'] = plan.public()
        retrieval_query = re.sub(r'\bengineers\b', 'engineer', plan.searchQuery) or 'professional experience'
        if retrieval_hint:
            retrieval_query = retrieval_hint
        if question and dataset and is_dataset_selection(query, dataset):
            # The dropdown supplies the domain for an otherwise context-free request.
            # It assists ranking, never proves a candidate's qualifications.
            retrieval_query = dataset
        matcher = KeywordMatcher(retrieval_query)
        if question:
            # Keep question phrasing for embeddings, but remove conversational
            # filler from literal passage scoring ("have" is not answer evidence).
            filler = {'does', 'have', 'has', 'had', 'these', 'those', 'their', 'they', 'them',
                      'candidate', 'candidates', 'resume', 'resumes', 'uploaded', 'dataset',
                      'tell', 'explain', 'describe', 'summarize', 'summarise', 'compare', 'details'}
            pairs = [(term, pattern) for term, pattern in zip(matcher.terms, matcher.patterns) if term not in filler]
            matcher.terms = [term for term, _ in pairs]
            matcher.patterns = [pattern for _, pattern in pairs]
        threshold = config.semantic_threshold(matcher.intent)
        context_threshold = config.semantic_threshold(matcher.intent, contextual=True)
        vectors = {}
        if mode != 'keyword':
            # Cache only query vectors, never document results or permissions.
            key = (id(self.ollama), config.EMBED_MODEL, config.QUERY_PREFIX, matcher.semantic_query)
            with self.lock:
                embedding = self._query_embeddings.get(key)
                if embedding is not None:
                    self._query_embeddings.move_to_end(key)
            if embedding is None:
                embedding = self.ollama.embed([config.QUERY_PREFIX + matcher.semantic_query])[0]
                with self.lock:
                    self._query_embeddings[key] = embedding
                    while len(self._query_embeddings) > 128:
                        self._query_embeddings.popitem(last=False)
        with self.lock:
            rows = self.rows(owner, dataset)
            if mode != 'keyword' and rows:
                pool_size = sum(len(json.loads(row['chunks'])) for row in rows)
                scope = {'owner': owner} if dataset is None else {'$and': [{'owner': owner}, {'doc_id': {'$in': [row['id'] for row in rows]}}]}
                # Score every scoped chunk in bounded batches. A nearest-neighbor
                # cutoff can otherwise hide qualifying documents in larger libraries.
                import numpy as np
                query_vector = np.asarray(embedding, dtype=np.float32)
                query_norm = np.linalg.norm(query_vector)
                for offset in range(0, pool_size, 512):
                    batch = self.vector.get(where=scope, limit=512, offset=offset, include=['embeddings'])
                    if not batch['ids']:
                        break
                    matrix = np.asarray(batch['embeddings'], dtype=np.float32)
                    denominator = np.linalg.norm(matrix, axis=1) * query_norm
                    scores = np.divide(matrix @ query_vector, denominator,
                                       out=np.zeros(len(matrix)), where=denominator != 0)
                    vectors.update((key, float(np.clip(score, 0., 1.))) for key, score in zip(batch['ids'], scores))
            results = []
            valid_rows = {}
            for row in rows:
                # Check source version before using stored excerpts.
                path = self.files / row['id']
                if not path.exists():
                    continue
                stat = path.stat()
                stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, row['digest'])
                cached = self._source_checks.get(row['id'])
                if cached != stamp:
                    if hashlib.sha256(path.read_bytes()).hexdigest() != row['digest']:
                        continue
                    self._source_checks[row['id']] = stamp
                pages = json.loads(row['pages'])
                verified, failures, missing_preferred = validate(plan, pages, allow_related=mode != 'keyword' and skill_match == 'any')
                if failures:
                    for failure in failures:
                        details['rejections'][failure] = details['rejections'].get(failure, 0) + 1
                    continue
                row['_pages'] = pages
                valid_rows[row['id']] = row
                requested = list(dict.fromkeys(term for branch in plan.requiredGroups for term in branch))
                canonical = lambda term: re.sub(r'\b(engineer|developer|architect|manager|analyst|scientist)s\b', r'\1',term.casefold())
                direct = {canonical(proof['requirement']) for proof in verified if proof.get('match_kind') != 'related'}
                matched_skills = [term for term in requested if canonical(term) in direct]
                missing_skills = [term for term in requested if term not in matched_skills]
                related = [proof for proof in verified if proof.get('match_kind') == 'related']
                related_only = bool(related) and not matched_skills
                incidental_ai = plan.searchQuery == 'ai' and not evidence('ai engineer', pages) and not any(
                    evidence(proof['matched_term'] + ' engineer',pages) for proof in related)
                best = None
                for i, part in enumerate(json.loads(row['chunks'])):
                    phrase, complete, hits = matcher.match(part['text'])
                    if question:
                        complete = bool(hits)
                    semantic = vectors.get(part.get('vector_id', ''), 0.)
                    required_similarity = context_threshold if matcher.semantic_context(part['text']) else threshold
                    if mode == 'keyword':
                        relevant = phrase or complete
                    elif mode == 'semantic':
                        relevant = semantic >= required_similarity
                    else:
                        relevant = phrase or complete or semantic >= required_similarity
                    # Document-level AND/OR evidence can span several chunks/pages.
                    # A semantic-only request still has to pass its calibrated threshold.
                    structured = bool(plan.numericConditions or len(plan.requiredGroups) > 1 or
                                      any(len(branch) > 1 for branch in plan.requiredGroups))
                    if mode != 'semantic' and structured and (verified or not plan.requiredGroups):
                        relevant = True
                    if mode != 'semantic' and verified and plan.searchQuery in {'.net', 'dotnet', 'react', 'javascript', 'typescript', 'node.js'}:
                        relevant = True
                        structured = True
                    # Disjoint score ranges guarantee the requested ordering even
                    # if an unrelated vector has a higher cosine similarity.
                    match_type = 'exact_phrase' if phrase else 'complete_keywords' if complete else 'semantic'
                    score = .90 + .10 * semantic if phrase else .75 + .14 * semantic if complete else .74 * semantic
                    if question and hits:
                        score = .55 + .20 * semantic
                        match_type = 'question_evidence'
                    if structured and verified and not (phrase or complete):
                        score = .75 + .14 * semantic
                        match_type = 'verified_requirements'
                    if skill_match == 'any' and requested:
                        if related_only:
                            relevant = semantic >= required_similarity
                            score = .74 * semantic
                            match_type = 'related_profile'
                        elif matched_skills and missing_skills:
                            relevant = mode != 'semantic' or semantic >= required_similarity
                            score = .60 + .14 * semantic
                            match_type = 'partial_keywords'
                    if incidental_ai:
                        # A product-sales mention cannot earn an engineering-level AI rating.
                        score = min(score, .30 + .20 * semantic)
                    if relevant and (best is None or score > best['score']):
                        best = {k: v for k, v in part.items() if k != 'vector_id'}
                        best.update(score=score, chunk_id=f"{row['id']}:{i}",
                                    match_type=match_type, matched_keywords=hits,
                                    semantic_threshold=round(required_similarity, 4) if mode != 'keyword' else None,
                                    semantic_similarity=round(semantic, 4) if mode != 'keyword' else None)
                if best:
                    reasons = []
                    if best['match_type'] == 'exact_phrase':
                        reasons.append(f'The exact phrase “{retrieval_query}” appears in the matching passage.')
                    elif best['match_type'] == 'question_evidence':
                        reasons.append('Question topics found in the cited passage: ' + ', '.join(best['matched_keywords']) + '. This does not mean every query word matches.')
                    elif best['match_type'] == 'complete_keywords':
                        reasons.append('All meaningful query words match: ' + ', '.join(best['matched_keywords']) + '.')
                    elif best['match_type'] == 'verified_requirements':
                        reasons.append('Mandatory conditions are verified across the cited document pages.')
                    elif best['match_type'] == 'partial_keywords':
                        reasons.append('Matches at least one requested skill: ' + ', '.join(matched_skills) + '. Other requested skills are optional in Any skill mode.')
                    elif best['match_type'] == 'related_profile':
                        reasons.append('Related profile: relevant experience was found, but the requested skill names were not verified.')
                    else:
                        reasons.append('The passage is related in meaning to your query, even without the complete literal phrase.')
                        found_context = [term for term in CONTEXT_TERMS.get(matcher.intent, ())
                                   if bounded(re.escape(term).replace(r'\ ', r'\s+')).search(best['text'])]
                        if found_context:
                            reasons.append('Related concepts found in this passage: ' + ', '.join(found_context[:5]) + '.')
                    if best['semantic_similarity'] is not None:
                        reasons.append(f"Semantic similarity {best['semantic_similarity']:.2f} " +
                                       (f"passes the applicable {best['semantic_threshold']:.2f} relevance threshold." if best['semantic_similarity'] >= best['semantic_threshold'] else
                                        'does not pass the semantic threshold; this result qualifies through literal matching.'))
                    reasons.append(f"Evidence is on page {best['page']}, section “{best['section']}”.")
                    rating = best['score'] * 5
                    rating_failures = [condition for condition in plan.numericConditions
                                       if condition['field'] == 'rating' and not compare(rating, condition)]
                    if rating_failures:
                        label = 'Relevance rating does not satisfy the requested threshold'
                        details['rejections'][label] = details['rejections'].get(label, 0) + 1
                        continue
                    reasons = [(f"Related experience for {item['requirement']} on page {item['page']}: {item['matched_term']}. {item['relationship']}"
                                if item.get('match_kind') == 'related' else
                                f"Verified {item['requirement']} on page {item['page']}: {item['text'][:240]}") for item in verified] + reasons
                    if incidental_ai:
                        reasons.insert(0, 'AI is mentioned, but hands-on AI engineering could not be verified; relevance is limited.')
                    results.append({**best, 'id': row['id'], 'filename': row['name'],
                                    'candidate_name':verified_candidate_heading(pages),
                                    'highlight_query': retrieval_query,
                                    'matched_requirements': [item['requirement'] for item in verified if item.get('match_kind') != 'related'],
                                    'matched_skills': matched_skills, 'missing_skills': missing_skills,
                                    'related_skills': [proof['matched_term'] for proof in related],
                                    'skill_match': skill_match,
                                    'evidence': verified, 'missing_preferred': missing_preferred,
                                    'reasons': reasons, 'rating': {'value': rating, 'out_of': 5,
                                    'label': 'Limited AI mention' if incidental_ai else 'Excellent literal match' if rating >= 4.5 else 'Strong keyword match' if rating >= 3.75 else 'Related semantic match',
                                    'basis': 'Retrieval relevance, not document quality or a probability'},
                                    'category': row['category'], 'type': Path(row['name']).suffix,
                                    'uploaded': row['uploaded'], 'source': row['source'],
                                    'reason': {'question_evidence': 'Evidence related to the requested question', 'exact_phrase': 'Exact phrase match', 'complete_keywords': 'All query keywords match',
                                               'semantic': 'Related meaning; no complete literal query match',
                                               'partial_keywords': 'At least one requested skill matches',
                                               'related_profile': 'Related experience; requested skills not verified',
                                               'verified_requirements': 'Mandatory requirements verified across the document'}[best['match_type']],
                                    'url': f"/api/documents/{row['id']}/file#page={best['page']}"})
            unique = deduplicate(results, valid_rows, plan.intent == 'candidate_recommendation')
        details['duplicates_removed'] = len(results) - len(unique)
        details['qualified_count'] = len(unique)
        target = plan.requestedCount if plan.requestedCount is not None else limit
        minimum = target if plan.requestedCount is not None else config.MIN_RECOMMENDATIONS
        if len(unique) < minimum:
            details['message'] = (f'Requested {minimum} unique qualifying documents; only {len(unique)} could be verified. '
                                  'No recommendations returned under the required count policy.')
            if details['rejections']:
                details['message'] += ' Unmet criteria: ' + '; '.join(list(details['rejections'])[:4]) + '.'
            return SearchResults(**details)
        # A small bounded batch keeps language-model work independent of library size.
        if enrich and unique and hasattr(self.ollama, 'rerank'):
            budget = max(500, config.CONTEXT_SIZE - 1600)
            candidates = unique[:config.RERANK_LIMIT]
            excerpts = [{'id': item['id'], 'text': item['text'][:max(80, budget // len(candidates))]} for item in candidates]
            try:
                ranking_query = ('Match any one requested skill or supported related experience; do not require all skills. Query: ' + query
                                 if skill_match == 'any' else query)
                proposal = self.ollama.rerank(ranking_query, excerpts)
                lookup = {item['id']: item['text'] for item in excerpts}
                for item in unique:
                    votes = [vote for vote in proposal.get('results', []) if isinstance(vote, dict) and vote.get('id') == item['id']]
                    if votes:
                        vote = votes[0]
                        quote, grade = vote.get('quote'), vote.get('relevance')
                        if isinstance(quote, str) and len(quote.strip()) >= 12 and quote in lookup.get(item['id'], '') and type(grade) in (int, float) and 0 <= grade <= 3:
                            item['rerank_evidence'] = quote
                            item['rerank_grade'] = grade
                unique.sort(key=lambda item: (item['score'], item.get('rerank_grade', 0)), reverse=True)
                details['reranking'] = 'Ollama evidence-checked tie breaking; ratings unchanged'
            except Exception:
                details['reranking'] = 'deterministic fallback'
        # A dataset may be reassigned while Ollama runs. Never return a moved source.
        if dataset is not None:
            with self.lock:
                current = {row['id']: row for row in self.rows(owner, dataset)}
                unique = [item for item in unique if item['id'] in current and
                          current[item['id']]['digest'] == valid_rows[item['id']]['digest']]
            details['qualified_count'] = len(unique)
            if len(unique) < minimum:
                details['message'] = 'Documents changed during the search. Not enough qualifying documents remain in the selected dataset; please search again.'
                return SearchResults(**details)
        response = SearchResults(unique[:target], **details)
        response.versions = {item['id']:valid_rows[item['id']]['digest'] for item in response}
        return response
