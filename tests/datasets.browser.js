// Synthetic UI/transport fixtures only; no user documents are changed.
(async () => {
  let passed = 0;
  const check = (condition, label) => { if (!condition) throw Error(label); passed++; };
  const saved = {api:window.api, query:$('query').value, dataset:$('search-dataset').value,
    options:[...$('search-dataset').options].map(o=>[o.text,o.value]), files:selectedFiles,
    category:$('category').value, selected:$('selected-summary').textContent,
    uploadStatus:$('upload-status').textContent,status:$('status').textContent,
    results:[...$('results').childNodes],count:$('result-count').textContent,
    answerHidden:$('answer').hidden,answer:$('answer-text').textContent,
    followups:[...$('followups').childNodes], suggestions:[...$('suggestions').childNodes]};
  try {
    const select = $('search-dataset');
    check(['General','Digital Marketing','.NET','Angular'].every(name=>[...select.options].some(option=>option.value===name)), 'Domain datasets are available');
    select.value='.NET'; $('query').value='Python';
    const requests=[];
    window.api=async(path,options)=>{
      requests.push({path,body:options?.body?JSON.parse(options.body):null});
      if(path.includes('/ask'))return new Response(JSON.stringify({sources:[],answer:'No matching information was found.',follow_up_questions:[],message:'No matches in .NET'}));
      return new Response(JSON.stringify({results:[],message:'No matches in .NET'}));
    };
    await search();
    check(requests.at(-1).body.dataset==='.NET','Search sends selected dataset');
    await search(true);
    check(requests.at(-1).body.dataset==='.NET'&&requests.at(-1).path.endsWith('/ask'),'Answers send selected dataset');
    $('query').oninput();await new Promise(resolve=>setTimeout(resolve,400));
    check(requests.at(-1).path.includes('dataset=.NET'),'Autocomplete sends selected dataset');
    render([{id:'synthetic',filename:'profile.txt',category:'.NET',page:1,text:'Python',score:.9}], 'Python');
    $('answer').hidden=false;$('answer-text').textContent='Old answer';
    select.value='Angular';select.dispatchEvent(new Event('change'));
    check(!$('results').querySelector('.card')&&$('answer').hidden&&!$('answer-text').textContent,'Changing datasets clears old cards and answers');
    check($('query').value==='Python','Dataset changes preserve the query');
    let release;
    window.api=()=>new Promise(resolve=>{release=resolve});
    const pending=search();select.value='.NET';select.dispatchEvent(new Event('change'));
    release(new Response(JSON.stringify({results:[{id:'stale',filename:'stale.txt',category:'Angular',page:1,text:'Python',score:.9}]})));
    await pending;
    check(!$('results').querySelector('.card'),'Old in-flight responses cannot populate a new dataset');
    updateSearchDatasets(['General']);
    check(select.value==='.NET','Refreshing datasets never silently broadens selection');
    const folderFile=new File(['synthetic'],'resume.txt');
    Object.defineProperty(folderFile,'webkitRelativePath',{value:'.NET/resume.txt'});
    Object.defineProperty($('folder'),'files',{configurable:true,value:[folderFile]});
    $('folder').onchange();
    check($('category').value==='.NET'&&selectedFiles.length===1,'Folder name becomes its upload dataset');
    check($('upload-status').textContent.includes('.NET'),'Folder destination is explained');
    window.api=saved.api;
    const empty=await(await api('/api/documents/search',jsonOptions({query:'Python',dataset:'__missing_dataset_ui_test__',mode:'keyword'}))).json();
    check(empty.results.length===0&&empty.validation.dataset==='__missing_dataset_ui_test__','Unknown datasets return no cross-dataset results');
    return {passed};
  } finally {
    window.api=saved.api;delete $('folder').files;
    $('search-dataset').replaceChildren(...saved.options.map(([text,value])=>new Option(text,value)));$('search-dataset').value=saved.dataset;
    $('query').value=saved.query;selectedFiles=saved.files;$('category').value=saved.category;
    $('selected-summary').textContent=saved.selected;message('upload-status',saved.uploadStatus);message('status',saved.status);
    $('results').replaceChildren(...saved.results);$('result-count').textContent=saved.count;
    $('answer').hidden=saved.answerHidden;$('answer-text').textContent=saved.answer;
    $('followups').replaceChildren(...saved.followups);$('suggestions').replaceChildren(...saved.suggestions);
  }
})()
