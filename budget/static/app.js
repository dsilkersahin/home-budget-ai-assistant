'use strict';
const $ = id => document.getElementById(id);
const state = {token:'',config:null,preview:null,edits:{},scope:'saved',chatId:null,lang:localStorage.getItem('budget-language') || 'en',pages:{},files:[],busy:false};
const tr = {
month:'Ay',category:'Kategori',income:'Gelir',expenses:'Giderler',year:'Yıl',household:'EV BÜTÇENİZ',overview:'Genel bakış',imports:'Dosya içe aktar',transactions:'İşlemler',sql:'SQL çalışma alanı',local:'Yerel ve özel',localDetail:'Dosyalarınız bu bilgisayarda kalır.',workspace:'Çalışma alanı',eyebrow:'EV BÜTÇENİZE NET BİR BAKIŞ',title:'Paranıza daha geniş bir bakış.',subtitle:'Hesaplarınızı bir araya getirin. Her ayın arkasındaki harcamaları anlayın.',upload:'＋ Ekstre içe aktar',importTitle:'Ekstrelerinizle başlayın',importSubtitle:'N26 CSV · Garanti kredi kartı XLS / XLSX · Birden fazla dosya',reviewFirst:'KAYDETMEDEN ÖNCE İNCELEYİN',drop:'Ekstreleri buraya bırakın veya dosya seçin',dropDetail:'En fazla 12 dosya · Dosya başına 15 MB · Yerel analiz',analyze:'Dosyaları analiz et',saved:'Kayıtlı veritabanı',uploaded:'Yükleme önizlemesi',currency:'Para birimi',source:'Kaynak',from:'Başlangıç',to:'Bitiş',refresh:'Yenile',consumption:'Kayıtlı tüketim harcaması',consumptionDetail:'Gider eksi iade · Kart ödemeleri hariç',movement:'N26 hesap hareketi',movementDetail:'İşaretli hesap tutarları · Hane fazlası değildir',repayments:'Kredi kartı ödemeleri',repaymentDetail:'Kart alışverişlerinden ayrı tutulur',review:'Sınıflandırma gerekli',monthly:'Aydan aya',consumptionShort:'Tüketim',breakdown:'Harcama dağılımı',insights:'İnceleyebileceğiniz noktalar',fromRecords:'KAYITLARINIZDAN',coverage:'Veri kapsamı ve raporlama notları',transactionHint:'Valör, orijinal tutar, banka etiketi ve kaynak bilgileri için satıra tıklayın.',sqlDetail:'Seçili veriyi sorgulayın. Salt okunur, yerel, en fazla 1.000 satır.',runSql:'Sorguyu çalıştır',schema:'Tablolar ve para hesaplamaları',assistant:'Bütçe asistanınız',chatIntro:'Verilerinizi sorun. Hesaplamalar yerel araçlarda yapılır; kanıtları inceleyebilirsiniz.',chatFooter:'Qwen3.5-9B · Yalnızca yerel araçlar',send:'Gönder ↗',chatNote:'Sohbet içe aktarımı kaydedemez veya bütçe onaylayamaz. Önizleme ve kayıtlı veriler ayrı sorgulanır.',footer:'Home Budget AI Assistant · Eviniz için tasarlandı. Bilgisayarınızda saklanır.'
};
const catTR={groceries:'Market',household_supplies:'Ev ihtiyaçları',coffee:'Kahve',eating_out:'Dışarıda yemek',socializing:'Sosyalleşme',housing:'Konut',utilities:'Faturalar',transport:'Ulaşım',subscriptions:'Abonelikler',health:'Sağlık',pets:'Evcil hayvanlar',travel:'Seyahat',activities:'Etkinlikler',electronics:'Elektronik',clothing:'Giyim',education:'Eğitim',shopping:'Alışveriş',insurance:'Sigorta',donations:'Bağış',savings:'Birikim',income:'Gelir',entertainment:'Eğlence',uncategorized:'Kategorisiz'};
const originalText = new Map();
const t = (en,turkish) => state.lang === 'tr' ? turkish : en;
const cat = value => state.lang === 'tr' ? (catTR[value] || value) : String(value || '').replaceAll('_',' ');
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function notice(message,error=false){$('notice').textContent=message;$('notice').className=error?'error':'';$('notice').hidden=false;}
function errorMessage(err){return err.message || String(err);}
async function api(path,options={}){
  const headers={...options.headers};
  if(options.method && options.method!=='GET')headers['X-Budget-Token']=state.token;
  if(options.body && !(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
  const response=await fetch(path,{...options,headers});
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail));
  return result;
}
function amount(value,currency=$('currency').value){
  // Backend decimal strings are authoritative. Intl is display-only.
  return new Intl.NumberFormat(state.lang==='tr'?'tr-TR':'en-IE',{style:'currency',currency,maximumFractionDigits:2}).format(Number(value || 0));
}
function table(headers,rows){
  const node=el('table'),head=el('thead'),tr=el('tr');headers.forEach(h=>tr.append(el('th',h)));head.append(tr);node.append(head);
  const body=el('tbody');rows.forEach(row=>{const tr=el('tr');row.forEach(value=>tr.append(el('td',value===null || value===undefined?'—':String(value))));body.append(tr);});node.append(body);return node;
}
function empty(node,message){node.replaceChildren(el('div',message,'empty'));}
function scopeArgs(){return {scope:state.scope,preview_id:state.preview?.preview_id};}
function clearChat(){state.chatId=null;$('chatMessages').replaceChildren();}
async function saveEdits(){if(state.preview)await api(`/api/preview/${state.preview.preview_id}`,{method:'POST',body:{edits:state.edits}});}
function setFiles(files){state.files=Array.from(files);$('fileNames').textContent=state.files.map(f=>f.name).join(' · ');$('previewButton').disabled=!state.files.length;}
$('files').addEventListener('change',event=>setFiles(event.target.files));
['dragenter','dragover'].forEach(event=>$('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.add('dragging');}));
['dragleave','drop'].forEach(event=>$('dropzone').addEventListener(event,e=>{e.preventDefault();$('dropzone').classList.remove('dragging');if(event==='drop')setFiles(e.dataTransfer.files);}));
$('previewButton').addEventListener('click',async()=>{
  $('previewButton').disabled=true;
  try{
    const form=new FormData();state.files.forEach(file=>form.append('files',file));
    state.preview=await api('/api/uploads',{method:'POST',body:form});state.edits={};state.pages={};
    state.scope='uploads';clearChat();$('uploadScope').disabled=false;
    $('start').value='';$('end').value='';$('source').value='all';renderPreview();
    notice(t('Preview ready. Review the rows before saving. Files with errors are excluded from analysis and block saving.','Önizleme hazır. Kaydetmeden önce satırları inceleyin. Hatalı dosyalar analize alınmaz ve kaydetmeyi engeller.'));
    await refresh();
  }catch(err){notice(errorMessage(err),true);}finally{$('previewButton').disabled=false;}
});
function options(values,current,onchange,labels=String){const select=el('select');values.forEach(v=>{const o=el('option',labels(v));o.value=v;o.selected=v===current;select.append(o);});select.addEventListener('change',()=>onchange(select.value));return select;}
function editRow(key,field,value){state.edits[key]={...(state.edits[key] || {}),[field]:value};}
function renderPreview(){
  const root=$('preview');root.hidden=!state.preview;root.replaceChildren();if(!state.preview)return;
  let errors=0,candidates=0;
  state.preview.batches.forEach((batch,index)=>{
    errors+=batch.errors.length;
    const box=el('details',undefined,'preview-file');box.open=index===0;
    const label=`${batch.filename} · ${batch.format.toUpperCase()} · ${batch.entries.length} ${t('rows','satır')}`;
    box.append(el('summary',label+(batch.already_imported?t(' · already imported / identical file',' · daha önce alındı / aynı dosya'):'')));
    if(batch.errors.length){const error=el('div',undefined,'error-box');batch.errors.forEach(e=>error.append(el('div',`${e.sheet || ''} ${t('row','satır')} ${e.row || '—'}: ${e.message}`)));error.append(el('p',t('Correct the source file and upload again. No rows from this file will be saved.','Kaynak dosyayı düzeltip tekrar yükleyin. Bu dosyadan hiçbir satır kaydedilmeyecek.')));box.append(error);}
    const flagged=batch.entries.filter(e=>e.duplicate_candidates.length);candidates+=flagged.length;
    box.append(el('p',t('Classification suggestions are editable. Positive entries are not automatically income. Review transfers and card settlements.','Sınıflandırma önerileri düzenlenebilir. Pozitif tutarlar otomatik gelir değildir. Transfer ve kart ödemelerini inceleyin.'),'muted'));
    const page=state.pages[index] || 0,start=page*100,entries=batch.entries.slice(start,start+100);
    const wrap=el('div',undefined,'table-scroll preview-table');const tbl=table([t('Source row','Kaynak satır'),t('Booking date','Kayıt tarihi'),t('Merchant','İşyeri'),t('Signed amount','İşaretli tutar'),t('Kind','Tür'),t('Category','Kategori'),t('Person','Kişi'),t('One-off','Tek sefer'),t('Keep / skip','Tut / atla'),t('Notes','Notlar')],[]);
    const body=tbl.querySelector('tbody');
    entries.forEach(row=>{
      const edit=state.edits[row.key] || {};const tr=el('tr');tr.append(el('td',`${row.sheet ? row.sheet+' · ' : ''}${row.row}`));
      function field(node){const td=el('td');td.append(node);tr.append(td);}
      const booking=el('input');booking.type='date';booking.value=edit.booking_date ?? row.booking_date;booking.setAttribute('aria-label','Booking date');booking.addEventListener('change',()=>editRow(row.key,'booking_date',booking.value));field(booking);
      tr.append(el('td',row.merchant));
      const signed=el('input');signed.value=edit.signed_booked ?? row.signed_booked;signed.setAttribute('aria-label',`Signed amount ${row.currency}`);signed.addEventListener('change',()=>editRow(row.key,'signed_booked',signed.value));const moneyCell=el('td');moneyCell.append(signed,el('small',' '+row.currency));tr.append(moneyCell);
      field(options(state.config.kinds,edit.kind ?? row.kind,v=>editRow(row.key,'kind',v)));
      field(options(state.config.categories,edit.category ?? row.category,v=>editRow(row.key,'category',v),cat));
      const person=el('input');person.value=edit.person ?? row.person ?? '';person.placeholder=t('Unassigned','Atanmamış');person.addEventListener('change',()=>editRow(row.key,'person',person.value.trim() || null));field(person);
      const one=el('input');one.type='checkbox';one.checked=edit.one_off ?? false;one.setAttribute('aria-label','One-off');one.addEventListener('change',()=>editRow(row.key,'one_off',one.checked));field(one);
      field(options(['review','keep','skip'],edit.decision ?? (row.duplicate_candidates.length?'review':'keep'),v=>editRow(row.key,'decision',v==='review'?null:v),v=>({review:t('Decide…','Seçin…'),keep:t('Keep','Tut'),skip:t('Skip','Atla')})[v]));
      tr.append(el('td',[...row.warnings,...(row.duplicate_candidates.length?[t('Matches: ','Eşleşmeler: ')+row.duplicate_candidates.join(', ')]:[])].join(' '),'review-warning'));
      if(batch.already_imported)tr.querySelectorAll('input,select').forEach(input=>input.disabled=true);
      body.append(tr);
    });
    wrap.append(tbl);box.append(wrap);
    if(batch.entries.length>100){const pager=el('div',undefined,'pager');const prev=el('button','←');prev.disabled=page===0;prev.onclick=()=>{state.pages[index]=page-1;renderPreview();};const next=el('button','→');next.disabled=start+100>=batch.entries.length;next.onclick=()=>{state.pages[index]=page+1;renderPreview();};pager.append(prev,el('span',`${start+1}–${Math.min(start+100,batch.entries.length)} / ${batch.entries.length}`),next);box.append(pager);}
    root.append(box);
  });
  const controls=el('div',undefined,'save-row');const apply=el('button',t('Update analysis preview','Analiz önizlemesini güncelle'),'quiet');apply.onclick=async()=>{try{await saveEdits();clearChat();await refresh();notice(t('Preview updated; nothing saved.','Önizleme güncellendi; kayıt yapılmadı.'));}catch(e){notice(errorMessage(e),true);}};
  const confirm=el('button',t('Confirm & save reviewed rows','İncelenen satırları onayla ve kaydet'),'primary');confirm.disabled=errors>0;
  confirm.onclick=async()=>{
    confirm.disabled=true;
    try{await saveEdits();const result=await api(`/api/confirm/${state.preview.preview_id}`,{method:'POST',body:{confirmed:true}});state.preview=null;state.edits={};state.scope='saved';$('uploadScope').disabled=true;clearChat();renderPreview();await refresh();notice(t(`${result.inserted} records saved. No import coverage was assumed.`,`${result.inserted} kayıt eklendi. Veri tamlığı varsayılmadı.`));}
    catch(err){notice(errorMessage(err),true);}finally{confirm.disabled=errors>0;}
  };
  controls.append(el('small',t(`${candidates} possible duplicate rows need an explicit keep/skip decision. Identical file reimports are skipped. No recurring payment is automatically confirmed.`,`${candidates} olası yinelenen satır için tut/atla kararı gerekli. Aynı dosya tekrar eklenmez. Düzenli ödeme otomatik onaylanmaz.`)),apply,confirm);root.append(controls);
}
function updateSelect(id,values,labelFn){const select=$(id),previous=select.value;select.replaceChildren();values.forEach(v=>{const option=el('option',labelFn(v));option.value=v;select.append(option);});if(values.includes(previous))select.value=previous;}
async function refresh(){
  $('refresh').disabled=true;
  try{
    const params=new URLSearchParams({...scopeArgs(),currency:$('currency').value,source:$('source').value,group_by:$('groupBy').value,search:$('search').value,category:$('category').value});
    if(!state.preview)params.delete('preview_id');
    if($('start').value)params.set('start',$('start').value);if($('end').value)params.set('end',$('end').value);
    const data=await api('/api/dashboard?'+params);
    updateSelect('year',['all',...new Set(data.all_months.map(m=>m.slice(0,4)))],v=>v==='all'?t('All years','Tüm yıllar'):v);
    updateSelect('month',['all',...data.all_months.filter(m=>$('year').value==='all'||m.startsWith($('year').value))],v=>v==='all'?t('All months','Tüm aylar'):v);
    updateSelect('category',['all',...data.categories],v=>v==='all'?t('All categories','Tüm kategoriler'):cat(v));
    updateSelect('chartCategory',['all',...data.categories],v=>v==='all'?t('All categories','Tüm kategoriler'):cat(v));
    $('chartCategory').value=$('category').value;
    updateSelect('currency',[...new Set(['EUR','TRY',...data.currencies])],String);
    updateSelect('source',['all',...data.sources],v=>v==='all'?t('All sources','Tüm kaynaklar'):v);
    $('savedScope').classList.toggle('selected',state.scope==='saved');$('uploadScope').classList.toggle('selected',state.scope==='uploads');
    $('scopeLabel').textContent=state.scope==='saved'?`${t('Database','Veritabanı')}: ${state.config.database}`:t('Unsaved uploaded files · valid files only','Kaydedilmemiş dosyalar · yalnızca geçerli dosyalar');
    $('chatScope').textContent=state.scope==='saved'?t('Querying saved records','Kayıtlı veriler sorgulanır'):t('Querying upload preview','Yükleme önizlemesi sorgulanır');
    $('period').textContent=(data.start?`${data.start} → ${data.end}`:t('No records yet','Henüz kayıt yok'))+' · '+t('Completeness not assumed','Veri tamlığı varsayılmadı');
    $('consumption').textContent=amount(data.totals.consumption);$('movement').textContent=data.totals.n26_net_account_movement===undefined?'—':amount(data.totals.n26_net_account_movement);$('repayments').textContent=amount(data.totals.card_repayment);
    $('unresolved').textContent=data.unresolved_count;$('recordCount').textContent=`${data.record_count} ${t('records in this view','kayıt bu görünümde')}`;
    renderCharts(data);renderSuggestions(data);renderTransactions(data);
  }catch(err){notice(errorMessage(err),true);}finally{$('refresh').disabled=false;}
}
function svgNode(tag,attrs){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,v));return node;}
function attachTip(node,text,container){
  const title=svgNode('title',{});title.textContent=text;node.append(title);
  function show(event){let tip=container.querySelector('.chart-tooltip');if(!tip){tip=el('div',undefined,'chart-tooltip');tip.setAttribute('role','tooltip');container.append(tip);}tip.textContent=text;const box=container.getBoundingClientRect(),point=node.getBoundingClientRect();tip.style.left=Math.max(0,Math.min((event.clientX||point.x)-box.x,box.width-200))+'px';tip.style.top=Math.max(0,(event.clientY||point.y)-box.y-45)+'px';}
  function hide(){container.querySelector('.chart-tooltip')?.remove();}
  node.addEventListener('pointermove',show);node.addEventListener('pointerleave',hide);node.addEventListener('focus',show);node.addEventListener('blur',hide);
}
function renderCharts(data){
  const monthly=$('monthlyChart');monthly.replaceChildren();
  if(!data.monthly.length){empty(monthly,t('Upload statements to see your monthly picture.','Aylık görünüm için ekstre yükleyin.'));$('monthlyTable').replaceChildren();}
  else{
    const svg=svgNode('svg',{viewBox:'0 0 640 240',role:'img','aria-label':t('Monthly income and expenses','Aylık gelir ve giderler')});
    const max=Math.max(1,...data.monthly.flatMap(m=>[Number(m.income||0),Number(m.expense||0)]));
    for(let tick=0;tick<=4;tick++){const y=190-tick*40;svg.append(svgNode('line',{x1:65,x2:610,y1:y,y2:y,stroke:'#e3e8df'}));const label=svgNode('text',{x:60,y:y+4,'text-anchor':'end','font-size':10});label.textContent=amount(max*tick/4);svg.append(label);}
    [['income','#16803c',t('Income','Gelir')],['expense','#cf3030',t('Expenses','Giderler')]].forEach(([key,color,name])=>{
      const points=data.monthly.map((row,i)=>({x:75+i*520/Math.max(1,data.monthly.length-1),y:190-Number(row[key]||0)/max*160,row}));
      svg.append(svgNode('polyline',{points:points.map(p=>`${p.x},${p.y}`).join(' '),fill:'none',stroke:color,'stroke-width':3}));
      points.forEach(p=>{const dot=svgNode('circle',{cx:p.x,cy:p.y,r:7,fill:color,tabindex:0});attachTip(dot,`${p.row.month} · ${$('chartCategory').value==='all'?t('All categories','Tüm kategoriler'):cat($('chartCategory').value)} · ${name}: ${amount(p.row[key])}`,monthly);svg.append(dot);});
    });
    data.monthly.forEach((row,i)=>{const label=svgNode('text',{x:75+i*520/Math.max(1,data.monthly.length-1),y:215,'text-anchor':'middle','font-size':10});label.textContent=row.month;svg.append(label);});monthly.append(svg);
    $('monthlyTable').replaceChildren(table([t('Month','Ay'),t('Consumption','Tüketim'),t('N26 movement','N26 hareketi'),t('Card repayments','Kart ödemeleri'),t('Recorded income','Kayıtlı gelir'),t('Unresolved','Çözümlenmemiş')],data.monthly.map(m=>[m.month,amount(m.consumption),m.n26_net_account_movement===undefined?'—':amount(m.n26_net_account_movement),amount(m.card_repayment),m.income===undefined?'—':amount(m.income),amount(m.unresolved)])));
  }
  const chart=$('groupChart');chart.replaceChildren();
  if(!data.groups.length){empty(chart,t('Category totals appear after importing expenses.','Giderler eklendikten sonra dağılım görünür.'));return;}
  if($('month').value!=='all'){
    const slices=(data.category_totals||[]).filter(g=>Number(g.amount)>0);
    const total=slices.reduce((sum,g)=>sum+Number(g.amount),0);
    if(!total){empty(chart,t('No positive net category spending for this month.','Bu ay için pozitif net kategori harcaması yok.'));return;}
    const svg=svgNode('svg',{viewBox:'0 0 240 240',role:'img','aria-label':t('Monthly spending by category','Aylık kategori harcamaları')});svg.classList.add('pie-chart');let angle=-Math.PI/2;
    slices.forEach((g,i)=>{const sweep=Number(g.amount)/total*Math.PI*2,end=angle+sweep,color=`hsl(${i*137.5%360} 55% 46%)`;let slice;
      if(slices.length===1)slice=svgNode('circle',{cx:120,cy:120,r:100,fill:color,tabindex:0});
      else slice=svgNode('path',{d:`M120 120 L${120+100*Math.cos(angle)} ${120+100*Math.sin(angle)} A100 100 0 ${sweep>Math.PI?1:0} 1 ${120+100*Math.cos(end)} ${120+100*Math.sin(end)} Z`,fill:color,stroke:'white',tabindex:0});
      attachTip(slice,`${cat(g.name)}: ${amount(g.amount)} (${(Number(g.amount)/total*100).toFixed(1)}%)`,chart);slice.addEventListener('click',()=>{$('category').value=g.name;refresh();});svg.append(slice);angle=end;
    });chart.append(svg);
    chart.append(el('p',t('Net expenses after refunds · hover for values; click a slice to filter.','İade sonrası net gider · değer için üzerine gelin; filtrelemek için tıklayın.'),'muted fine'));
    chart.append(table([t('Category','Kategori'),t('Net expenses','Net gider')],data.category_totals.map(g=>[cat(g.name),amount(g.amount)])));
  }else{
    const max=Math.max(...data.groups.map(g=>Math.abs(Number(g.amount))),1);
    data.groups.forEach(group=>{const row=el('div',undefined,'group-row');const label=el('div',undefined,'group-label');label.append(el('span',data.group_by==='category'?cat(group.name):group.name),el('b',amount(group.amount)));const track=el('div',undefined,'group-track'),fill=el('div',undefined,'group-fill');fill.style.width=Math.abs(Number(group.amount))/max*100+'%';track.append(fill);row.append(label,track);chart.append(row);});
  }
}
function renderSuggestions(data){
  const root=$('suggestions');root.replaceChildren();
  if(!data.suggestions.length)root.append(el('p',t('Your first import will bring this view to life.','İlk yüklemenizle bu görünüm oluşacak.'),'muted fine'));
  data.suggestions.forEach(s=>{const row=el('div',undefined,'insight-item');let text=s.text;if(state.lang==='tr'){if(s.type==='review')text=`${data.unresolved_count} çözümlenmemiş işlemi inceleyin; toplamlar henüz tüm harcamayı temsil etmeyebilir.`;if(s.type==='categorize')text=`Daha iyi kategori analizi için ${data.uncategorized_count} işlemi sınıflandırın.`;if(s.type==='trend')text='En yüksek kayıtlı grup: '+(data.groups[0]?.name || '');}row.append(el('span',s.type==='trend'?'↗':'○','insight-icon'),el('span',text+(s.amount?' '+amount(s.amount):'')));root.append(row);});
  $('limitations').replaceChildren(...data.limitations.map(text=>el('li',text)));$('coverageData').textContent=data.coverage.length?JSON.stringify(data.coverage,null,2):t('No import completeness has been confirmed.','İçe aktarım tamlığı onaylanmadı.');
}
function renderTransactions(data){
  $('transactionCaption').textContent=`${data.transactions.length} / ${data.record_count} ${t('records shown','kayıt gösteriliyor')}`+(data.rows_truncated?t(' · narrow dates/search for more detail',' · tarih/arama ile daraltın'):'');
  $('rowDetails').hidden=true;
  if(!data.transactions.length){empty($('transactionTable'),t('No matching records. Choose files to start a preview.','Eşleşen kayıt yok. Önizleme için dosya seçin.'));return;}
  const tbl=table([t('Date / month','Tarih / ay'),t('Merchant','İşyeri'),t('Category','Kategori'),t('Kind','Tür'),t('Amount','Tutar'),t('Source','Kaynak')],[]);const body=tbl.querySelector('tbody');
  data.transactions.forEach(row=>{const tr=el('tr',undefined,'transaction '+(row.kind==='income'?'income-row':row.kind==='expense'?'expense-row':''));tr.tabIndex=0;tr.append(el('td',row.booking_date || row.month),el('td',row.merchant),el('td',cat(row.category)));const td=el('td');td.append(el('span',row.kind,'kind '+row.kind));tr.append(td,el('td',amount(row.amount,row.currency),'amount'),el('td',row.source_type));const show=()=>{$('rowDetails').hidden=false;$('rowDetails').textContent=JSON.stringify(row,null,2);};tr.onclick=show;tr.onkeydown=e=>{if(e.key==='Enter')show();};body.append(tr);});$('transactionTable').replaceChildren(tbl);
}
$('runSql').onclick=async()=>{const button=$('runSql');button.disabled=true;try{await saveEdits();const result=await api('/api/sql',{method:'POST',body:{...scopeArgs(),sql:$('sqlInput').value}});$('sqlResult').replaceChildren(table(result.columns,result.rows),el('p',result.truncated?t('Truncated to 1,000 rows.','1.000 satıra sınırlandı.'):t(`${result.rows.length} rows`,`${result.rows.length} satır`),'muted fine'));}catch(err){$('sqlResult').replaceChildren(el('p',errorMessage(err),'error-box'));}finally{button.disabled=false;}};
function message(text,role,evidence){const node=el('div',text,'chat-message '+role);if(evidence?.length){const details=el('details');details.append(el('summary',t('Tool evidence & executed SQL','Araç kanıtları ve SQL')),el('pre',JSON.stringify(evidence,null,2)));node.append(details);}$('chatMessages').append(node);$('chatMessages').scrollTop=$('chatMessages').scrollHeight;return node;}
$('chatForm').addEventListener('submit',async event=>{
  event.preventDefault();const text=$('chatInput').value.trim();if(!text || state.busy)return;
  state.busy=true;$('sendChat').disabled=true;$('chatInput').value='';message(text,'user');const pending=message(t('Analyzing locally… the model may take a moment.','Yerel analiz yapılıyor… modelin yanıtı biraz sürebilir.'),'assistant');
  try{await saveEdits();const result=await api('/api/chat',{method:'POST',body:{...scopeArgs(),chat_id:state.chatId,text,language:state.lang}});state.chatId=result.chat_id;pending.remove();message(result.answer || t('No explanation returned; inspect the evidence.','Açıklama dönmedi; kanıtları inceleyin.'),'assistant',result.evidence);}
  catch(err){pending.remove();message(errorMessage(err),'error');}finally{state.busy=false;$('sendChat').disabled=false;}
});
document.querySelectorAll('[data-prompt]').forEach((button,i)=>button.onclick=()=>{const prompts=['Mevcut tüm tarihler için EUR aylık tüketimi özetle. Önce data_inventory, sonra read_sql kullan ve SQL göster.','EUR cinsinden en yüksek kayıtlı harcamaya sahip kategoriler hangileri? Tarihleri incele, read_sql kullan.','Sınıflandırılması gereken işlemleri read_sql ile göster; işlem kimliklerini ekle.'];$('chatInput').value=state.lang==='tr'?prompts[i]:button.dataset.prompt;$('chatInput').focus();});
$('resetChat').onclick=clearChat;
$('savedScope').onclick=()=>{state.scope='saved';clearChat();refresh();};$('uploadScope').onclick=async()=>{state.scope='uploads';clearChat();try{await saveEdits();await refresh();}catch(e){notice(errorMessage(e),true);}};
$('refresh').onclick=async()=>{try{await saveEdits();await refresh();}catch(e){notice(errorMessage(e),true);}};
['currency','source','start','end','groupBy','category'].forEach(id=>$(id).addEventListener('change',refresh));
$('chartCategory').addEventListener('change',()=>{$('category').value=$('chartCategory').value;refresh();});
$('year').addEventListener('change',()=>{const year=$('year').value;$('month').value='all';$('start').value=year==='all'?'':year+'-01-01';$('end').value=year==='all'?'':year+'-12-31';refresh();});
$('month').addEventListener('change',()=>{const month=$('month').value;if(month==='all'){const year=$('year').value;$('start').value=year==='all'?'':year+'-01-01';$('end').value=year==='all'?'':year+'-12-31';}else{$('year').value=month.slice(0,4);$('start').value=month+'-01';const [year,num]=month.split('-').map(Number);$('end').value=month+'-'+new Date(year,num,0).getDate();}refresh();});
['start','end'].forEach(id=>$(id).addEventListener('change',()=>{$('month').value='all';$('year').value='all';}));
let searchTimeout;$('search').addEventListener('input',()=>{clearTimeout(searchTimeout);searchTimeout=setTimeout(refresh,300);});
function translate(){document.documentElement.lang=state.lang;document.querySelectorAll('[data-i18n]').forEach(node=>{if(!originalText.has(node))originalText.set(node,node.textContent);node.textContent=state.lang==='tr'?(tr[node.dataset.i18n] || originalText.get(node)):originalText.get(node);});$('chatInput').placeholder=t('Ask about your spending…','Harcamalarınızı sorun…');$('search').placeholder=t('Search merchant…','İşyeri ara…');$('language').textContent=state.lang==='tr'?'TR / EN':'EN / TR';Array.from($('groupBy').options).forEach(o=>o.textContent=({category:t('Category','Kategori'),section:t('Statement section','Ekstre bölümü'),account:t('Account / card','Hesap / kart'),source_type:t('Source','Kaynak')})[o.value]);}
$('language').onclick=()=>{state.lang=state.lang==='en'?'tr':'en';localStorage.setItem('budget-language',state.lang);translate();clearChat();renderPreview();refresh();};
async function boot(){try{state.config=await api('/api/config');state.token=state.config.token;$('database').textContent=state.config.database;translate();await refresh();const status=await api('/api/model');$('modelStatus').textContent=(status.available?'● ':'○ ')+status.model+(status.available?'':t(' · unavailable',' · kullanılamıyor'));}catch(err){notice(errorMessage(err),true);}}
boot();
