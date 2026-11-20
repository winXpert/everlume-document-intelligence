(async () => {
  const originalApi=api, savedQuery=$('query').value, savedMode=$('query-mode').value;
  const savedDataset=$('search-dataset').value;
  const checks=[]; let requests=[];
  try {
    $('query-mode').value='auto'; $('search-dataset').onchange();
    api=async (path,options) => {
      const request=JSON.parse(options.body); requests.push(request);
      return {json:async()=>({query_mode:'general',intent:'general_answer',
        answer:requests.length===1?'Machine learning learns from data.':'Here is an example.',
        answer_mode:'General knowledge · not based on uploaded documents',
        results:[],sources:[],validation:{},message:'Answered locally.'})};
    };
    $('query').value='What is machine learning?'; await search(true);
    checks.push(requests[0].query_mode==='auto' && requests[0].history.length===0);
    checks.push(!$('answer').hidden && $('answer').textContent.includes('General knowledge'));
    checks.push($('results').children.length===0 && document.querySelector('.results-heading').hidden);
    checks.push($('search-loader').hidden && !$('ask').disabled);
    $('query').value='Give an example'; await search(true);
    checks.push(requests[1].history.length===2 && requests[1].history[0].content==='What is machine learning?');
    checks.push($('conversation').querySelectorAll('p').length===4);
    $('search-dataset').value='.NET'; $('search-dataset').onchange();
    $('query').value='Explain RAG'; await search(true);
    checks.push(requests[2].history.length===0 && requests[2].dataset==='.NET');
    $('query-mode').value='general'; $('query-mode').onchange();
    checks.push($('dataset-hint').textContent.includes('No uploaded documents'));
    checks.push($('answer').hidden && $('conversation').querySelectorAll('p').length===0);
    if(checks.some(value=>!value)) throw Error('AI mode/conversation UI failed: '+JSON.stringify(checks));
    return {passed:checks.length};
  } finally {
    api=originalApi; $('query-mode').value=savedMode; $('search-dataset').value=savedDataset;
    $('search-dataset').onchange(); $('query').value=savedQuery;
  }
})()
