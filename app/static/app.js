const $ = id => document.getElementById(id);
let selected, job, pageIndex = 0, pollTimer, proofTimer, dirty = false;
function notice(text) { $('notice').textContent = text; $('notice').hidden = false; clearTimeout(notice.timer); notice.timer = setTimeout(() => $('notice').hidden = true, 6500); }
async function api(url, options = {}) { const res = await fetch(url, options); if (!res.ok) { let data; try { data = await res.json(); } catch {} throw Error(typeof data?.detail === 'string' ? data.detail : `请求失败 (${res.status})`); } return res.json(); }
function choose(file) { if (!file) return; if (!file.name.toLowerCase().endsWith('.pdf')) return notice('请选择 PDF 文件'); selected = file; $('file-label').textContent = `${file.name} · ${(file.size / 1048576).toFixed(1)} MB`; $('convert').disabled = false; }
$('dropzone').onclick = () => $('file').click();
$('dropzone').onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') {e.preventDefault(); $('file').click();} };
$('file').onchange = e => choose(e.target.files[0]);
$('dropzone').ondragover = e => { e.preventDefault(); $('dropzone').classList.add('drag'); };
$('dropzone').ondragleave = () => $('dropzone').classList.remove('drag');
$('dropzone').ondrop = e => {e.preventDefault(); $('dropzone').classList.remove('drag'); choose(e.dataTransfer.files[0]);};
async function history() { try { const items = await api('/api/jobs'); $('history').replaceChildren(); for (const item of items) { const b = document.createElement('button'); b.className = 'history-item'; b.textContent = '▤  ' + item.title; b.title = item.title; b.onclick = () => openJob(item.id); $('history').append(b); } } catch(e) { notice(e.message); } }
$('new-book').onclick = async () => { if(dirty) {try {await save();} catch(e){return notice(e.message);}} clearTimeout(pollTimer); clearTimeout(proofTimer); job = null; $('upload-view').hidden = false; $('job-view').hidden = true; };
$('convert').onclick = async () => { if(!selected) return; const body = new FormData(); body.append('file', selected); body.append('start', $('start').value || 1); body.append('end', $('end').value || 0); body.append('dpi', $('dpi').value); body.append('correct_scan', $('correct-scan').checked); $('convert').disabled = true; $('convert').textContent = '正在上传…'; try { const data = await api('/api/jobs', {method:'POST', body}); await openJob(data.id); history(); } catch(e) {notice(e.message);} finally {$('convert').disabled = false; $('convert').textContent = '开始识别 →';} };
async function openJob(id) { try { if(dirty) await save(); clearTimeout(pollTimer); clearTimeout(proofTimer); job = await api(`/api/jobs/${id}`); pageIndex = 0; dirty = false; $('upload-view').hidden = true; $('job-view').hidden = false; renderJob(); refreshModels(); scheduleProof(); if(['queued','running'].includes(job.status)) pollTimer = setTimeout(poll, 1500); } catch(e) {notice(e.message);} }
async function poll() { const id = job?.id; if(!id) return; try {const fresh = await api(`/api/jobs/${id}`); if(job?.id !== id) return; job = fresh; renderJob(); if(['queued','running'].includes(job.status)) pollTimer = setTimeout(poll, 1800); else history();} catch(e){notice(e.message); pollTimer = setTimeout(poll, 4000);} }
function renderJob() { $('job-title').textContent = job.title; $('status').textContent = `${job.message}  ${job.completed} / ${job.total}`; $('progress').style.width = `${job.completed/job.total*100}%`; const busy = ['queued','running'].includes(job.status); $('cancel').hidden = !busy; $('editor').hidden = busy || !job.pages.length; $('step2').classList.add('on'); $('step3').classList.toggle('on', !busy && !!job.pages.length); if(!busy && job.pages.length) {$('book-title').value = job.title; renderPage();} }
function renderPage() { const page = job.pages[pageIndex]; renderCorrection(page); $('page-label').textContent = `第 ${page.number} 页`; $('page-counter').textContent = `${pageIndex+1} / ${job.pages.length}`; $('prev').disabled = pageIndex === 0; $('next').disabled = pageIndex === job.pages.length-1; $('retain').checked = page.retain_original; $('blocks').replaceChildren(); renderFigures(page); if(!page.blocks.length) { const p = document.createElement('p'); p.textContent = '本页未识别出文字，将自动保留扫描图。'; $('blocks').append(p); } for(const block of page.blocks) {const div = document.createElement('div'); div.className = 'block' + (block.confidence < .85 ? ' low' : ''); const top = document.createElement('div'); top.className = 'block-top'; const select = document.createElement('select'); select.setAttribute('aria-label','段落类型'); for(const [value, label] of [['paragraph','正文'],['heading','标题'],['grid','网格'],['omit','忽略']]) {const opt = document.createElement('option'); opt.value=value; opt.textContent=label; select.append(opt);} select.value=block.kind; select.onchange=()=>{block.kind=select.value; dirty=true; renderPage();}; const score=document.createElement('span'); score.textContent = `识别置信度 ${Math.round(block.confidence*100)}%`; top.append(select, score); const area=document.createElement('textarea'); area.setAttribute('aria-label','校对文字'); area.value=block.text; area.rows = Math.min(12, Math.max(2, Math.ceil(block.text.length/24))); area.oninput=()=>{block.text=area.value; dirty=true;renderToc();}; div.append(top, area); if(block.kind === 'grid') { const help=document.createElement('small'); help.textContent='每行是一排，Tab 分列；下方可逐格校对。修改上方文本后移开焦点更新网格。'; div.append(help); const cells=document.createElement('div'); cells.className='grid-cells'; div.append(cells); renderGridEditor(block,cells,area); area.onchange=()=>renderGridEditor(block,cells,area); area.onkeydown=e=>{if(e.key==='Tab' && !e.shiftKey){e.preventDefault();area.setRangeText('\t',area.selectionStart,area.selectionEnd,'end');block.text=area.value;dirty=true;}}; } if(block.proofread_history?.length) { const details=document.createElement('details'), summary=document.createElement('summary'); summary.textContent='查看智能校对记录'; details.append(summary); for(const h of block.proofread_history) { const record=document.createElement('p'); record.style.whiteSpace='pre-wrap'; record.textContent=`${h.undone?'已撤销':'修改记录'}\n修改前：${h.before}\n修改后：${h.after}`; details.append(record); } div.append(details); } if(['heading','paragraph'].includes(block.kind)) { const add=document.createElement('button');add.className='secondary toc-add';add.textContent='加入章节目录';add.onclick=()=>{const index=page.blocks.indexOf(block);job.toc ??= [];let entry=job.toc.find(e=>e.page===page.number && e.block===index);if(entry)entry.included=true;else job.toc.push({page:page.number,block:index,title:'',level:1,included:true});dirty=true;renderToc();};div.append(add); } $('blocks').append(div); } renderToc(); renderProof(); }
$('prev').onclick=()=>{pageIndex--; renderPage();}; $('next').onclick=()=>{pageIndex++; renderPage();};
$('retain').onchange=()=>{job.pages[pageIndex].retain_original=$('retain').checked;dirty=true;};
$('book-title').oninput=()=>{dirty=true;};
async function save() { const title = $('book-title').value.trim(); if(!title) throw Error('请输入书名'); const saved = await api(`/api/jobs/${job.id}`, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,toc:job.toc,revision:job.revision ?? 0,pages:job.pages.map(p=>({number:p.number,retain_original:p.retain_original,figures:(p.figures || []).map(f=>({id:f.id,included:f.included,before_block:f.before_block,caption:f.caption || ''})),blocks:p.blocks.map(b=>({kind:b.kind,text:b.text}))}))})}); job.revision=saved.revision; job.title=title; dirty=false; $('job-title').textContent=title; }
$('save').onclick=async()=>{try{await save();notice('校对已保存');history();}catch(e){notice(e.message);}};
$('cancel').onclick=async()=>{try{await api(`/api/jobs/${job.id}/cancel`,{method:'POST'});clearTimeout(pollTimer);await poll();}catch(e){notice(e.message);}};
async function exportBook(format) { $('pdf').disabled=$('epub').disabled=true; notice('正在排版并嵌入字体…'); try {await save(); const data=await api(`/api/jobs/${job.id}/export`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({format,font_size:Number($('font-size').value),leading:Number($('leading').value),page_size:$('page-size').value,include_originals:$('originals').checked})}); const a=document.createElement('a'); a.href=data.url; a.download=''; document.body.append(a); a.click(); a.remove(); notice('已生成，下载即将开始');}catch(e){notice(e.message);}finally{$('pdf').disabled=$('epub').disabled=false;} }
$('pdf').onclick=()=>exportBook('pdf');$('epub').onclick=()=>exportBook('epub');
window.onbeforeunload=e=>{if(dirty){e.preventDefault();e.returnValue='';}};
history();


