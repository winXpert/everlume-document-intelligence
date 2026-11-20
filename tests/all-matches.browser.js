(() => {
  const items = Array.from({length:45}, (_, i) => ({id:String(i), filename:`Profile ${i+1}.txt`,
    text:'Python engineer', page:1, category:'General', score:.9,
    reasons:['Verified Python'], rating:{value:4.5}}));
  const checks = [];
  render(items, 'Python');
  checks.push(document.querySelectorAll('#results .card').length === 20);
  checks.push($('result-count').textContent === '(45)');
  $('results-next').click();
  checks.push(document.querySelector('#results h3').textContent === 'Profile 21.txt');
  $('results-next').click();
  checks.push(document.querySelectorAll('#results .card').length === 5 && $('results-next').disabled);
  $('results-prev').click();
  checks.push(document.querySelector('#results h3').textContent === 'Profile 21.txt');
  $('search-dataset').onchange();
  checks.push($('results-pagination').hidden && resultState.items.length === 0);
  if (checks.some(passed => !passed)) throw new Error('Result pagination failed');
  return {passed:checks.length};
})()
