// Synthetic transport/card checks; no uploads or model calls.
(async()=>{
  let passed=0;
  const check=(ok,label)=>{if(!ok)throw Error(label);passed++};
  const saved={api:window.api,query:$('query').value,policy:$('skill-match').value,
    results:[...$('results').childNodes],count:$('result-count').textContent,
    status:$('status').textContent,hint:$('dataset-hint').textContent};
  try{
    check($('skill-match').value==='any','Any skill is the default');
    let sent;
    window.api=async(path,options)=>{sent=JSON.parse(options.body);return new Response(JSON.stringify({results:[]}))};
    $('query').value='Python and React';await search();
    check(sent.skill_match==='any','Search sends Any policy');
    $('skill-match').value='all';$('skill-match').dispatchEvent(new Event('change'));await search();
    check(sent.skill_match==='all'&&$('dataset-hint').textContent.includes('All requested skills'),'Strict option is explicit');
    render([{id:'synthetic',filename:'profile.txt',category:'Test',page:1,text:'Built React applications.',score:.6,
      match_type:'related_profile',missing_skills:['angular'],related_skills:['react'],
      evidence:[{requirement:'angular',matched_term:'react',match_kind:'related',page:1,text:'Built React applications.'}],
      reasons:['React is related experience; Angular was not verified.']}],'Angular');
    check($('results').querySelector('.tag').textContent==='RELATED PROFILE','Nearby profiles have their own label');
    check($('results').querySelector('.why').textContent.includes('Requested skills not verified: angular'),'Missing exact skills are transparent');
    check($('results').querySelector('.evidence-links button').textContent.includes('Related: react'),'Evidence labels do not invent Angular experience');
    check(!$('results').querySelector('mark'),'Semantic relationships are not literal highlights');
    return {passed};
  }finally{
    window.api=saved.api;$('query').value=saved.query;$('skill-match').value=saved.policy;
    $('results').replaceChildren(...saved.results);$('result-count').textContent=saved.count;
    message('status',saved.status);$('dataset-hint').textContent=saved.hint;setSearchLoading(false);
  }
})()