function renderFigures(page) {
  const figures = page.figures || [];
  $('figures').replaceChildren();
  $('detect-figures').disabled = !!page.figures_detected;
  $('detect-figures').textContent = page.figures_detected ? '检测完成' : '检测插图';
  $('figures-note').textContent = !page.figures_detected ? '旧任务可点击检测插图，无需重新识别文字。' :
    figures.length ? `发现 ${figures.length} 个候选区域。请确认裁切内容；可取消误检或调整插入位置。` : '未检测到插图；若有遗漏，可手动框选。';
  figures.forEach((figure, index) => {
    const card = document.createElement('div'); card.className = 'figure-card';
    const image = document.createElement('img');
    image.src = `/api/jobs/${job.id}/pages/${page.number}/figures/${figure.id}`;
    image.alt = `插图 ${index + 1} 裁切预览`;
    const keep = document.createElement('label'); keep.className = 'check';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = figure.included;
    checkbox.onchange = () => { figure.included = checkbox.checked; dirty = true; };
    keep.append(checkbox, document.createTextNode(`保留插图 ${index + 1}${figure.method === 'manual' ? ' · 手动框选' : ' · 自动检测'}`));
    const position = document.createElement('select'); position.setAttribute('aria-label', `插图 ${index+1} 插入位置`);
    for (let i = 0; i <= page.blocks.length; i++) {
      const option = document.createElement('option'); option.value = i;
      option.textContent = i === page.blocks.length ? '本页正文之后' : `第 ${i+1} 段之前：${page.blocks[i].text.slice(0,18)}`;
      position.append(option);
    }
    position.value = figure.before_block;
    position.onchange = () => { figure.before_block = Number(position.value); dirty = true; };
    const caption = document.createElement('input'); caption.placeholder = '图片说明（可选）'; caption.maxLength = 1000;
    caption.setAttribute('aria-label', `插图 ${index+1} 说明`); caption.value = figure.caption || '';
    caption.oninput = () => { figure.caption = caption.value; dirty = true; };
    card.append(image, keep, position, caption); $('figures').append(card);
  });
}
$('detect-figures').onclick = async () => {
  const id = job.id, index = pageIndex, page = job.pages[index];
  $('detect-figures').disabled = true;
  try {
    await save();
    const updated = await api(`/api/jobs/${id}/pages/${page.number}/figures/detect`, {method:'POST'});
    if (job?.id === id) { job.pages[index] = updated; if (pageIndex === index) renderFigures(updated); }
    notice(`检测完成，发现 ${(updated.figures || []).length} 个候选区域`);
  } catch (e) { notice(e.message); $('detect-figures').disabled = false; }
};
let cropStart, cropBounds, cropTarget;
$('crop-figure').onclick = () => {
  cropTarget = {id: job.id, index: pageIndex, page: job.pages[pageIndex]};
  cropBounds = null; cropStart = null;
  $('crop-image').src = `/api/jobs/${job.id}/pages/${cropTarget.page.number}`;
  $('crop-box').hidden = true; $('crop-confirm').disabled = true;
  $('crop-dialog').showModal();
};
function cropPoint(event) {
  const rect = $('crop-image').getBoundingClientRect();
  return [Math.max(0, Math.min(1, (event.clientX-rect.left)/rect.width)), Math.max(0, Math.min(1, (event.clientY-rect.top)/rect.height))];
}
$('crop-stage').onpointerdown = event => {
  if (!$('crop-image').complete || !$('crop-image').naturalWidth) return;
  event.preventDefault(); cropStart = cropPoint(event); cropBounds = null;
  $('crop-confirm').disabled = true; $('crop-box').hidden = true;
  $('crop-stage').setPointerCapture(event.pointerId);
};
$('crop-stage').onpointermove = event => {
  if (!cropStart) return;
  const end = cropPoint(event);
  cropBounds = [Math.min(cropStart[0],end[0]), Math.min(cropStart[1],end[1]), Math.max(cropStart[0],end[0]), Math.max(cropStart[1],end[1])];
  const [x,y,r,b] = cropBounds, style = $('crop-box').style;
  style.left = `${x*100}%`; style.top = `${y*100}%`; style.width = `${(r-x)*100}%`; style.height = `${(b-y)*100}%`;
  $('crop-box').hidden = false;
};
$('crop-stage').onpointerup = () => {
  cropStart = null;
  $('crop-confirm').disabled = !cropBounds || (cropBounds[2]-cropBounds[0]) * $('crop-image').naturalWidth < 10 || (cropBounds[3]-cropBounds[1]) * $('crop-image').naturalHeight < 10;
};
$('crop-stage').onpointercancel = () => { cropStart = null; cropBounds = null; $('crop-confirm').disabled = true; $('crop-box').hidden = true; };
$('crop-close').onclick = () => $('crop-dialog').close();
$('crop-confirm').onclick = async () => {
  $('crop-confirm').disabled = true;
  try {
    await save();
    const {id,index,page} = cropTarget;
    const bbox = cropBounds.map((v,i) => Math.round(v * (i%2 ? $('crop-image').naturalHeight : $('crop-image').naturalWidth)));
    const updated = await api(`/api/jobs/${id}/pages/${page.number}/figures`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({bbox})});
    if (job?.id === id) { job.pages[index] = updated; if(pageIndex === index) renderFigures(updated); }
    $('crop-dialog').close(); notice('已裁切并加入插图，导出时将自动嵌入');
  } catch(e) {notice(e.message); $('crop-confirm').disabled = false;}
};


