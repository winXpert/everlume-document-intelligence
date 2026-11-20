const $ = id => document.getElementById(id);
let activeDoc, activePage = 1, searchSequence = 0, suggestSequence = 0;
let sessionPromise, libraryPage = 1, libraryData, selectedIds = new Set();
let selectedFiles = [], activeJob, jobs = [], sending = false, cancelTransfers = false;
const jobFiles = new Map(), transferErrors = new Map();
let librarySequence = 0, lastReadyCount = -1;
let resultState = {items: [], query: '', message: '', page: 1};
const RESULTS_PAGE_SIZE = 20;

async function connect() {
  if (!sessionPromise) sessionPromise = fetch('/api/session', {method: 'POST', credentials: 'same-origin',
    headers: {'X-Requested-With': 'EverlumeWorkspace'}}).then(async response => {
    if (!response.ok) throw new Error('The local workspace could not connect. Start the backend on this machine.');
    document.querySelector('.connection').classList.add('online');
    $('connection-label').textContent = 'Local workspace connected';
    return response.json();
  }).catch(error => { sessionPromise = null; throw error; });
  return sessionPromise;
}
async function api(path, options = {}, retry = true) {
  await connect();
  const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store', ...options});
  if (response.status === 401 && retry) { sessionPromise = null; await connect(); return api(path, options, false); }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
  }
  return response;
}
function jsonOptions(body, method = 'POST') { return {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}; }
function message(id, text, error = false) { $(id).textContent = text; $(id).classList.toggle('error', error); }
function element(tag, text, className) {
  const node = document.createElement(tag); node.textContent = text;
  if (className) node.className = className;
  return node;
}
function showView(view) {
  for (const node of document.querySelectorAll('.view')) node.hidden = node.id !== `view-${view}`;
  for (const button of document.querySelectorAll('.nav')) {
    button.classList.toggle('active', button.dataset.view === view);
    if (button.dataset.view === view) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  }
  $('breadcrumb').textContent = {discover: 'Discover', library: 'Document library', uploads: 'Upload center'}[view];
  if (view === 'library') loadLibrary().catch(globalError);
  if (view === 'uploads') refreshJobs().catch(globalError);
}
function globalError(error) { message('global-status', error.message, true); }
document.querySelectorAll('.nav').forEach(button => button.onclick = () => showView(button.dataset.view));
document.querySelectorAll('[data-open-library]').forEach(button => button.onclick = () => showView('library'));
document.querySelectorAll('[data-open-uploads]').forEach(button => button.onclick = () => showView('uploads'));
$('hero-upload').onclick = () => { showView('uploads'); $('file').click(); };

