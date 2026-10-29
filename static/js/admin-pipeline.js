(function () {
'use strict';
const root = document.getElementById('adminPipelinePanel');
if (!root) return;
const $ = (selector) => root.querySelector(selector);
const esc = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = (name) => `<svg aria-hidden="true"><use href="#pipeline-i-${name}"/></svg>`;
const plural = (n,one,few,many) => n%100>=11&&n%100<=14 ? many : n%10===1 ? one : n%10>=2&&n%10<=4 ? few : many;
const settingKeys = {
    rewrite:'CONVERSATIONAL_REWRITE_ENABLED', history:'RAG_QUERY_EXPANSION_MAX_MESSAGES',
    multi:'RAG_MULTI_QUERY_ENABLED', variants:'RAG_MULTI_QUERY_COUNT', hyde:'RAG_HYDE_ENABLED',
    mode:'RETRIEVAL_MODE', candidates:'RAG_FUSION_CANDIDATES', deep:'DEEP_RETRIEVAL_ENABLED',
    iterations:'DEEP_RETRIEVAL_MAX_ITERS', newQueries:'DEEP_RETRIEVAL_NEW_QUERIES_PER_ITER',
    rerank:'RERANK_ENABLED', rankTop:'RERANK_TOP_N', topK:'RAG_TOP_K', minScore:'RAG_MIN_SCORE',
    context:'RAG_MAX_CONTEXT_LENGTH', visual:'RAG_VISUAL_CONTEXT_ENABLED', tokens:'CHAT_MAX_TOKENS',
    citations:'RAG_MAX_CITATIONS', chitchat:'RAG_CHITCHAT_SKIP_RETRIEVAL', model:'OLLAMA_CHAT_MODEL',
};
let state = {};
let bridge;
let snapshot = {};
let initialized = false;
let selected = 'rewrite';
let runId = 0;
let running = false;
let scale = 1;
let position = {x:0,y:0};
let compact = false;
let toastTimer;
const stages = [
  {id:'input',name:'Вопрос пользователя',icon:'chat',number:'ВХОД',x:35,y:95,keys:['CHAT_ATTACHMENTS_ENABLED'],description:'Отправная точка: исходный вопрос, история диалога и вложения. Исходная формулировка также передаётся модели при генерации ответа.'},
  {id:'rewrite',name:'Дополнение вопроса',icon:'expand',number:'01',x:250,y:95,toggle:'rewrite',keys:['CONVERSATIONAL_REWRITE_ENABLED','RAG_QUERY_EXPANSION_MAX_MESSAGES'],description:'Превращает короткую реплику в самостоятельный поисковый запрос, учитывая предыдущие сообщения. Помогает понимать «его», «это» и уточнения.'},
  {id:'multi',name:'Переформулировки',icon:'flow',number:'02',x:475,y:65,toggle:'multi',keys:['RAG_MULTI_QUERY_ENABLED'],description:'Создаёт дополнительные формулировки одного вопроса. Каждая участвует в поиске, чтобы найти статьи с другими словами и терминами.'},
  {id:'hyde',name:'Гипотетический ответ',icon:'spark',number:'02b',x:475,y:230,toggle:'hyde',keys:['RAG_HYDE_ENABLED'],description:'Генерирует пример возможного ответа и использует его для поиска похожих фрагментов. Этот текст служит только поиску и не считается источником.'},
  {id:'dense',name:'Поиск по смыслу',icon:'search',number:'03a',x:705,y:65,keys:['RETRIEVAL_MODE','RAG_FUSION_CANDIDATES'],description:'Ищет семантически близкие фрагменты с помощью эмбеддингов. Находит нужную тему, даже если вопрос и документация используют разные слова.'},
  {id:'sparse',name:'Поиск по словам',icon:'lines',number:'03b',x:705,y:230,keys:['RETRIEVAL_MODE','RAG_FUSION_CANDIDATES'],description:'Ищет совпадения слов и терминов методом BM25. Особенно полезен для названий, сокращений, кодов ошибок и точных формулировок.'},
  {id:'fusion',name:'Объединение результатов',icon:'merge',number:'04',x:940,y:95,keys:['RRF_K_CONSTANT','RAG_TOP_K','RAG_MIN_SCORE'],description:'Объединяет списки найденных фрагментов и убирает повторы. В гибридном режиме учитывает позиции результатов двух способов поиска.'},
  {id:'deep',name:'Углублённый поиск',icon:'reset',number:'05',x:940,y:260,toggle:'deep',keys:['DEEP_RETRIEVAL_ENABLED','DEEP_RETRIEVAL_MAX_ITERS','DEEP_RETRIEVAL_NEW_QUERIES_PER_ITER'],description:'Если результатов недостаточно, предлагает дополнительные запросы и повторяет поиск. Число итераций ограничено; поиск может завершиться раньше.'},
  {id:'rerank',name:'Повторное ранжирование',icon:'rank',number:'06',x:940,y:430,toggle:'rerank',keys:['RERANK_ENABLED','RERANK_TOP_N','RERANK_MODEL'],description:'Cross-encoder оценивает пары «вопрос — фрагмент» и меняет порядок результатов. Требует доступной модели и увеличивает время обработки.'},
  {id:'context',name:'Сбор контекста',icon:'context',number:'07',x:705,y:430,keys:['RAG_TOP_K','RAG_MIN_SCORE','RAG_MAX_CONTEXT_LENGTH','RAG_VISUAL_CONTEXT_ENABLED'],description:'Собирает отобранные фрагменты в контекст для модели, соблюдая лимит длины. По настройке добавляет найденные изображения базы знаний.'},
  {id:'generate',name:'Генерация ответа',icon:'spark',number:'08',x:475,y:430,keys:['OLLAMA_CHAT_MODEL','CHAT_MAX_TOKENS'],description:'Модель получает исходный вопрос, историю и найденный контекст. Формирует ответ в выбранном стиле: обычный, краткий или инструкция.'},
  {id:'output',name:'Ответ и источники',icon:'check',number:'ВЫХОД',x:250,y:430,keys:['RAG_MAX_CITATIONS'],description:'Готовый ответ поступает в чат вместе с источниками и цитатами. Дополнительная обработка также может исправить диаграммы Mermaid.'},
];
const stageById = Object.fromEntries(stages.map((s) => [s.id,s]));
stageById.input.keys.push('RAG_CHITCHAT_SKIP_RETRIEVAL');
stageById.multi.keys.push('RAG_MULTI_QUERY_COUNT');
stageById.deep.keys.push('DEEP_RETRIEVAL_MIN_BEST_SCORE','DEEP_RETRIEVAL_MAX_CANDIDATES');
stageById.rerank.keys.push('RERANK_TIMEOUT_SECONDS','RERANK_MAX_TEXT_CHARS');
stageById.fusion.keys.push('RAG_FUSION_CANDIDATES','RRF_SCORE_NORMALIZER');
const compactPositions = {input:[20,60],rewrite:[255,60],multi:[255,240],hyde:[20,240],dense:[255,425],sparse:[20,425],fusion:[20,605],deep:[255,605],rerank:[255,785],context:[20,785],generate:[20,980],output:[255,980]};
const shortNames = {input:'Вопрос пользователя',hyde:'Гипотеза для поиска',fusion:'Объединение',rerank:'Ранжирование',output:'Готовый ответ'};

function nodeMetric(id) {
  if(id==='hyde' && state.hyde && state.mode==='sparse')return '<span class="metric-unit">Не участвует в поиске</span>';
  const numericKey={rewrite:'history',multi:'variants',deep:'iterations',rerank:'rankTop',context:'topK',generate:'tokens',output:'citations'}[id];
  if(numericKey && !Number.isFinite(state[numericKey]))return '<span class="metric-off">Укажите значение</span>';
  if (!enabled(id)) return '<span class="metric-off">Пропускается</span>';
  const metrics = {
    input:['','Текст · файлы · история'],
    rewrite:[state.history,`${plural(state.history,'сообщение','сообщения','сообщений')} истории`],
    multi:[`+${state.variants}`,plural(state.variants,'формулировка','формулировки','формулировок')],
    hyde:['HyDE','пример для поиска'],
    dense:['Векторы','близость по смыслу'],
    sparse:['BM25','точные совпадения'],
    fusion:[state.mode==='hybrid'?'RRF':'1 список','без повторов'],
    deep:[`↻ ${state.iterations}`,`${plural(state.iterations,'итерация','итерации','итераций')} максимум`],
    rerank:[state.rankTop,'кандидатов'],
    context:[state.topK,plural(state.topK,'фрагмент','фрагмента','фрагментов')],
    generate:[state.tokens,'токенов'],
    output:[`до ${state.citations}`,state.citations===1?'цитаты':'цитат'],
  };
  const [value,unit] = metrics[id];
  return `${value ? `<span class="metric-value">${value}</span>` : ''}<span class="metric-unit">${unit}</span>`;
}

function enabled(id) {
  const stage = stageById[id];
  if (id === 'dense') return state.mode !== 'sparse';
  if (id === 'sparse') return state.mode !== 'dense';
  if (id === 'hyde') return state.hyde;
  return stage.toggle ? state[stage.toggle] : true;
}

function stageInfo(id) {
  switch (id) {
    case 'input': return 'Текст · история · вложения';
    case 'rewrite': return state.rewrite ? `С учётом ${state.history} сообщений` : 'Исходная формулировка';
    case 'multi': return state.multi ? `1 исходный + ${state.variants} ${plural(state.variants,'вариант','варианта','вариантов')}` : 'Выключено · один запрос';
    case 'hyde': return state.hyde ? state.mode==='sparse' ? 'Создаётся, но не участвует в поиске' : 'Дополнительный векторный запрос' : 'Выключено · пропускается';
    case 'dense': return enabled('dense') ? 'Эмбеддинги · ChromaDB' : 'Отключён выбранным режимом';
    case 'sparse': return enabled('sparse') ? 'Ключевые слова · BM25' : 'Отключён выбранным режимом';
    case 'fusion': return state.mode === 'hybrid' ? 'RRF · удаление дубликатов' : 'Удаление дубликатов';
    case 'deep': return state.deep ? `По условию · до ${state.iterations} итераций` : 'Выключено · один проход';
    case 'rerank': return state.rerank ? `Cross-encoder · до ${state.rankTop} фрагм.` : 'Выключено · исходный порядок';
    case 'context': return `${state.topK} фрагм. · до ${Math.round(state.context / 1000)} тыс. знаков`;
    case 'generate': return `${state.answerMode === 'instruction' ? 'Инструкция' : state.answerMode === 'brief' ? 'Краткий ответ' : 'Обычный ответ'} · ${state.tokens} токенов`;
    case 'output': return `Ответ · до ${state.citations} цитат`;
    default: return '';
  }
}

function renderNodes() {
  for (const s of stages) {
    const [x,y] = compact ? compactPositions[s.id] : [s.x,s.y];
    let node = $(`[data-stage="${s.id}"]`);
    const existed = !!node;
    const wasOff = node?.classList.contains('off');
    if (!node) {node=document.createElement('button');node.type='button';node.dataset.stage=s.id;node.className='node';$('#pipeline-nodes').append(node);}
    node.classList.toggle('selected',selected===s.id);
    node.classList.toggle('off',!enabled(s.id));
    node.classList.toggle('terminal',s.id==='input'||s.id==='output');
    node.classList.toggle('search-node',s.id==='dense'||s.id==='sparse');
    node.style.left=`${x}px`;node.style.top=`${y}px`;
    node.setAttribute('aria-pressed',String(selected===s.id));
    node.setAttribute('aria-label',`${s.name}. ${stageInfo(s.id)}. Открыть параметры`);
    node.innerHTML=`<span class="port port-in"></span><span class="node-top"><span class="node-icon">${icon(s.icon)}</span><span class="node-number">${s.id==='deep'?'ПО УСЛОВИЮ':s.number}</span></span><span class="node-title">${shortNames[s.id]||s.name}</span><span class="node-info">${nodeMetric(s.id)}</span><span class="port port-out"></span>`;
    if (existed && wasOff && enabled(s.id)) {node.classList.add('just-enabled');setTimeout(()=>node.classList.remove('just-enabled'),650);}
  }
  $('#pipeline-active-count').textContent = `${stages.filter((s) => enabled(s.id)).length} из ${stages.length} этапов включено`;
  $('#pipeline-search-mode-caption').textContent=state.mode==='hybrid'?'ДВЕ ВЕТКИ ПОИСКА':state.mode==='dense'?'ПОИСК ПО СМЫСЛУ':'ПОИСК ПО СЛОВАМ';
}

function renderConnections() {
  const ds = enabled('dense'), sp = enabled('sparse');
  const source = state.multi ? 660 : 450;
  const sourceY = state.multi ? 121 : 151;
  const connections = [
    {id:'input-rewrite',d:'M220 151 H247',on:state.rewrite},
    {id:'rewrite-out',d:'M435 151 H450',on:state.rewrite},
    {id:'rewrite-bypass',d:'M220 151 H229 Q239 151 239 164 V214 Q239 225 250 225 H438 Q450 225 450 212 V151',on:!state.rewrite},
    {id:'rewrite-multi',d:'M450 151 C455 151 451 121 472 121',on:state.multi},
    {id:'to-dense',d:`M${source} ${sourceY} C${source+25} ${sourceY} 679 121 702 121`,on:ds},
    {id:'to-sparse',d:`M${source} ${sourceY} H678 Q689 ${sourceY} 689 ${sourceY+12} V274 Q689 286 702 286`,on:sp},
    {id:'rewrite-hyde',d:'M435 151 H449 Q458 151 458 165 V274 Q458 286 472 286',on:enabled('hyde'),optional:true},
    {id:'hyde-dense',d:'M660 286 H669 Q680 286 680 274 V133 Q680 121 702 121',on:enabled('hyde')&&ds,optional:true},
    {id:'dense-fusion',d:'M890 121 H905 Q916 121 916 133 V139 Q916 151 937 151',on:ds},
    {id:'sparse-fusion',d:'M890 286 H905 Q916 286 916 274 V163 Q916 151 937 151',on:sp},
    {id:'fusion-deep',d:state.deep ? 'M1032 207 V257' : state.rerank ? 'M1032 207 V222 Q1032 236 1139 236 Q1145 236 1145 250 V394 Q1145 408 1032 408 V427' : 'M1032 207 V222 Q1032 236 1139 236 Q1145 236 1145 250 V386 Q1145 398 1132 398 H810 Q797 398 797 411 V427',on:true},
    {id:'deep-rerank',d:state.rerank ? 'M1032 372 V427' : 'M1032 372 V386 Q1032 398 1018 398 H810 Q797 398 797 411 V427',on:state.deep},
    {id:'deep-loop',d:sp ? 'M940 316 H917 Q905 316 905 329 V349 Q905 360 892 360 H804 Q791 360 791 347 V345' : 'M940 316 H923 Q911 316 911 303 V197 Q911 187 898 187 H810 Q797 187 797 180',on:state.deep,loop:true},
    {id:'rerank-context',d:'M940 486 H893',on:state.rerank},
    {id:'context-generate',d:'M705 486 H663',on:true},
    {id:'generate-output',d:'M475 486 H438',on:true},
    {id:'greeting-route',d:'M127 207 V565 Q127 582 144 582 H550 Q567 582 567 565 V545',on:true,hidden:true},
  ];
  if (compact) {
    const compactPaths = {
      'input-rewrite':'M205 116 H252',
      'rewrite-out':'M347 172 V174',
      'rewrite-bypass':'M112 172 V199 Q112 211 124 211 H337 Q347 211 347 223',
      'rewrite-multi':'M347 172 V237',
      'to-dense':state.multi?'M347 352 V422':state.rewrite?'M440 116 H450 Q458 116 458 128 V394 Q458 406 347 406 V422':'M347 223 H450 Q458 223 458 236 V394 Q458 406 347 406 V422',
      'to-sparse':state.multi?'M255 296 H233 Q223 296 223 309 V393 Q223 405 211 405 H124 Q112 405 112 417 V422':state.rewrite?'M347 172 V193 Q347 207 333 207 H233 Q223 207 223 220 V393 Q223 405 211 405 H124 Q112 405 112 417 V422':'M112 172 V422',
      'rewrite-hyde':'M255 116 H233 Q223 116 223 129 V284 Q223 296 208 296',
      'hyde-dense':'M112 352 V372 Q112 383 124 383 H335 Q347 383 347 395 V422',
      'dense-fusion':'M347 537 V562 Q347 575 335 575 H124 Q112 575 112 587 V602',
      'sparse-fusion':'M112 537 V602',
      'fusion-deep':state.deep?'M205 661 H252':state.rerank?'M112 717 V741 Q112 752 124 752 H335 Q347 752 347 764 V782':'M112 717 V782',
      'deep-rerank':state.rerank?'M347 717 V782':'M347 717 V738 Q347 750 335 750 H124 Q112 750 112 762 V782',
      'deep-loop':sp?'M440 661 H450 Q458 661 458 648 V562 Q458 551 446 551 H124 Q112 551 112 540':'M440 661 H450 Q458 661 458 648 V562 Q458 551 446 551 H359 Q347 551 347 540',
      'rerank-context':'M255 841 H208',
      'context-generate':'M112 897 V977',
      'generate-output':'M205 1036 H252',
      'greeting-route':'M20 116 H13 Q7 116 7 129 V1023 Q7 1036 17 1036',
    };
    connections.forEach((c) => {c.d=compactPaths[c.id];});
  }
  const endpoints = {
    'input-rewrite':['input','rewrite'],'rewrite-out':['rewrite','multi'],
    'rewrite-bypass':['input','multi'],'rewrite-multi':['rewrite','multi'],
    'to-dense':[state.multi?'multi':state.rewrite?'rewrite':'input','dense'],
    'to-sparse':[state.multi?'multi':state.rewrite?'rewrite':'input','sparse'],
    'rewrite-hyde':['rewrite','hyde'],'hyde-dense':['hyde','dense'],
    'dense-fusion':['dense','fusion'],'sparse-fusion':['sparse','fusion'],
    'fusion-deep':['fusion',state.deep?'deep':state.rerank?'rerank':'context'],
    'deep-rerank':['deep',state.rerank?'rerank':'context'],
    'deep-loop':['deep',sp?'sparse':'dense'],'rerank-context':['rerank','context'],
    'context-generate':['context','generate'],'generate-output':['generate','output'],
    'greeting-route':['input','generate'],
  };
  // Preserve edge groups so enabling a branch can animate without redrawing the graph.
  const ns='http://www.w3.org/2000/svg';
  for (const c of connections) {
    let group=$(`[data-link="${c.id}"]`);
    const existed=!!group;
    const wasActive=group?.classList.contains('is-active');
    if(!group){group=document.createElementNS(ns,'g');group.dataset.link=c.id;group.classList.add('edge-bundle');group.innerHTML='<path class="edge-halo"/><path class="connection"/><circle class="travel-dot" r="3.5"><animateMotion dur=".85s" repeatCount="indefinite" calcMode="paced"/></circle>';$('#pipeline-paths').append(group);}
    const path=group.querySelector('.connection');
    const previous=path.getAttribute('d');
    const [from,to]=endpoints[c.id];
    group.dataset.from=from;group.dataset.to=to;
    group.classList.toggle('is-active',c.on);
    group.style.display=c.hidden?'none':'';
    group.querySelector('.edge-halo').setAttribute('d',c.d);
    path.dataset.edge=c.id;
    path.setAttribute('d',c.d);
    path.setAttribute('class',`connection ${c.on?'enabled':'inactive'} ${c.optional?'optional':''} ${c.loop?'loop':''}`);
    group.querySelector('animateMotion').setAttribute('path',c.d);
    if(existed && c.on && (!wasActive || previous!==c.d)){group.classList.add('edge-arriving');setTimeout(()=>group.classList.remove('edge-arriving'),700);}
  }
  $('#pipeline-loop-label').classList.toggle('show',state.deep);
}

function highlightConnections(id) {
  $('#pipeline-graph').classList.toggle('is-exploring',!!id);
  const related=new Set(id?[id]:[]);
  root.querySelectorAll('.edge-bundle').forEach((group)=>{
    const match=!!id&&(group.dataset.from===id||group.dataset.to===id);
    group.classList.toggle('is-related',match);
    if(match&&group.classList.contains('is-active')){related.add(group.dataset.from);related.add(group.dataset.to);}
  });
  root.querySelectorAll('.node').forEach((node)=>node.classList.toggle('related',related.has(node.dataset.stage)));
}

function range(key,label,min,max,step,unit,help='') {
    const item=snapshot.items[settingKeys[key]];
    const limits=item?.ui || {};
    const value=state[key];
    min=limits.min ?? Math.min(min,Number.isFinite(value)?value:min);
    max=limits.max ?? Math.max(max,Number.isFinite(value)?value:max);
    const numberStep=item?.type==='float'?'any':1;
    const inputValue=Number.isFinite(value)?value:'';
    return `<div class="field"><label for="pipeline-field-${key}"><span>${label}</span><output for="pipeline-field-${key}" data-output="${key}">${inputValue===''?'—':formatValue(key,value,unit)}</output></label><input id="pipeline-field-${key}" type="range" data-key="${key}" data-unit="${unit}" min="${min}" max="${max}" step="${step}" value="${inputValue}"><div class="range-labels"><span>${min.toLocaleString('ru-RU')}</span><span>${max.toLocaleString('ru-RU')} ${unit}</span></div><label class="sr-only" for="pipeline-number-${key}">${label}: точное значение</label><input class="pipeline-number" id="pipeline-number-${key}" type="number" data-key="${key}" data-unit="${unit}" step="${numberStep}" ${limits.min!==undefined?`min="${limits.min}"`:''} ${limits.max!==undefined?`max="${limits.max}"`:''} value="${inputValue}">${help?`<p class="field-help">${help}</p>`:''}</div>`;
}

function formatValue(key,value,unit) { return `${Number(value).toLocaleString('ru-RU',{maximumFractionDigits:2})}${unit ? ` ${unit}` : ''}`; }
function toggle(key,label,inline=false) { return `<div class="toggle-row ${inline ? 'inline-toggle' : ''}"><span>${label}</span><button class="switch" type="button" role="switch" aria-label="${label}" aria-checked="${state[key]}" data-toggle="${key}"></button></div>`; }
function select(key,label,options) { return `<div class="field"><label for="pipeline-field-${key}">${label}</label><select id="pipeline-field-${key}" data-key="${key}">${options.map(([v,l]) => `<option value="${v}" ${state[key] === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>`; }
function example(label,body) { return `<div class="example-box"><div class="example-label">${label}</div>${body}</div>`; }

function stageVisual(id) {
  const numericKeys={multi:['variants'],deep:['iterations'],context:['topK','context'],output:['citations']}[id] || [];
  if(numericKeys.some(key=>!Number.isFinite(state[key])))return example('Предпросмотр','<p>Укажите числовые параметры для предпросмотра.</p>');
  switch(id) {
    case 'rewrite':
      return example('Вопрос становится самостоятельным',`<div class="rewrite-visual"><div class="speech before"><span class="speech-label">РЕПЛИКА В ЧАТЕ</span><p>А как подключить его по Bluetooth?</p></div><div class="rewrite-bridge">${icon('arrow')}<span>Учитываем историю</span></div><div class="speech after"><span class="speech-label">ПОИСКОВЫЙ ЗАПРОС</span><p>Подключение <mark>принтера к ТСД</mark> по Bluetooth</p></div></div>`);
    case 'multi': {
      const variants=['Подключение принтера к терминалу','Параметры печати с ТСД','Настройка мобильной печати','Печать с терминала по Bluetooth'];
      return example('Один вопрос · несколько формулировок',`<div class="query-fan"><div class="fan-source">${icon('chat')}<span>Как настроить принтер на ТСД?</span></div><div class="fan-list">${variants.slice(0,state.variants).map((text,i)=>`<div class="fan-query" style="--item:${i}"><span class="query-index">0${i+1}</span><span>${text}</span></div>`).join('')}</div><div class="fan-total"><span class="state-dot"></span>${state.variants+1} ${plural(state.variants+1,'запрос','запроса','запросов')} участвуют в поиске</div></div>`);
    }
    case 'rerank':
      return example('Как меняется порядок',`<div class="rank-example is-playing"><div class="rank-column"><span class="visual-small-label">НАЙДЕНО</span><div class="rank-before"><div class="doc-row"><b>А</b><span>Общие параметры</span></div><div class="doc-row"><b>Б</b><span>Подключение ТСД</span></div><div class="doc-row"><b>В</b><span>Настройка печати</span></div></div></div><div class="rank-column"><span class="visual-small-label">ПОСЛЕ ОЦЕНКИ</span><div class="rank-after"><div class="rank-item best" style="--from:2;--to:0"><b>В</b><span>Настройка печати</span>${icon('arrow')}</div><div class="rank-item" style="--from:1;--to:1"><b>Б</b><span>Подключение ТСД</span></div><div class="rank-item" style="--from:0;--to:2"><b>А</b><span>Общие параметры</span></div></div></div></div><button class="replay-demo" type="button" data-rank-demo>${icon('reset')}Показать перестановку</button><span class="visual-disclaimer">Условный пример</span>`);
    case 'dense':
      return example('Разные слова · близкий смысл',`<div class="semantic-visual"><div class="semantic-query">Терминал не печатает</div><div class="semantic-link"><span></span>${icon('search')}<span></span></div><div class="semantic-match">${icon('book')}Настройка печати на ТСД</div></div>`);
    case 'sparse':
      return example('Точный термин в документации',`<div class="keyword-query">Запрос <b>«Ошибка E104»</b></div><div class="document-snippet"><span class="visual-small-label">ФРАГМЕНТ СТАТЬИ</span><p>При появлении <mark>ошибки E104</mark> проверьте параметры подключения…</p><div class="document-line"></div><div class="document-line short"></div></div><span class="visual-disclaimer">Условный пример</span>`);
    case 'fusion':
      return example('Общий список без повторов',`<div class="fusion-inputs"><span>По смыслу <b>А · Б · В</b></span><span>По словам <b>Б · В · Г</b></span></div><div class="fusion-join">${icon('merge')}</div><div class="fusion-result"><span>А</span><span>Б</span><span>В</span><span>Г</span><small>4 уникальных</small></div>`);
    case 'deep':
      return example('Поиск с обратной связью',`<div class="deep-visual"><div>${icon('search')}<span>Первичный поиск</span></div><div class="deep-condition">Данных достаточно?</div><div class="deep-options"><span>${icon('check')}Да → к ответу</span><span>${icon('reset')}Нет → ещё поиск</span></div><span class="deep-limit">Не больше ${state.iterations} итераций</span></div>`);
    case 'context':
      return example('Что попадёт в контекст',`<div class="context-visual"><div class="paper-stack"><div></div><div></div><div>${icon('book')}<b>${state.topK}</b><span>фрагментов</span></div></div><div class="context-budget"><strong>${Math.round(state.context/1000)} тыс.</strong><span>знаков максимум</span><small>${state.visual?'Текст + изображения':'Только текст'}</small></div></div>`);
    case 'generate':
      return example('Из знаний — в ответ',`<div class="generation-inputs"><span>Вопрос</span><span>История</span><span>Контекст</span></div><div class="generation-engine">${icon('spark')}<span>Модель формирует ответ</span></div><div class="generation-output"><div class="document-line"></div><div class="document-line"></div><div class="document-line short"></div></div>`);
    case 'output':
      return example('Ответ с опорой на источники',`<div class="answer-preview"><div class="answer-preview-title">${icon('check')}Готово к отправке</div><div class="document-line"></div><div class="document-line"></div><div class="document-line short"></div><div class="citation-preview">${Array.from({length:Math.min(state.citations,4)},(_,i)=>`<span>[${i+1}]</span>`).join('')}<small>Источники</small></div></div>`);
    default:return '';
  }
}

function updateVisualExample() {
  const holder=$('#pipeline-stage-visual');
  if(holder){const visual=stageVisual(selected);if(visual)holder.innerHTML=visual;}
}

function renderInspector() {
  const s = stageById[selected];
  let fields = '', demo = '', note = '';
  const searchFields = () => select('mode','Как искать', [['hybrid','Гибридный · смысл + слова'],['dense','Только по смыслу'],['sparse','Только по словам']]) + range('candidates','Кандидатов для объединения',5,50,5,'','Размер пула перед объединением и удалением повторов.');
  switch (s.id) {
    case 'input':
      fields = toggle('chitchat','Приветствия без поиска',true);
      demo = example('Два возможных маршрута','<p><strong>«Как настроить принтер?»</strong><br>→ Поиск по базе знаний</p><div class="example-arrow">или</div><p><strong>«Привет!»</strong><br>→ Короткий ответ без поиска</p>');
      note = 'Маршрутизация приветствий действует только без вложений. В демо можно проверить пример «Приветствие».';break;
    case 'rewrite':
      fields = range('history','Глубина истории',1,20,1,'сообщ.','Сколько последних сообщений учитывать при подготовке поискового запроса.');
      demo = example('Как меняется поисковый запрос','<p>«А как подключить его по Bluetooth?»</p><div class="example-arrow">'+icon('arrow')+' с учётом истории</div><p><strong>«Подключение принтера к ТСД по Bluetooth»</strong></p>');
      note = 'Срабатывает, только когда в диалоге есть история. Исходный вопрос пользователя сохраняется.';break;
    case 'multi':
      fields = range('variants','Дополнительных формулировок',1,4,1,'','Максимум дополнительных поисковых запросов, помимо исходного.');
      demo = example('Один вопрос — несколько путей','<p>1. Как настроить принтер на ТСД?<br>2. Подключение принтера к терминалу<br>3. Параметры печати с ТСД<br>4. Настройка мобильной печати</p>');
      note = 'Количество задаёт верхнюю границу: модель может вернуть меньше уникальных формулировок. Исходный запрос участвует в поиске отдельно.';break;
    case 'hyde':
      demo = example('Текст для поиска','<p>«Для настройки принтера на терминале сбора данных откройте параметры печати и выберите тип подключения…»</p>');
      note = 'Гипотеза используется только в поиске по смыслу. При поиске только по словам включённый этап всё равно вызывает модель, но его результат не участвует в поиске.';break;
    case 'dense': case 'sparse':
      fields = searchFields();
      demo = example(s.id === 'dense' ? 'Смысловая близость' : 'Точное совпадение',s.id === 'dense' ? '<p>«Терминал не печатает»<br>→ «Настройка печати на ТСД»</p>' : '<p>«Ошибка E104»<br>→ статьи с термином «E104»</p>');
      note = 'В гибридном режиме обе ветки участвуют в поиске, а результаты объединяются через RRF.';break;
    case 'fusion':
      fields = searchFields();
      demo = example('Объединение RRF','<p>Поиск по смыслу + поиск по словам<br>↓<br>Общий список без повторов</p>');
      note = 'Значения score у разных способов поиска отличаются. Порог релевантности лучше подбирать на примерах из вашей базы.';break;
    case 'deep':
      fields = range('iterations','Максимум итераций',2,5,1,'','Включая первичный поиск. При достаточном результате цикл завершается раньше.') + range('newQueries','Новых запросов за итерацию',1,4,1,'');
      note = 'Петля показана укрупнённо. Реальный глубокий поиск повторяет извлечение и ранжирование в каждой итерации; в демонстрации моделируется один повтор.';break;
    case 'rerank':
      fields = range('rankTop','Кандидатов для оценки',5,50,5,'фрагм.');
      demo = example('Повторная оценка','<p>Каждый кандидат оценивается вместе с вопросом.<br>Более подходящие фрагменты поднимаются выше.</p>');
      note = 'Если модель недоступна или превышен таймаут, алгоритм использует исходный порядок.';break;
    case 'context':
      fields = range('topK','Фрагментов в контексте',1,50,1,'') + range('context','Лимит контекста',10000,120000,5000,'зн.') + range('minScore','Минимальный score',0,1,.05,'') + toggle('visual','Изображения из вики',true);
      note = 'Число фрагментов и порог могут переопределяться в панели чата. Схема показывает серверные значения по умолчанию. Изображения требуют поддержки vision-моделью.';break;
    case 'generate':
      fields = `<div class="model-summary"><span>Модель ответа</span><strong>${esc(state.model)}</strong><button class="replay-demo" type="button" data-open-setting="OLLAMA_CHAT_MODEL">Выбрать модель в настройках</button></div>` + range('tokens','Максимальная длина',1,8192,128,'ток.');
      note = 'Стиль реального ответа задаётся в чате. Стиль в блоке демонстрации ниже влияет только на симуляцию.';
      demo = example('Что получает модель','<p>Исходный вопрос + история<br>+ найденный контекст<br>+ выбранный стиль ответа</p>');break;
    case 'output':
      fields = range('citations','Максимум цитат',0,20,1,'');
      demo = example('Результат обработки','<p>Ответ по найденной документации<br>+ ссылки на источники<br>+ цитаты и изображения</p>');
      note = 'Цитаты добавляются по совпадениям текста с источниками; фактическое количество может быть меньше лимита.';break;
  }
  $('#pipeline-inspector').innerHTML = `<div class="inspector-header"><span>ПАРАМЕТРЫ ЭТАПА</span><button class="back-to-graph" type="button">↑ К схеме</button><span>${s.number}</span></div><div class="inspector-content"><div class="inspector-stage"><div class="inspector-icon">${icon(s.icon)}</div><div><h2>${s.name}</h2><span class="stage-state ${enabled(s.id) ? '' : 'disabled'}"><i class="state-dot"></i>${enabled(s.id) ? (s.id === 'deep' ? 'Включён · по условию' : 'Включён') : 'Пропускается'}</span></div></div><p class="inspector-description">${s.description}</p>${s.toggle ? toggle(s.toggle,'Включить этап') : '<div class="fixed-label">'+(s.id === 'dense' || s.id === 'sparse' ? 'Участие зависит от режима поиска' : 'Основной этап обработки')+'</div>'}<div class="fields">${fields}</div><div id="pipeline-stage-visual">${stageVisual(s.id)||demo}</div>${note ? `<div class="inspector-note">${icon('info')}<span>${note}</span></div>` : ''}</div><div class="inspector-footer"><details><summary>Технические параметры</summary><div class="technical-keys">${s.keys.map((k) => `<button type="button" data-open-setting="${k}"><code>${k}</code></button>`).join('')}</div></details></div>`;
}

function updateDraft() {
    const count = snapshot.dirtyCount || 0;
    $('#pipeline-apply').disabled = !count || snapshot.saving || !snapshot.ready;
    $('#pipeline-reset').disabled = !count || snapshot.saving;
    $('#pipeline-reload').disabled = snapshot.saving || snapshot.loading;
    $('#pipeline-apply span').textContent = snapshot.saving ? 'Сохранение…' : count ? `Применить всё · ${count}` : 'Применено';
    $('#pipeline-draft-status').textContent = count ? `Общий черновик: ${count} изменений` : 'Настройки загружены с сервера';
    $('#pipeline-draft-status').classList.toggle('dirty',!!count);
}
function refresh() { renderNodes(); renderConnections(); updateDraft(); }
function notify(message) {
    clearTimeout(toastTimer); $('#pipeline-toast').textContent=message; $('#pipeline-toast').hidden=false;
    toastTimer=setTimeout(()=>{$('#pipeline-toast').hidden=true;},4000);
}
function setStatus(message) {
    if (!initialized) return;
    $('#pipeline-notice').textContent=message || '';
    $('#pipeline-notice').hidden=!message;
}
function update(next) {
    const wasReady=snapshot.ready;
    snapshot=next;
    if(!initialized) return;
    if(!next.visible && running)cancelRun(false);
    const available=next.ready && next.isAdmin;
    root.querySelectorAll('[data-pipeline-content]').forEach((node)=>{node.hidden=!available;});
    if(!available){
        cancelRun(false);
        state={}; $('#pipeline-nodes').innerHTML=''; $('#pipeline-paths').innerHTML=''; $('#pipeline-inspector').innerHTML='';
        $('#pipeline-trace').innerHTML=''; $('#pipeline-question').value='';
        updateDraft();
        setStatus(next.isAdmin ? next.error || 'Загрузка настроек сервера…' : 'Раздел доступен только администратору.');
        return;
    }
    const previous=JSON.stringify(state);
    for(const [name,key] of Object.entries(settingKeys)){
        const item=next.items[key];
        const raw=Object.prototype.hasOwnProperty.call(next.draft,key)?next.draft[key]:item?.value;
        state[name]=item?.type==='bool' ? raw===true || String(raw).toLowerCase()==='true'
            : item?.type==='int'||item?.type==='float' ? (raw==='' ? NaN : Number(raw)) : String(raw??'');
    }
    state.answerMode=$('#pipeline-demo-mode').value;
    if(running && previous!==JSON.stringify(state))cancelRun(false);
    const active=document.activeElement;
    const editing=active && root.contains(active) && active.matches('input[data-key]');
    refresh();
    if(editing)updateVisualExample();else renderInspector();
    $('#pipeline-inspector').inert=!!next.saving;
    $('#pipeline-run').disabled=!!next.saving;
    setStatus(next.error || (next.loading ? 'Обновление настроек…' : ''));
    if(!wasReady)requestAnimationFrame(fitGraph);
}
function init(callbacks) {
    bridge=callbacks; initialized=true;
}
function changeSetting(key,value,rerender=false) {
    if(!snapshot.ready || snapshot.saving || !settingKeys[key])return;
    cancelRun(false);
    bridge.change(settingKeys[key],value);
    if(rerender)renderInspector();
}
$('#pipeline-nodes').addEventListener('click',(event)=>{
    const node=event.target.closest('[data-stage]');if(!node)return;
    selected=node.dataset.stage;
    root.querySelectorAll('.node').forEach((el)=>{el.classList.toggle('selected',el.dataset.stage===selected);el.setAttribute('aria-pressed',String(el.dataset.stage===selected));});
    renderInspector();
    if(compact)$('#pipeline-inspector').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
});
$('#pipeline-inspector').addEventListener('click',(event)=>{
    if(event.target.closest('.back-to-graph')){$('.board').scrollIntoView({behavior:'smooth',block:'start'});return;}
    const setting=event.target.closest('[data-open-setting]');
    if(setting){bridge.openSetting(setting.dataset.openSetting);return;}
    if(event.target.closest('[data-rank-demo]')){const demo=$('.rank-example');demo.classList.remove('is-playing');void demo.offsetWidth;demo.classList.add('is-playing');return;}
    const toggle=event.target.closest('[data-toggle]');
    if(toggle)changeSetting(toggle.dataset.toggle,!state[toggle.dataset.toggle],true);
});
$('#pipeline-inspector').addEventListener('input',(event)=>{
    const target=event.target;
    if(!target.matches('input[data-key]'))return;
    const key=target.dataset.key;
    const value=target.value===''?'':Number(target.value);
    changeSetting(key,value);
    const output=$(`[data-output="${key}"]`);
    if(output)output.textContent=value===''?'—':formatValue(key,value,target.dataset.unit);
    root.querySelectorAll(`input[data-key="${key}"]`).forEach((input)=>{if(input!==target)input.value=target.value;});
});
$('#pipeline-inspector').addEventListener('change',(event)=>{if(event.target.tagName==='SELECT')changeSetting(event.target.dataset.key,event.target.value,true);});
$('#pipeline-nodes').addEventListener('pointerover',(event)=>{const node=event.target.closest('[data-stage]');if(node&&!node.contains(event.relatedTarget))highlightConnections(node.dataset.stage);});
$('#pipeline-nodes').addEventListener('pointerout',(event)=>{const node=event.target.closest('[data-stage]');if(node&&!node.contains(event.relatedTarget))highlightConnections(null);});
$('#pipeline-nodes').addEventListener('focusin',(event)=>{const node=event.target.closest('[data-stage]');if(node)highlightConnections(node.dataset.stage);});
$('#pipeline-nodes').addEventListener('focusout',()=>highlightConnections(null));
$('#pipeline-apply').addEventListener('click',()=>bridge.save());
$('#pipeline-reset').addEventListener('click',()=>bridge.reset());
$('#pipeline-reload').addEventListener('click',()=>bridge.reload());
$('#pipeline-demo-mode').addEventListener('change',()=>{cancelRun(false);state.answerMode=$('#pipeline-demo-mode').value;refresh();renderInspector();});

function applyTransform() {$('#pipeline-graph').style.transform=`translate(${position.x}px,${position.y}px) scale(${scale})`;$('#pipeline-zoom-value').textContent=`${Math.round(scale*100)}%`;}
function fitGraph() {
  if (!snapshot.ready || root.hidden || !root.classList.contains('active')) return;
  let rect=$('#pipeline-viewport').getBoundingClientRect();
  if (rect.width < 1) return;
  const nextCompact=rect.width<820;
  if(nextCompact!==compact){compact=nextCompact;$('#pipeline-graph').classList.toggle('compact',compact);$('#pipeline-connections').setAttribute('viewBox',compact?'0 0 470 1130':'0 0 1160 610');refresh();}
  if(compact){
    scale=Math.min((rect.width-20)/470,1.15);
    $('#pipeline-viewport').style.height=`${1130*scale+45}px`;
    position={x:(rect.width-470*scale)/2,y:12};
  }else{
    $('#pipeline-viewport').style.height='';rect=$('#pipeline-viewport').getBoundingClientRect();
    scale=Math.min((rect.width-30)/1160,(rect.height-55)/610,1.25);
    position={x:(rect.width-1160*scale)/2,y:Math.max(9,(rect.height-35-610*scale)/2)};
  }
  applyTransform();
}
function zoom(amount) {
  const rect=$('#pipeline-viewport').getBoundingClientRect();
  const next=Math.max(.3,Math.min(1.7,scale+amount));
  const ratio=next/scale;
  position={x:rect.width/2-(rect.width/2-position.x)*ratio,y:rect.height/2-(rect.height/2-position.y)*ratio};
  scale=next;applyTransform();
}
$('#pipeline-zoom-in').addEventListener('click',() => zoom(.1));$('#pipeline-zoom-out').addEventListener('click',() => zoom(-.1));$('#pipeline-fit').addEventListener('click',fitGraph);
let drag=null;
$('#pipeline-viewport').addEventListener('pointerdown',(event) => {
  if(event.target.closest('button') || event.button!==0)return;
  drag={pointer:event.pointerId,x:event.clientX-position.x,y:event.clientY-position.y};
  $('#pipeline-viewport').setPointerCapture(event.pointerId);$('#pipeline-viewport').classList.add('dragging');
});
$('#pipeline-viewport').addEventListener('pointermove',(event) => {if(!drag)return;position={x:event.clientX-drag.x,y:event.clientY-drag.y};applyTransform();});
const stopDrag=() => {drag=null;$('#pipeline-viewport').classList.remove('dragging');};
$('#pipeline-viewport').addEventListener('pointerup',stopDrag);$('#pipeline-viewport').addEventListener('pointercancel',stopDrag);
$('#pipeline-viewport').addEventListener('wheel',(event) => {if(!event.ctrlKey&&!event.metaKey)return;event.preventDefault();zoom(event.deltaY>0?-.06:.06);},{passive:false});
new ResizeObserver(fitGraph).observe($('#pipeline-viewport'));

function nodeState(id,css) {const el=$(`[data-stage="${id}"]`);if(el)el.classList.add(css);}
function clearRunVisuals() {root.querySelectorAll('.node').forEach((el) => el.classList.remove('running','done','skipped'));root.querySelectorAll('.connection').forEach((el) => el.classList.remove('running','complete'));const greeting=$('[data-link="greeting-route"]');if(greeting)greeting.style.display='none';highlightConnections(null);}
function setRunButton(active) {$('#pipeline-run span').textContent=active?'Остановить':'Показать путь';$('#pipeline-run use').setAttribute('href',active?'#pipeline-i-stop':'#pipeline-i-play');$('#pipeline-running-badge').hidden=!active;$('#pipeline-with-history').disabled=active;}
function cancelRun(showMessage=true) {
  runId++;
  if(!running){clearRunVisuals();return;}
  running=false;setRunButton(false);clearRunVisuals();
  $('#pipeline-run-status').textContent='Демонстрация остановлена';
  if(showMessage)notify('Демонстрация остановлена.');
}
function addTrace(title,body,tag='ДЕМО') {
  const item=document.createElement('article');item.className='trace-item';
  item.innerHTML=`<h3>${esc(title)}<span>${esc(tag)}</span></h3><p>${esc(body)}</p>`;
  $('#pipeline-trace').append(item);
}
const pause=(ms) => new Promise((resolve) => setTimeout(resolve,ms));
async function step(id,title,body,edges,token) {
  if(token!==runId)return false;
  root.querySelectorAll('.node.running').forEach((el) => {el.classList.remove('running');el.classList.add('done');});
  root.querySelectorAll('.connection.running').forEach((el) => {el.classList.remove('running');el.classList.add('complete');});
  if(id){nodeState(id,'running');selected=id;root.querySelectorAll('.node').forEach((el) => {el.classList.toggle('selected',el.dataset.stage===id);el.setAttribute('aria-pressed',String(el.dataset.stage===id));});renderInspector();}
  for(const edge of edges||[])$(`[data-edge="${edge}"]`)?.classList.add('running');
  $('#pipeline-running-badge span:last-child').textContent=title;
  $('#pipeline-run-status').textContent=title;
  if(body)addTrace(title,body);
  await pause(matchMedia('(prefers-reduced-motion: reduce)').matches?130:900);
  return token===runId;
}
async function runDemo() {
  if(running){cancelRun();return;}
  const question=$('#pipeline-question').value.trim();if(!question){$('#pipeline-question').focus();return;}
  clearRunVisuals();running=true;const token=++runId;const config={...state};
  setRunButton(true);$('#pipeline-run-output').hidden=false;$('#pipeline-trace').innerHTML='';
  const hasHistory=$('#pipeline-with-history').checked;
  const greeting=config.chitchat && /^(привет[!.,\s]*|здравствуй(?:те)?[!.,\s]*|добрый (день|вечер|утро)[!.,\s]*)$/i.test(question);
  const followup=/\bBluetooth\b/i.test(question)||/^а\s/i.test(question);
  const printer=/принтер|тсд|bluetooth|терминал/i.test(question);
  let base=question;
  const next=async(id,title,body,edges=[]) => step(id,title,body,edges,token);
  if(!await next('input','Вопрос принят',question))return;
  if(greeting){
    $('[data-link="greeting-route"]').style.display='';
    stages.filter((s) => !['input','generate','output'].includes(s.id)).forEach((s) => nodeState(s.id,'skipped'));
    if(!await next('generate','Короткий ответ без поиска','Приветствие направлено сразу на генерацию ответа. База знаний не используется.',['greeting-route']))return;
    if(!await next('output','Ответ готов','Привет! Чем могу помочь?',['generate-output']))return;
  }else{
    if(config.rewrite&&hasHistory){
      base=printer&&followup?'Как подключить принтер к терминалу сбора данных по Bluetooth?':question;
      if(!await next('rewrite','Вопрос дополнен историей',base===question?'В этом примере вопрос уже самодостаточный. Формулировка сохранена.':base,['input-rewrite']))return;
    }else{
      nodeState('rewrite','skipped');
      addTrace('Дополнение пропущено',config.rewrite?'В тесте отключена история диалога. Используется исходный вопрос.':'Этап выключен. Используется исходный вопрос.','ПРОПУСК');
    }
    if(config.multi){
      const variants=printer?['Настройка печати с терминала сбора данных','Подключение мобильного принтера к ТСД','Параметры Bluetooth-печати на терминале','Инструкция по настройке принтера ТСД']:[`Инструкция: ${base}`,`Порядок действий по теме: ${base}`,`Решение вопроса: ${base}`,`Справка по теме: ${base}`];
      if(!await next('multi',`Подготовлено ${config.variants} дополнительных запроса`,[base,...variants.slice(0,config.variants)].map((q,i) => `${i+1}. ${q}`).join('\n'),['rewrite-multi']))return;
    }else nodeState('multi','skipped');
    if(config.hyde){
      if(!await next('hyde','Подготовлен поисковый пример',config.mode==='sparse'?'Гипотеза создана, но при поиске только по словам не используется.':'Условный фрагмент ответа используется как дополнительный запрос векторного поиска. Это не найденный источник.',['rewrite-hyde']))return;
    }else nodeState('hyde','skipped');
    if(config.mode!=='sparse'){
      if(!await next('dense','Поиск по смыслу',`Демо: отбираются семантически близкие фрагменты. Лимит кандидатов: ${config.candidates}.`,['to-dense',...(config.hyde?['hyde-dense']:[])]))return;
    }else nodeState('dense','skipped');
    if(config.mode!=='dense'){
      if(!await next('sparse','Поиск по словам','Демо: поиск совпадений по ключевым словам и терминам BM25.',['to-sparse']))return;
    }else nodeState('sparse','skipped');
    if(!await next('fusion','Результаты объединены',config.mode==='hybrid'?'Демонстрационное объединение двух веток через RRF и удаление повторов.':'Используется одна ветка поиска. Повторы удаляются.',[...(config.mode!=='sparse'?['dense-fusion']:[]),...(config.mode!=='dense'?['sparse-fusion']:[])]))return;
    if(config.deep){
      if(!await next('deep','Проверка полноты поиска',`Демо: моделируется недостаток данных и один дополнительный поиск. Лимит — ${config.iterations} итерации.`,['fusion-deep']))return;
      const searchNode=config.mode==='sparse'?'sparse':'dense';
      if(!await next(searchNode,'Дополнительная итерация',`Добавлены уточняющие запросы (до ${config.newQueries}). В этом примере после повтора поиск завершается.`,['deep-loop']))return;
    }else nodeState('deep','skipped');
    if(config.rerank){
      if(!await next('rerank','Фрагменты переоценены',`Демо: cross-encoder уточняет порядок кандидатов (до ${config.rankTop} фрагментов).`,config.deep?['deep-rerank']:['fusion-deep']))return;
    }else nodeState('rerank','skipped');
    if(!await next('context','Контекст собран',`До ${config.topK} фрагментов, лимит ${config.context.toLocaleString('ru-RU')} знаков. ${config.visual?'Изображения включены при наличии подходящих источников.':'Изображения отключены.'}`,[config.rerank?'rerank-context':config.deep?'deep-rerank':'fusion-deep']))return;
    if(!await next('generate','Формируется ответ',`Исходный вопрос: «${question}»\nСтиль: ${config.answerMode==='instruction'?'инструкция':config.answerMode==='brief'?'краткий ответ':'обычный ответ'}. Лимит: ${config.tokens} токенов.`,['context-generate']))return;
    const answer=printer?(config.answerMode==='brief'?'Подключите принтер к ТСД, выберите его в настройках печати и выполните тестовую печать.':config.answerMode==='instruction'?'1. Подключите принтер к терминалу.\n2. Откройте настройки печати на ТСД.\n3. Выберите устройство и выполните тестовую печать.':'Для печати с ТСД необходимо подключить принтер и выбрать его в настройках терминала. После настройки проверьте соединение тестовой печатью.'):`На этом этапе модель сформировала бы ответ на вопрос «${question}» по найденным фрагментам вики.`;
    if(!await next('output','Демонстрационный ответ',answer+'\n\nЭто условный пример результата, а не инструкция из вашей базы.', ['generate-output']))return;
  }
  if(token!==runId)return;
  root.querySelectorAll('.node.running').forEach((el) => {el.classList.remove('running');el.classList.add('done');});
  root.querySelectorAll('.connection.running').forEach((el) => {el.classList.remove('running');el.classList.add('complete');});
  running=false;setRunButton(false);$('#pipeline-run-status').textContent='Маршрут пройден · демонстрация завершена';
}
$('#pipeline-run-form').addEventListener('submit',(event) => {event.preventDefault();runDemo();});
$('#pipeline-close-output').addEventListener('click',() => {cancelRun(false);$('#pipeline-run-output').hidden=true;});
root.querySelectorAll('[data-question]').forEach((button) => button.addEventListener('click',() => {cancelRun(false);$('#pipeline-question').value=button.dataset.question;$('#pipeline-question').focus();}));
document.addEventListener('keydown',(event) => {if(root.classList.contains('active') && event.key==='Escape'){if(running)cancelRun();$('#pipeline-toast').hidden=true;}});

window.AdminPipelineUI = {init, update, setStatus};
})();