function renderCorrection(page) {
  const info = page.correction;
  $('scan-view').value = info ? $('scan-view').value : 'original';
  $('original').src = `/api/jobs/${job.id}/pages/${page.number}?original=${$('scan-view').value === 'original'}`;
  const grids = page.blocks.filter(b => b.kind === 'grid').length;
  $('correction-note').textContent = info ?
    `${info.perspective ? '已校正透视；' : '未应用透视变换；'}${info.deskew_degrees ? `已校正倾斜 ${Math.abs(info.deskew_degrees).toFixed(2)}°；` : '未应用旋转；'}识别到 ${grids} 个网格。${(info.notes || []).join('。')}` :
    '此任务使用旧版识别。点击右侧按钮生成新副本并恢复结构，原任务的校对内容会保留。';
}
$('scan-view').onchange = () => renderCorrection(job.pages[pageIndex]);
$('rebuild').onclick = async () => {
  $('rebuild').disabled = true;
  try {
    await save();
    const updated = await api(`/api/jobs/${job.id}/rebuild`, {method:'POST'});
    await openJob(updated.id); await history();
    notice('已创建结构恢复副本，原任务和校对内容仍保留');
  } catch(e) {notice(e.message);} finally {$('rebuild').disabled=false;}
};
function renderGridEditor(block, target, area) {
  const rows=block.text.split('\n').filter(line=>line.trim()).map(line=>line.split('\t'));
  target.replaceChildren();
  const table=document.createElement('table');
  rows.forEach((row,r)=>{
    const tr=document.createElement('tr');
    row.forEach((cell,c)=>{
      const td=document.createElement('td'), input=document.createElement('input');
      input.value=cell;if(!cell.trim()){input.placeholder='空缺待核对';input.classList.add('empty-cell');}input.setAttribute('aria-label',`网格第 ${r+1} 行第 ${c+1} 列`);
      input.oninput=()=>{input.classList.toggle('empty-cell',!input.value.trim());rows[r][c]=input.value.replace(/[\t\r\n]/g,' ');block.text=rows.map(row=>row.join('\t')).join('\n');area.value=block.text;dirty=true;};
      td.append(input);tr.append(td);
    });
    table.append(tr);
  });
  target.append(table);
}