function highlight(text, query) {
  const fragment = document.createDocumentFragment();
  const originalTokens = query.normalize('NFKC').match(/\.net\b|[\p{L}\p{N}_]+(?:\+\+|#|\.js\b)?/giu) || [];
  let tokens = [...originalTokens];
  if (tokens.length > 2) {
    const stopwords = new Set('a an and are as at be by can could do does for from how i in is it me of on or please related show the to was what when where which who with would you documents document find about many'.split(' '));
    tokens = tokens.filter(t => !stopwords.has(t.toLowerCase()));
  }
  if (!tokens.length) { fragment.append(text); return fragment; }
  const escaped = tokens.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const phrase = originalTokens.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
  const regex = new RegExp(`(?<![\\p{L}\\p{N}_])(?:${phrase}|${escaped.join('|')})(?![\\p{L}\\p{N}_])`, 'giu');
  let start = 0;
  for (const match of text.matchAll(regex)) {
    fragment.append(text.slice(start, match.index), element('mark', match[0]));
    start = match.index + match[0].length;
  }
  fragment.append(text.slice(start)); return fragment;
}
function render(results, query, emptyMessage = '', page = 1) {
  const pages = Math.max(1, Math.ceil(results.length / RESULTS_PAGE_SIZE));
  page = Math.max(1, Math.min(page, pages));
  resultState = {items: results, query, message: emptyMessage, page};
  const offset = (page - 1) * RESULTS_PAGE_SIZE;
  $('results-pagination').hidden = results.length <= RESULTS_PAGE_SIZE;
  $('results-page').textContent = `Showing ${offset + 1}–${Math.min(offset + RESULTS_PAGE_SIZE, results.length)} of ${results.length} matches · Page ${page} of ${pages}`;
  $('results-prev').disabled = page === 1;
  $('results-next').disabled = page === pages;
  $('results').replaceChildren(); $('result-count').textContent = results.length ? `(${results.length})` : '';
  if (!results.length) {
    const empty = element('div', '', 'empty-state');
    empty.append(element('div', '⌕'), element('h3', 'No matching information found.'), element('p', emptyMessage || 'Try a different phrase, broaden the topic, or add more relevant documents to your library.'));
    $('results').append(empty); return;
  }
  results.slice(offset, offset + RESULTS_PAGE_SIZE).forEach((result, index) => {
    index += offset;
    const card = element('section', '', 'card'), top = element('div', '', 'card-top');
    const title = element('div', '', 'document-title'), name = element('div', '');
    name.append(element('h3', `${result.source_id ? `[${result.source_id}] ` : ''}${result.filename}`), element('small', `#${index + 1} ${result.metadata_only ? 'dataset document' : 'recommendation'} · ${result.category} · Page ${result.page}`));
    title.append(element('span', (result.type || result.filename.split('.').pop()).replace('.', '').toUpperCase(), 'file-icon'), name);
    const rating = element('div', '', 'rating'), value = result.metadata_only ? 0 : result.rating?.value ?? Math.round(result.score * 50) / 10;
    rating.hidden = !!result.metadata_only;
    const ratingText = Math.abs(value * 10 - Math.round(value * 10)) < 1e-9 ? value.toFixed(1) : String(Number(value.toFixed(4)));
    rating.title = `Unrounded relevance rating: ${value} / 5. Filters use this value.`;
    rating.setAttribute('aria-label', `Relevance rating ${value} out of 5`);
    rating.append(element('strong', `${ratingText} / 5`), element('div', '★'.repeat(Math.round(value)) + '☆'.repeat(5 - Math.round(value)), 'stars'), element('small', result.rating?.label || 'Query relevance'));
    top.append(title, rating);
    const snippet = element('p', '', 'card-snippet'); snippet.append(highlight(result.text, result.highlight_query || query));
    const why = element('div', '', 'why'), reasons = element('ul', '');
    // Keep numerical filtering diagnostics in the API; show useful evidence here.
    for (const reason of (result.reasons || [result.reason]).filter(r => r && !r.startsWith('Semantic similarity'))) reasons.append(element('li', reason));
    for (const skill of result.missing_preferred || []) reasons.append(element('li', `Preferred qualification not verified: ${skill}`));
    if (result.missing_skills?.length) reasons.append(element('li', `Requested skills not verified: ${result.missing_skills.join(', ')}. Shown because another skill or related experience matches.`));
    why.append(element('strong', '✧ Why this document was chosen'), reasons);
    const footer = element('div', '', 'card-footer'), open = element('button', `View source · Page ${result.page} ↗`, 'outline');
    open.onclick = () => preview(result.id, result.page, result.highlight_query || query).catch(globalError);
    footer.append(element('span', {exact_phrase: 'EXACT PHRASE', complete_keywords: 'COMPLETE KEYWORDS', semantic: 'SEMANTIC MATCH', partial_keywords:'MATCHES SOME SKILLS', related_profile:'RELATED PROFILE'}[result.match_type] || (result.metadata_only ? 'DATASET DOCUMENT' : 'RELEVANT PASSAGE'), 'tag'), open);
    card.append(top, snippet, why, footer); $('results').append(card);
    if (result.evidence?.length) {
      const sources = element('div', '', 'evidence-links');
      for (const proof of result.evidence) {
        const label = proof.match_kind === 'related' ? `Related: ${proof.matched_term}` : proof.requirement;
        const button = element('button', `${label} · Page ${proof.page}`, 'quiet');
        button.title = proof.text; button.onclick = () => preview(result.id, proof.page, result.highlight_query || query).catch(globalError); sources.append(button);
      }
      card.append(sources);
    }
  });
}
$('results-prev').onclick = () => render(resultState.items, resultState.query, resultState.message, resultState.page - 1);
$('results-next').onclick = () => render(resultState.items, resultState.query, resultState.message, resultState.page + 1);
function setSearchLoading(loading, ask = false) {
  if (loading) $('results-pagination').hidden = true;
  $('search-loader').hidden = !loading;
  $('results').setAttribute('aria-busy', String(loading));
  $('search-loader-label').textContent = 'Understanding your request and preparing an answer…';
  $('ask').disabled = loading; $('search').querySelector('button').disabled = loading;
  $('ask').classList.toggle('is-loading', loading && ask);
  $('search').querySelector('button').classList.toggle('is-loading', loading && !ask);
}
let chatHistory = [];
const aiMode = document.createElement('label');
aiMode.textContent = 'AI mode ';
const aiSelect = document.createElement('select'); aiSelect.id = 'query-mode';
for (const [value,label] of [['auto','Auto'],['general','General AI'],['document','Document AI'],['hybrid','Hybrid AI']]) aiSelect.add(new Option(label,value));
aiMode.append(aiSelect); document.querySelector('.search-controls').prepend(aiMode);
const newChat = element('button','New conversation'); newChat.type = 'button'; newChat.className = 'quiet';
document.querySelector('.search-controls').append(newChat);
const transcript = document.createElement('details'); transcript.id = 'conversation';
const summary = document.createElement('summary'); summary.textContent = 'Conversation history';
transcript.append(summary); const turns = document.createElement('div'); transcript.append(turns);
$('answer').append(transcript);
newChat.onclick = () => { $('search-dataset').onchange(); };
aiSelect.onchange = () => { $('search-dataset').onchange(); };
async function search(ask = false) {
  const query = $('query').value.trim(); if (!query) return $('query').focus();
  const dataset = $('search-dataset').value;
  const sequence = ++searchSequence;
  setSearchLoading(true, ask);
  $('answer').hidden = true; $('results').replaceChildren();
  $('result-count').textContent = '';
  message('status', 'Understanding your request and preparing a response…');
  try {
    const body = await (await api(`/api/documents/${ask ? 'ask' : 'search'}`, jsonOptions({query, mode: $('mode').value, dataset, skill_match:$('skill-match').value, query_mode:aiSelect.value, history:chatHistory}))).json();
    if (sequence !== searchSequence) return;
    const results = ask ? body.sources : body.results; render(results, query, body.message);
    document.querySelector('.results-heading').hidden = body.query_mode === 'general';
    if (body.query_mode === 'general') { $('results').replaceChildren(); $('results-pagination').hidden = true; }
    if (ask || body.answer) {
      $('answer').hidden = false; $('answer-text').textContent = body.answer; $('followups').replaceChildren();
      $('answer').querySelector('.section-eyebrow').textContent = body.answer_mode || 'Verified document evidence';
      $('answer').querySelector('h2').textContent = body.query_mode === 'general' ? 'Ask. Explore. Understand.' : 'A clear answer. Verifiable sources.';
      if (body.answer && body.intent !== 'clarification') {
        chatHistory.push({role:'user',content:query.slice(0,1500),dataset},{role:'assistant',content:body.answer.slice(0,1500),dataset});
        chatHistory = chatHistory.slice(-6); turns.replaceChildren();
        for (const turn of chatHistory) turns.append(element('p',`${turn.role === 'user' ? 'You' : 'Assistant'}: ${turn.content}`));
      }
      const total = body.validation?.total_matching_documents, cited = body.validation?.answer_cited_documents;
      $('answer-scope').hidden = !(Number.isInteger(total) && Number.isInteger(cited) && cited > 0 && cited < total);
      $('answer-scope').textContent = `This answer cites ${cited} of ${total} matching documents. Narrow the question for a closer comparison.`;
      for (const question of body.follow_up_questions || []) {
        const button = element('button', question); button.onclick = () => { $('query').value = question; search(true); }; $('followups').append(button);
      }
    }
    if (body.intent === 'dataset_count') {
      $('results').replaceChildren(); $('results-pagination').hidden = true;
      $('result-count').textContent = '';
    }
    message('status', ['dataset_names', 'hiring_review'].includes(body.intent) ? body.message : results.length ? `${results.length} verified unique document${results.length === 1 ? '' : 's'} · Dataset: ${dataset}` : body.message || `No matching information was found in dataset “${dataset}”.`);
  } catch (error) { if (sequence === searchSequence) message('status', error.message, true); }
  finally { if (sequence === searchSequence) setSearchLoading(false); }
}
$('search').onsubmit = event => { event.preventDefault(); search(); };
$('ask').onclick = () => search(true);
document.querySelectorAll('[data-query]').forEach(button => button.onclick = () => { $('query').value = button.dataset.query; search(); });
let suggestionTimer;
$('search-dataset').onchange = () => {
    chatHistory = []; turns.replaceChildren();
    document.querySelector('.results-heading').hidden = false;
    resultState = {items: [], query: '', message: '', page: 1};
    $('results-pagination').hidden = true;
  ++searchSequence; ++suggestSequence; clearTimeout(suggestionTimer);
  $('results').replaceChildren(); $('result-count').textContent = '';
  $('answer').hidden = true; $('answer-text').textContent = ''; $('followups').replaceChildren(); $('suggestions').replaceChildren();
  if ($('preview').open) $('preview').close();
  setSearchLoading(false);
  message('status', `Dataset: ${$('search-dataset').value}. Enter a query and select Search; only this dataset will be used.`);
  if (aiSelect.value === 'general') {
    $('dataset-hint').textContent = 'General AI uses local model knowledge. No uploaded documents are searched.';
    message('status','Ask a general question. Uploaded documents are not required.');
  } else {
    $('dataset-hint').textContent = 'Document questions use only the selected dataset. Auto also answers general knowledge questions.';
  }
};
$('skill-match').onchange = () => {
  $('search-dataset').onchange();
  $('dataset-hint').textContent = $('skill-match').value === 'any'
    ? 'Search only this dataset. Any one requested skill is enough; Hybrid search also considers related experience.'
    : 'Search only this dataset. All requested skills must be verified.';
  message('status', $('skill-match').value === 'any' ? 'Any one requested skill is enough. Hybrid and Semantic search also include supported related profiles.' : 'All requested skills must be verified.');
};
function updateSearchDatasets(categories) {
  const selected = $('search-dataset').value || 'General';
  const names = [...new Set(['General', 'Digital Marketing', '.NET', 'Angular', ...categories, selected])];
  $('search-dataset').replaceChildren(...names.map(name => new Option(name, name)));
  $('search-dataset').value = selected;
}
$('query').oninput = () => {
  clearTimeout(suggestionTimer); const sequence = ++suggestSequence;
  suggestionTimer = setTimeout(async () => {
    try {
      const params = new URLSearchParams({query: $('query').value, dataset: $('search-dataset').value});
      const data = await (await api(`/api/documents/suggestions?${params}`)).json();
      if (sequence === suggestSequence) $('suggestions').replaceChildren(...data.suggestions.map(s => { const option = element('option', s); option.value = s; return option; }));
    } catch { $('suggestions').replaceChildren(); }
  }, 300);
};

// Library management: metadata only, with server-side filters and pagination.
async function loadLibrary() {
  const sequence = ++librarySequence;
  const params = new URLSearchParams({query: $('library-query').value, category: $('library-category').value, page: libraryPage, page_size: 25});
  const data = await (await api(`/api/documents?${params}`)).json();
  if (sequence !== librarySequence) return;
  if (libraryPage > 1 && !data.documents.length) { libraryPage--; return loadLibrary(); }
  libraryData = data; $('document-count').textContent = data.overall_total; $('nav-count').textContent = data.overall_total;
  updateSearchDatasets(data.categories);
  const category = $('library-category').value;
  const categories = [...data.categories]; if (category && !categories.includes(category)) categories.push(category);
  $('library-category').replaceChildren(new Option('All categories', ''), ...categories.map(c => new Option(c, c))); $('library-category').value = category;
  $('library-rows').replaceChildren();
  for (const doc of data.documents) {
    const row = element('tr', ''), checkCell = element('td', ''), check = document.createElement('input');
    check.type = 'checkbox'; check.checked = selectedIds.has(doc.id); check.setAttribute('aria-label', `Select ${doc.name}`);
    check.onchange = () => { if (check.checked) selectedIds.add(doc.id); else selectedIds.delete(doc.id); syncSelection(); };
    checkCell.append(check);
    const nameCell = element('td', ''), open = element('button', doc.name, 'filename-button');
    open.onclick = () => preview(doc.id, 1).catch(globalError); nameCell.append(open);
    const action = element('td', ''), manage = element('button', 'Manage ↗', 'quiet');
    manage.onclick = open.onclick; action.append(manage);
    row.append(checkCell, nameCell, element('td', doc.category), element('td', new Date(doc.uploaded).toLocaleDateString()), action);
    $('library-rows').append(row);
  }
  if (!data.documents.length) { const cell = element('td', 'No documents found. Add files in the upload center to build your library.'); cell.colSpan = 5; const row = element('tr', ''); row.append(cell); $('library-rows').append(row); }
  $('library-summary').textContent = `${data.total} document${data.total === 1 ? '' : 's'}${selectedIds.size ? ` · ${selectedIds.size} selected` : ''}`;
  $('library-page').textContent = `Page ${data.page} of ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
  $('library-prev').disabled = data.page <= 1; $('library-next').disabled = data.page * data.page_size >= data.total;
  syncSelection();
}
function syncSelection() {
  $('bulk-delete').disabled = !selectedIds.size;
  $('bulk-delete').textContent = selectedIds.size ? `Delete selected (${selectedIds.size})` : 'Delete selected';
  const visible = libraryData?.documents || [];
  $('select-page').checked = visible.length > 0 && visible.every(d => selectedIds.has(d.id));
  $('select-page').indeterminate = visible.some(d => selectedIds.has(d.id)) && !$('select-page').checked;
}
$('select-page').onchange = () => { for (const doc of libraryData?.documents || []) { if ($('select-page').checked) selectedIds.add(doc.id); else selectedIds.delete(doc.id); } loadLibrary().catch(globalError); };
let filterTimer;
$('library-query').oninput = () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => { libraryPage = 1; loadLibrary().catch(globalError); }, 250); };
$('library-category').onchange = () => { libraryPage = 1; loadLibrary().catch(globalError); };
$('library-prev').onclick = () => { libraryPage--; loadLibrary().catch(globalError); };
$('library-next').onclick = () => { libraryPage++; loadLibrary().catch(globalError); };
$('library-refresh').onclick = () => loadLibrary().catch(globalError);
$('bulk-delete').onclick = async () => {
  if (!confirm(`Delete ${selectedIds.size} selected documents and their search indexes?`)) return;
  $('bulk-delete').disabled = true;
  try {
    const ids = [...selectedIds];
    for (let offset = 0; offset < ids.length; offset += 200) await api('/api/documents/bulk-delete', jsonOptions({ids: ids.slice(offset, offset + 200)}));
    selectedIds.clear(); await loadLibrary(); $('results').replaceChildren(); $('answer').hidden = true;
  } catch (error) { globalError(error); syncSelection(); }
};

// Large batches use bounded HTTP transfers and a durable server indexing queue.
function selectFiles(files) {
  const merged = [...selectedFiles];
  for (const file of files) if (!merged.some(f => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified)) merged.push(file);
  if (merged.length > 200) return message('upload-status', 'Choose up to 200 files per batch.', true);
  selectedFiles = merged;
  const bytes = selectedFiles.reduce((sum, file) => sum + file.size, 0);
  $('selected-summary').textContent = selectedFiles.length ? `${selectedFiles.length} file${selectedFiles.length === 1 ? '' : 's'} selected · ${(bytes / 1048576).toFixed(1)} MB total` : 'No files selected';
}
$('file').onchange = () => { selectFiles(Array.from($('file').files)); $('file').value = ''; };
$('choose-folder').onclick = () => $('folder').click();
$('folder').onchange = () => {
  const files = Array.from($('folder').files);
  const supported = files.filter(file => /\.(pdf|docx|txt|csv|md|json|log)$/i.test(file.name));
  const dataset = files[0]?.webkitRelativePath.split('/')[0];
  if (!supported.length) { message('upload-status', 'The selected folder contains no supported documents.', true); $('folder').value = ''; return; }
  if (supported.length > 200) { message('upload-status', 'Choose up to 200 supported documents per batch. Split this folder into smaller batches.', true); $('folder').value = ''; return; }
  if (!dataset || dataset.length > 100) { message('upload-status', 'Use a folder name between 1 and 100 characters.', true); $('folder').value = ''; return; }
  selectedFiles = []; $('category').value = dataset; selectFiles(supported); $('folder').value = '';
  message('upload-status', `Folder selected. These ${supported.length} files will be uploaded to dataset “${dataset}”.`);
};
$('clear-selection').onclick = () => { selectedFiles = []; selectFiles([]); };
for (const event of ['dragenter', 'dragover']) $('dropzone').addEventListener(event, e => { e.preventDefault(); $('dropzone').classList.add('dragover'); });
for (const event of ['dragleave', 'drop']) $('dropzone').addEventListener(event, e => { e.preventDefault(); $('dropzone').classList.remove('dragover'); });
$('dropzone').addEventListener('drop', event => selectFiles(Array.from(event.dataTransfer.files)));

async function startUpload(resume = false) {
  if (sending) return;
  if (!selectedFiles.length) { message('upload-status', 'Choose your documents first.'); return $('file').click(); }
  if (selectedFiles.length > 200) return message('upload-status', 'Choose up to 200 files per batch.', true);
  sending = true; cancelTransfers = false; $('upload-submit').disabled = true; $('resume-upload').disabled = true;
  message('upload-status', resume ? 'Resuming file transfers…' : 'Creating your upload batch…');
  try {
    const batch = resume && activeJob ? await (await api(`/api/documents/upload-jobs/${activeJob.id}`)).json() :
      await (await api('/api/documents/upload-jobs', jsonOptions({filenames: selectedFiles.map(f => f.name), category: $('category').value.trim() || 'General'}))).json();
    activeJob = batch;
    const mapping = jobFiles.get(batch.id) || new Map();
    const available = [...selectedFiles];
    for (const item of batch.items) {
      if (!resume || ['awaiting_upload', 'failed'].includes(item.state)) {
        const index = available.findIndex(file => file.name === item.name);
        if (index >= 0) mapping.set(item.id, available.splice(index, 1)[0]);
      }
    }
    jobFiles.set(batch.id, mapping);
    const pending = batch.items.filter(item => ['awaiting_upload', 'failed'].includes(item.state) && mapping.has(item.id));
    renderJob(batch); let cursor = 0, received = 0;
    async function transfer() {
      while (!cancelTransfers && cursor < pending.length) {
        const item = pending[cursor++];
        try {
          const form = new FormData(); form.append('file', mapping.get(item.id));
          const receipt = await (await api(`/api/documents/upload-jobs/${batch.id}/items/${item.id}`, {method: 'POST', body: form})).json();
          transferErrors.delete(item.id); if (['queued', 'indexing', 'indexed'].includes(receipt.state)) received++;
        } catch (error) { transferErrors.set(item.id, error.message); }
        message('upload-status', `${received} of ${pending.length} selected files received. Indexing continues in the background.`);
      }
    }
    await Promise.all([transfer(), transfer()]);
    if (!pending.length) message('upload-status', 'Select files matching the pending or failed filenames in this batch.', true);
    else if (cancelTransfers) message('upload-status', 'Remaining transfers stopped. A file already indexing may finish.');
    else message('upload-status', `${received} of ${pending.length} file transfers completed. Check the queue below for individual indexing results.`, received !== pending.length);
    selectedFiles = []; selectFiles([]); await refreshJobs();
  } catch (error) { message('upload-status', error.message, true); }
  finally { sending = false; $('upload-submit').disabled = false; $('resume-upload').disabled = false; }
}
$('upload').onsubmit = event => { event.preventDefault(); startUpload(); };
$('resume-upload').onclick = () => startUpload(true);

const stateLabels = {awaiting_upload: 'Awaiting file', queued: 'Queued', indexing: 'Indexing', indexed: 'Ready', failed: 'Failed', cancelled: 'Cancelled'};
function renderJob(job) {
  $('queue-panel').hidden = false; $('queue-title').textContent = `${job.total} documents · ${new Date(job.created).toLocaleString()}`;
  $('queue-progress').max = job.total; $('queue-progress').value = job.completed;
  $('queue-summary').textContent = `${job.completed} / ${job.total} completed · ${job.counts.indexed} ready · ${job.counts.indexing} indexing · ${job.counts.queued} queued · ${job.counts.awaiting_upload} awaiting files · ${job.counts.failed} failed · ${job.counts.cancelled} cancelled`;
  $('cancel-job').disabled = !(job.counts.awaiting_upload || job.counts.queued || job.counts.failed);
  $('resume-hint').hidden = !job.counts.awaiting_upload;
  $('resume-upload').hidden = !(job.counts.awaiting_upload || job.counts.failed);
  const rows = document.createDocumentFragment();
  for (const item of job.items) {
    const row = element('tr', ''), status = element('td', ''), detail = element('td', item.error || transferErrors.get(item.id) || (item.state === 'indexed' ? 'Indexed successfully' : item.state === 'indexing' ? 'Extracting and embedding content…' : ''));
    status.append(element('span', stateLabels[item.state] || item.state, `state ${item.state}`));
    if (item.can_retry || ['failed', 'awaiting_upload'].includes(item.state) && jobFiles.get(job.id)?.has(item.id)) {
      const retry = element('button', 'Retry', 'outline'); retry.disabled = sending;
      retry.onclick = async () => {
        retry.disabled = true;
        try {
          if (item.can_retry) await api(`/api/documents/upload-jobs/${job.id}/items/${item.id}/retry`, {method: 'POST'});
          else { const form = new FormData(); form.append('file', jobFiles.get(job.id).get(item.id)); await api(`/api/documents/upload-jobs/${job.id}/items/${item.id}`, {method: 'POST', body: form}); }
          transferErrors.delete(item.id); await refreshJobs();
        }
        catch (error) { message('upload-status', error.message, true); retry.disabled = false; }
      }; detail.append(retry);
    }
    row.append(element('td', item.name), status, detail); rows.append(row);
  }
  $('queue-rows').replaceChildren(rows);
}
async function refreshJobs() {
  const data = await (await api('/api/documents/upload-jobs')).json(); jobs = data.jobs;
  const inProgress = jobs.reduce((sum, job) => sum + job.counts.queued + job.counts.indexing + job.counts.awaiting_upload, 0);
  $('queue-count').textContent = inProgress; $('nav-queue').textContent = inProgress;
  if (!activeJob && jobs.length) activeJob = jobs.find(job => !job.finished) || jobs[0];
  if (activeJob) activeJob = jobs.find(job => job.id === activeJob.id) || activeJob;
  $('job-history').replaceChildren();
  for (const job of jobs) {
    const button = element('button', '', `job-button${activeJob?.id === job.id ? ' active' : ''}`), info = element('span', `${job.total} documents`);
    info.append(element('small', `${new Date(job.created).toLocaleString()} · ${job.counts.failed ? job.counts.failed + ' failed' : job.finished ? 'Completed' : 'In progress'}`));
    button.append(info, element('b', `${job.completed}/${job.total}`));
    button.onclick = () => { activeJob = job; renderJob(job); refreshJobs().catch(globalError); }; $('job-history').append(button);
  }
  if (!jobs.length) $('job-history').append(element('p', 'Your upload batches will appear here.', 'muted'));
  if (activeJob) renderJob(activeJob);
  const ready = jobs.reduce((sum, job) => sum + job.counts.indexed, 0);
  if (ready !== lastReadyCount) { lastReadyCount = ready; await loadLibrary(); }
}
$('jobs-refresh').onclick = () => refreshJobs().catch(globalError);
$('cancel-job').onclick = async () => {
  if (!activeJob || !confirm('Cancel files that have not started indexing? A file already indexing will finish.')) return;
  cancelTransfers = true;
  try { activeJob = await (await api(`/api/documents/upload-jobs/${activeJob.id}/cancel`, {method: 'POST'})).json(); renderJob(activeJob); await refreshJobs(); }
  catch (error) { globalError(error); }
};

async function preview(id, page, highlightQuery) {
  activeDoc = await (await api(`/api/documents/${id}`)).json(); activePage = page;
  activeDoc.highlightQuery = highlightQuery;
  $('preview-title').textContent = activeDoc.name; $('document-name').value = activeDoc.name; $('document-category').value = activeDoc.category;
  message('preview-status', ''); showPage(); if (!$('preview').open) $('preview').showModal();
}
function showPage() {
  activePage = Math.min(Math.max(activePage, 1), activeDoc.pages.length);
  $('page-label').textContent = `Page ${activePage} of ${activeDoc.pages.length}`;
  $('page-text').replaceChildren(highlight(activeDoc.pages[activePage - 1], activeDoc.highlightQuery || $('query').value));
  $('previous').disabled = activePage === 1; $('next').disabled = activePage === activeDoc.pages.length;
}
$('previous').onclick = () => { activePage--; showPage(); };
$('next').onclick = () => { activePage++; showPage(); };
$('close').onclick = () => $('preview').close();
$('download').onclick = async () => {
  try {
    const response = await api(`/api/documents/${activeDoc.id}/file`), url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = activeDoc.name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (error) { message('preview-status', error.message, true); }
};
$('metadata-form').onsubmit = async event => {
  event.preventDefault();
  try {
    await api(`/api/documents/${activeDoc.id}`, jsonOptions({name: $('document-name').value, category: $('document-category').value}, 'PATCH'));
    activeDoc.name = $('document-name').value; activeDoc.category = $('document-category').value; $('preview-title').textContent = activeDoc.name;
    message('preview-status', 'Document details saved.'); await loadLibrary();
  } catch (error) { message('preview-status', error.message, true); }
};
$('delete').onclick = async () => {
  if (!confirm(`Delete ${activeDoc.name} and its search index?`)) return;
  try { await api(`/api/documents/${activeDoc.id}`, {method: 'DELETE'}); selectedIds.delete(activeDoc.id); $('preview').close(); await loadLibrary(); if ($('query').value.trim()) search(); }
  catch (error) { message('preview-status', error.message, true); }
};
$('replace').onclick = () => $('replacement').click();
$('replacement').onchange = async () => {
  const file = $('replacement').files[0]; if (!file || !activeDoc) return;
  $('replace').disabled = true; message('preview-status', 'Replacing document and updating the search index…');
  try {
    const form = new FormData(); form.append('file', file); await api(`/api/documents/${activeDoc.id}`, {method: 'PUT', body: form});
    await preview(activeDoc.id, 1); message('preview-status', 'Document replaced and reindexed.'); await loadLibrary(); $('answer').hidden = true; $('results').replaceChildren();
  } catch (error) { message('preview-status', error.message, true); }
  finally { $('replacement').value = ''; $('replace').disabled = false; }
};

async function poll() {
  try { if (jobs.some(job => !job.finished) || sending) await refreshJobs(); }
  catch (error) { message('upload-status', `Progress temporarily unavailable: ${error.message}`, true); }
  setTimeout(poll, 1500);
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { loadLibrary().catch(globalError); refreshJobs().catch(globalError); }
});
(async () => {
  try { await connect(); await api('/api/health'); await loadLibrary(); await refreshJobs(); message('global-status', ''); }
  catch (error) { globalError(error); $('connection-label').textContent = 'Backend connection required'; }
  poll();
})();
