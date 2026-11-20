// Execute in the running app's browser context. Uses synthetic UI data only.
(async () => {
  let passed = 0;
  function check(condition, label) { if (!condition) throw new Error(label); passed++; }
  await connect();
  check(!document.querySelector('#token,input[type=password]'), 'No access-token field remains');
  check(!document.cookie.includes('everlume_session'), 'Session credential is inaccessible to JavaScript');
  check((await api('/api/health')).ok, 'Cookie-authenticated backend request works');
  const savedResults = [...$('results').childNodes], savedCount = $('result-count').textContent;
  render([{id:'synthetic-ui-test',filename:'AI-profile.txt',type:'.txt',category:'Test',page:2,
    score:.94,text:'Emails and maintenance. Agentic AI systems.',match_type:'exact_phrase',
    reasons:['Your exact phrase appears in the passage.','Evidence is on page 2.'],
    rating:{value:4.7,label:'Excellent literal match'}}], 'AI');
  check($('results').querySelector('.rating').textContent.includes('4.7 / 5'), 'Five-point relevance rating renders');
  check($('results').querySelectorAll('.why li').length === 2, 'Evidence reasons render');
  check([...$('results').querySelectorAll('mark')].every(node=>node.textContent==='AI'), 'Literal highlights exclude substrings');
  check($('results').querySelector('button').textContent.includes('Page 2'), 'Source navigation preserves page');
  $('results').replaceChildren(...savedResults); $('result-count').textContent = savedCount;
  const savedFiles = selectedFiles, summary = $('selected-summary').textContent;
  const uploadStatus = $('upload-status').textContent;
  selectedFiles = [];
  selectFiles(Array.from({length:200},(_,i)=>new File(['small test'],`test-${i}.txt`,{type:'text/plain',lastModified:1})));
  check(selectedFiles.length === 200 && $('selected-summary').textContent.includes('200 files'), '200-file selection is supported');
  selectFiles([new File(['extra'],'extra.txt')]);
  check(selectedFiles.length === 200 && $('upload-status').textContent.includes('200'), 'Selection is capped at 200');
  selectedFiles = savedFiles; $('selected-summary').textContent = summary; message('upload-status',uploadStatus);
  const savedDoc = activeDoc, savedPage = activePage, savedQuery = $('query').value;
  const savedPageNodes = [...$('page-text').childNodes], savedPageLabel = $('page-label').textContent;
  activeDoc = {pages:['Emails and AI.','Maintenance and AI Engineer.']}; activePage = 1; $('query').value = 'AI';
  showPage(); $('next').click();
  check(activePage===2 && $('page-label').textContent==='Page 2 of 2', 'Preview page controls still work');
  check([...$('page-text').querySelectorAll('mark')].map(node=>node.textContent).join(',')==='AI', 'Preview uses corrected highlighting');
  activeDoc=savedDoc;activePage=savedPage;$('query').value=savedQuery;
  $('page-text').replaceChildren(...savedPageNodes);$('page-label').textContent=savedPageLabel;
  if(activeDoc)showPage();
  return {passed};
})()