function proofBusy() { return ['queued','running'].includes(job?.proofreading?.status); }
async function refreshModels() {
  try { const data=await api('/api/proofreading/models'); const select=$('proof-model'), previous=select.value; select.replaceChildren();
    for(const name of data.models) {const opt=document.createElement('option');opt.value=name;opt.textContent=name;select.append(opt);}
    if(data.models.includes(previous)) select.value=previous;
    $('proof-model-note').textContent=data.models.length ? '模型在本机运行，书籍内容不会上传。首次分析可能较慢。' : data.message+'。请启动 Ollama 并下载模型，详见 README 的智能校对说明。';
    renderProof();
  } catch(e) {notice(e.message);}
}
function renderProof() {
  if(!job) return;
  const run=job.proofreading, busy=proofBusy(), suggestions=run?.suggestions || [];
  $('proof-status').textContent=run ? `${run.message} ${run.completed} / ${run.total} 页` : '尚未分析';
  $('proof-start').disabled=busy || !$('proof-model').value;
  $('proof-cancel').hidden=!busy;
  $('proof-auto').disabled=busy;
  $('proof-all').disabled=busy || !suggestions.some(s=>s.status==='pending');
  $('proof-undo').disabled=busy || !suggestions.some(s=>s.status==='applied');
  const locked=busy && run.auto_apply;
  for(const el of document.querySelectorAll('#blocks input,#blocks select,#blocks textarea,#figures input,#figures select,#book-title,#save,#pdf,#epub,#retain,#rebuild,#crop-figure,#toc-detect,#toc-entries input,#toc-entries select,.toc-add')) el.disabled=locked;
  $('detect-figures').disabled=locked || !!job.pages[pageIndex]?.figures_detected;
  $('proof-suggestions').replaceChildren();
  const labels={pending:'待确认',applied:'已应用',dismissed:'已忽略',stale:'原文已变化或建议冲突，请重新分析',undone:'已撤销'};
  for(const s of suggestions) {
    const card=document.createElement('article');card.className='proof-suggestion';
    const where=document.createElement('button');where.className='secondary';where.textContent=`第 ${s.page} 页 · 第 ${s.block+1} 段`;where.onclick=()=>{pageIndex=job.pages.findIndex(p=>p.number===s.page);renderPage();$('blocks').scrollIntoView({behavior:'smooth'});};
    const before=document.createElement('del'), after=document.createElement('ins'), reason=document.createElement('p');before.textContent=s.before;after.textContent=s.after;reason.textContent=`${labels[s.status]} · ${s.reason}`;
    card.append(where,before,after,reason);
    if(s.status==='pending') for(const [action,label] of [['apply','应用'],['dismiss','忽略']]) {const b=document.createElement('button');b.className='secondary';b.textContent=label;b.disabled=busy;b.onclick=()=>proofAction(action,[s.id]);card.append(b);}
    $('proof-suggestions').append(card);
  }
}
function scheduleProof() { clearTimeout(proofTimer); if(proofBusy()) proofTimer=setTimeout(pollProof,1800); }
async function pollProof() {
  const id=job?.id;if(!id)return;
  try {const fresh=await api(`/api/jobs/${id}`);if(job?.id!==id)return;
    const wasAuto=job.proofreading?.auto_apply;
    job.proofreading=fresh.proofreading;
    if(!proofBusy() && wasAuto && !dirty) {job=fresh;renderPage();} else renderProof();
    scheduleProof();
  } catch(e) {notice(e.message); if(job?.id===id) proofTimer=setTimeout(pollProof,4000);}
}
async function proofAction(action, ids=[]) {
  if(!job?.proofreading)return;
  const id=job.id,runId=job.proofreading.id;
  try {if(dirty)await save();await api(`/api/jobs/${id}/proofreading/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:runId,ids})});
    const fresh=await api(`/api/jobs/${id}`);if(job?.id===id){job=fresh;renderPage();scheduleProof();}
  }catch(e){notice(e.message);}
}
$('proof-models').onclick=refreshModels;
$('proof-start').onclick=async()=>{
  const id=job.id; $('proof-start').disabled=true;
  try {await save();const run=await api(`/api/jobs/${id}/proofreading`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:$('proof-model').value,page:$('proof-scope').value==='page'?job.pages[pageIndex].number:null,auto_apply:$('proof-auto').checked})});
    if(job?.id===id){job.proofreading=run;renderProof();scheduleProof();}
  }catch(e){notice(e.message);renderProof();}
};
$('proof-cancel').onclick=()=>proofAction('cancel');
$('proof-all').onclick=()=>proofAction('apply',job.proofreading.suggestions.filter(s=>s.status==='pending').map(s=>s.id));
$('proof-undo').onclick=()=>proofAction('undo');

function renderToc() {
  if(!job)return;
  const entries=job.toc || [];
  $('toc-note').textContent=job.toc === undefined ? '旧任务可点击识别；未识别时导出也会自动检测。' : `共 ${entries.filter(e=>e.included).length} 项已选。可改名称、层级或取消勾选；漏识别的标题可在对应段落点击「加入章节目录」。层级跳跃会在导出时自动收拢。`;
  $('toc-entries').replaceChildren();
  const order=new Map(job.pages.map((p,i)=>[p.number,i]));
  for(const entry of [...entries].sort((a,b)=>order.get(a.page)-order.get(b.page)||a.block-b.block)) {
    const page=job.pages.find(p=>p.number===entry.page), block=page?.blocks[entry.block];if(!block)continue;
    const row=document.createElement('div');row.className='toc-entry';
    const keep=document.createElement('input');keep.type='checkbox';keep.checked=entry.included;keep.setAttribute('aria-label',`保留目录第 ${entry.page} 页第 ${entry.block+1} 段`);keep.onchange=()=>{entry.included=keep.checked;dirty=true;renderToc();};
    const title=document.createElement('input');title.value=entry.title || block.text;title.maxLength=160;title.setAttribute('aria-label','目录标题');title.oninput=()=>{entry.title=title.value;dirty=true;};
    const level=document.createElement('select');level.setAttribute('aria-label','目录层级');for(let i=1;i<=3;i++){const opt=document.createElement('option');opt.value=i;opt.textContent=`${i} 级`;level.append(opt);}level.value=entry.level;level.onchange=()=>{entry.level=Number(level.value);dirty=true;};
    const jump=document.createElement('button');jump.className='secondary';jump.textContent=`原页 ${entry.page} · 段 ${entry.block+1}`;jump.onclick=()=>{pageIndex=order.get(entry.page);renderPage();const el=$('blocks').children[entry.block];el?.scrollIntoView({behavior:'smooth',block:'center'});el?.querySelector('textarea')?.focus({preventScroll:true});};
    row.append(keep,title,level,jump);$('toc-entries').append(row);
  }
  const locked=proofBusy() && job.proofreading.auto_apply;
  for(const el of document.querySelectorAll('#toc-entries input,#toc-entries select,#toc-detect,.toc-add'))el.disabled=locked;
}
$('toc-detect').onclick=async()=>{
  const id=job.id;$('toc-detect').disabled=true;
  try {await save();const data=await api(`/api/jobs/${id}/chapters/detect`,{method:'POST'});
    if(job?.id!==id)return;
    const current=job.toc || [], keys=new Set(current.map(e=>`${e.page}:${e.block}`));
    const additions=data.toc.filter(e=>!keys.has(`${e.page}:${e.block}`));
    job.toc=[...current,...additions];dirty=true;renderToc();notice(`补充 ${additions.length} 个章节候选，已有目录调整已保留。请保存或直接导出。`);
  }catch(e){notice(e.message);}finally{if(job?.id===id)$('toc-detect').disabled=false;}
};
