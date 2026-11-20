// Nonmutating browser checks: synthetic cards and an invalid backend query.
(async () => {
  let passed = 0;
  const check = (condition, label) => { if (!condition) throw Error(label); passed++; };
  const saved = [...$('results').childNodes], count = $('result-count').textContent;
  try {
    render([{id:'synthetic', filename:'profile.txt', type:'.txt', category:'Test', page:1,
      score:.80998, text:'Python applications with 4 team members.', highlight_query:'Python', match_type:'verified_requirements',
      rating:{value:4.0499,label:'Verified requirements'}, reasons:['Verified Python'],
      evidence:[{requirement:'Python',page:2,text:'Developed Python applications.'}],
      missing_preferred:['Kubernetes']}], 'Python minimum 4 stars');
    check([...$('results').querySelectorAll('mark')].map(node=>node.textContent).join(',') === 'Python', 'Numeric filters are not highlighted as search terms');
    check($('results').querySelector('.rating strong').textContent === '4.0499 / 5', 'Rating precision is preserved');
    check($('results').querySelector('.rating').title.includes('4.0499'), 'Actual numerical rating is available');
    check($('results').querySelector('.evidence-links button').textContent.includes('Page 2'), 'Each verified requirement links to its page');
    check($('results').querySelector('.evidence-links button').title.includes('Developed Python'), 'Verbatim supporting evidence is available');
    check($('results').querySelector('.why').textContent.includes('Preferred qualification not verified: Kubernetes'), 'Missing preference is explained');
    render([], 'Python', 'Requested 5 unique qualifying documents; only 2 could be verified.');
    check(!$('results').querySelector('.card'), 'Empty response clears prior recommendations');
    check($('results').textContent.includes('only 2'), 'Count-policy explanation is displayed');
    const response = await (await api('/api/documents/search', jsonOptions({query:'AI minimum 8 stars'}))).json();
    check(response.results.length === 0 && response.validation.criteria.numericConditions[0].value === 8, 'Backend validates explicit numeric conditions');
    check(response.message.includes('between 0 and 5'), 'Invalid rating has a clear explanation');
    return {passed};
  } finally {
    $('results').replaceChildren(...saved); $('result-count').textContent = count;
  }
})()
