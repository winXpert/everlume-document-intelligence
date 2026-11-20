// Run in the app browser. Fixtures never upload, index, or modify documents.
(async () => {
  let passed = 0;
  const check = (value, label) => { if (!value) throw Error(label); passed++; };
  async function fixture(saved, dark = false, blocked = false) {
    const frame = document.createElement('iframe');
    frame.style.cssText = 'position:fixed;left:-10000px;width:390px;height:800px';
    const ready = new Promise(resolve => frame.onload = resolve);
    frame.srcdoc = `<!doctype html><html><head><meta name="theme-color"><script>
      window.memory=${JSON.stringify(saved ? {'everlume.theme': saved} : {})};
      const media={matches:${dark},addEventListener:(name,callback)=>window.onMediaChange=callback};
      window.matchMedia=()=>media;
      window.changeSystem=value=>{media.matches=value;window.onMediaChange({matches:value})};
      window.setSystemSilently=value=>{media.matches=value};
      Object.defineProperty(window,'localStorage',{value:{getItem(key){if(${blocked})throw Error('Blocked');return window.memory[key]??null},setItem(key,value){if(${blocked})throw Error('Blocked');window.memory[key]=value}}});
      <\/script><script src="/theme.js?v=2"><\/script><script>window.beforeBody=document.documentElement.dataset.theme;<\/script>
      </head><body><select id="theme-preference"><option value="light">Light</option><option value="dark">Dark</option><option value="system">System</option></select><span id="theme-status"></span></body></html>`;
    document.body.append(frame); await ready;
    return frame;
  }
  const frames = [];
  const original = EverlumeTheme.preference;
  const savedQuery = $('query').value, savedFilter = $('library-query').value;
  const selected = selectedFiles, savedResults = [...$('results').childNodes], count = $('result-count').textContent;
  const sample = document.createElement('div');
  sample.style.cssText = 'position:fixed;left:-10000px';
  sample.innerHTML = '<section class="card"><p class="card-snippet">Evidence <mark>AI</mark></p><div class="why"><strong>Verified evidence</strong></div></section><span class="state indexed">Ready</span><span class="state failed">Failed</span><span class="state indexing">Processing</span><dialog open>Preview <pre>Document text</pre></dialog>';
  document.body.append(sample);
  try {
    let frame = await fixture(null); frames.push(frame);
    check(frame.contentWindow.EverlumeTheme.preference === 'system', 'No saved preference defaults to System');
    check(frame.contentWindow.beforeBody === 'light', 'Theme resolves before body renders');
    frame.contentWindow.changeSystem(true);
    check(frame.contentDocument.documentElement.dataset.theme === 'dark', 'System switches automatically to dark');
    frame.contentWindow.changeSystem(false);
    check(frame.contentDocument.documentElement.dataset.theme === 'light', 'System switches automatically to light');
    frame.contentWindow.setSystemSilently(true);
    frame.contentWindow.dispatchEvent(new frame.contentWindow.Event('focus'));
    check(frame.contentDocument.documentElement.dataset.theme === 'dark', 'Returning to a suspended tab refreshes System theme');
    frame.contentWindow.EverlumeTheme.setPreference('dark');
    check(frame.contentWindow.memory['everlume.theme'] === 'dark', 'Preference is saved');
    frame.contentWindow.changeSystem(false);
    check(frame.contentDocument.documentElement.dataset.theme === 'dark', 'Explicit dark ignores OS changes');
    frame.contentWindow.EverlumeTheme.setPreference('light');
    frame.contentWindow.changeSystem(true);
    check(frame.contentDocument.documentElement.dataset.theme === 'light', 'Explicit light ignores OS changes');
    frame.contentWindow.EverlumeTheme.setPreference('system');
    check(frame.contentDocument.documentElement.dataset.theme === 'dark', 'Returning to System resolves current OS appearance');
    frame.contentWindow.memory['everlume.theme'] = 'light';
    frame.contentWindow.dispatchEvent(new frame.contentWindow.StorageEvent('storage',{key:'everlume.theme'}));
    check(frame.contentWindow.EverlumeTheme.preference === 'light', 'Cross-tab storage changes synchronize');
    frame = await fixture('dark', false); frames.push(frame);
    check(frame.contentWindow.beforeBody === 'dark', 'Saved dark restores before first render');
    check(frame.contentDocument.querySelector('select').value === 'dark', 'Selector reflects saved preference');
    frame = await fixture('light', true); frames.push(frame);
    check(frame.contentWindow.beforeBody === 'light', 'Saved light overrides dark OS');
    frame = await fixture('invalid', true); frames.push(frame);
    check(frame.contentWindow.EverlumeTheme.preference === 'system' && frame.contentWindow.beforeBody === 'dark', 'Invalid preferences fall back to System');
    frame = await fixture(null, false, true); frames.push(frame);
    frame.contentWindow.EverlumeTheme.setPreference('dark');
    check(frame.contentDocument.documentElement.dataset.theme === 'dark', 'Blocked storage still allows switching');
    $('query').value = 'Theme state preservation'; $('library-query').value = 'Keep filter';
    selectedFiles = [new File(['synthetic'], 'theme-test.txt')];
    render([{id:'theme-fixture',filename:'synthetic.txt',page:1,category:'Test',score:.9,text:'AI evidence',rating:{value:4.5}}], 'AI');
    const card = $('results').firstChild;
    for (const [theme, background, panel, text] of [
      ['light','rgb(248, 250, 252)','rgb(255, 255, 255)','rgb(17, 24, 39)'],
      ['dark','rgb(15, 17, 23)','rgb(32, 33, 39)','rgb(249, 250, 251)'],
    ]) {
      const selector = $('theme-preference'); selector.value = theme; selector.dispatchEvent(new Event('change'));
      check(getComputedStyle(document.body).backgroundColor === background, `${theme}: main background`);
      check(getComputedStyle(sample.querySelector('.card')).backgroundColor === panel, `${theme}: card surface`);
      check(getComputedStyle(sample.querySelector('dialog')).backgroundColor === panel, `${theme}: preview surface`);
      check(getComputedStyle(sample.querySelector('.card-snippet')).color === text, `${theme}: readable text`);
      check(getComputedStyle(document.documentElement).colorScheme === theme, `${theme}: native controls`);
      check(localStorage.getItem('everlume.theme') === theme, `${theme}: real localStorage persistence`);
      check($('query').value === 'Theme state preservation' && $('library-query').value === 'Keep filter' && selectedFiles.length === 1 && $('results').firstChild === card, `${theme}: workspace state preserved`);
    }
    return {passed};
  } finally {
    frames.forEach(frame=>frame.remove()); sample.remove(); EverlumeTheme.setPreference(original);
    $('query').value=savedQuery; $('library-query').value=savedFilter; selectedFiles=selected;
    $('results').replaceChildren(...savedResults); $('result-count').textContent=count;
  }
})()
