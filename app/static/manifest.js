const ui={busy:false};const output=document.querySelector('#message');document.querySelector('#print').addEventListener('click',()=>window.print());document.querySelector('#execute').addEventListener('click',async()=>{if(ui.busy)return;ui.busy=true;output.textContent='核验中…';try{const dataset=document.querySelector('#sample').value;const response=await fetch(dataset===document.body.dataset.source?'/api/runs/'+document.body.dataset.runId+'/rerun':'/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset})});const result=await response.json();if(!response.ok)throw Error(result.detail);const url=new URL(location.href);url.searchParams.set('dataset',dataset);url.searchParams.set('run_id',result.manifest.run_id);location.href=url;}catch(e){output.textContent=e.message;}finally{ui.busy=false;}});document.querySelector('#query').addEventListener('input',event=>document.querySelectorAll('.data-panel tbody tr').forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(event.target.value.toLowerCase())));document.querySelector('#sample').value=new URL(location.href).searchParams.get('dataset')||document.querySelector('#sample').value;
const filePicker=document.querySelector('#csv-file');
if(filePicker){
 const editor=document.querySelector('#csv-text');
 filePicker.addEventListener('change',async()=>{const file=filePicker.files[0];if(!file)return;if(file.size>2000000){editor.value='';alert('文件超过2MB，请缩小后导入');return;}const bytes=await file.arrayBuffer();try{editor.value=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch(e){editor.value=new TextDecoder('gb18030',{fatal:true}).decode(bytes);}});
 document.querySelector('#import-csv').addEventListener('click',async event=>{event.target.disabled=true;try{const response=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csv_text:editor.value})});const data=await response.json();if(!response.ok)throw Error(data.detail);location.href=location.pathname+'?run_id='+data.manifest.run_id;}catch(e){editor.setCustomValidity(e.message);editor.reportValidity();}finally{event.target.disabled=false;}});
 editor.addEventListener('input',()=>editor.setCustomValidity(''));
}
const correctionText=document.querySelector('#correction-text');
if(correctionText){
 const packageId=document.querySelector('#correction-package-id');
 const button=document.querySelector('#apply-correction');
 const declaration={pieces:'#declaration-pieces',net_kg:'#declaration-net',gross_kg:'#declaration-gross'};
 const say=message=>{output.textContent=message;};
 const declarationValue=()=>{
  const value={};
  for(const [field,selector] of Object.entries(declaration)){
   const raw=document.querySelector(selector).value.trim();
   if(raw)value[field]=raw;
  }
  return value;
 };
 button.addEventListener('click',async()=>{
  if(ui.busy)return;
  if(!packageId.value.trim()){packageId.focus();say('请填写补正包编号');return;}
  if(!correctionText.value.trim()&&!Object.keys(declarationValue()).length){correctionText.focus();say('请粘贴补正内容或填写申报汇总');return;}
  ui.busy=true;button.disabled=true;say('补正中…');
  try{
   const body={package_id:packageId.value.trim(),csv_text:correctionText.value};
   const summary=declarationValue();
   if(Object.keys(summary).length)body.declaration=summary;
   const response=await fetch('/api/runs/'+document.body.dataset.runId+'/corrections',
     {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   const data=await response.json();
   if(!response.ok)throw Error(data.detail);
   const outcome=data.correction_outcome||{};
   if(outcome.duplicate){say('同一补正包已采纳，未重复生成');return;}
   if(outcome.restored){
    const reason=(outcome.rejected[0]||{}).detail||'补正包被退回';
    say('补正包已退回，旧版结果保持不变：'+reason);
    return;
   }
   const url=new URL(location.href);url.searchParams.set('run_id',outcome.run_id);location.href=url;
  }catch(e){say(e.message);}finally{ui.busy=false;button.disabled=false;}
 });
}
