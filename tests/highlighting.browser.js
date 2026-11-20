// Run in the app's browser context, where highlight() is the production function.
(() => {
  const cases = [
    ['.NET', 'Internet NET .NET and ASP.NET', ['.NET']],
    ['C#', 'C++ C C#', ['C#']],
    ['C++', 'C# C C++', ['C++']],
    ['AI', 'Emails Maintenance Familiar AI ai (AI)', ['AI', 'ai', 'AI']],
    ['AI Engineer', 'Emails maintenance familiar. AI Engineer.', ['AI Engineer']],
    ['Agentic AI', 'Agentic AI and autonomous agents.', ['Agentic AI']],
    ['ML Engineer', 'HTML engineer. ML Engineer; Machine Learning Engineer.', ['engineer', 'ML Engineer', 'Engineer']],
    ['AI', 'éAI AIé _AI AI_', []],
    ['AI', '<img src=x onerror=alert(1)> AI', ['AI']],
    ['Agentic AI', 'Agentic\nAI', ['Agentic\nAI']],
    ['AI', 'Autonomous agents and orchestration.', []],
    ['How many days of annual leave?', 'annual leave benefits and days', ['annual', 'leave', 'days']],
  ];
  for (const [query, text, expected] of cases) {
    const container = document.createElement('div');
    container.append(highlight(text, query));
    const actual = [...container.querySelectorAll('mark')].map(node => node.textContent);
    if (JSON.stringify(actual) !== JSON.stringify(expected) || container.textContent !== text || container.querySelector('img')) {
      throw new Error(JSON.stringify({query, text, expected, actual}));
    }
  }
  return {passed: cases.length};
})()
