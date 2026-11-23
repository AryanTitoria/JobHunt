(() => {
  'use strict';
  const signupErrors = document.getElementById('signup-errors');
  if (signupErrors) { signupErrors.focus(); signupErrors.scrollIntoView({block: 'center'}); }
  document.querySelectorAll('[data-confirm]').forEach(button => {
    button.addEventListener('click', event => {
      if (!window.confirm(button.dataset.confirm)) event.preventDefault();
    });
  });
  document.querySelectorAll('[data-print]').forEach(button=>button.addEventListener('click',()=>window.print()));
  const toggle=document.querySelector('[data-nav-toggle]');
  const closeNav=()=>{document.body.classList.remove('nav-open');if(toggle)toggle.setAttribute('aria-expanded','false');};
  if(toggle)toggle.addEventListener('click',()=>{const open=document.body.classList.toggle('nav-open');toggle.setAttribute('aria-expanded',String(open));});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeNav();});
  window.addEventListener('pageshow',()=>{document.body.classList.remove('is-navigating');closeNav();});
  document.addEventListener('click',event=>{const link=event.target.closest('a[href]');if(!link||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||link.target||link.hasAttribute('download'))return;const url=new URL(link.href,location.href);if(url.origin===location.origin&&url.pathname!==location.pathname&&!url.hash)document.body.classList.add('is-navigating');});
  const scope=document.getElementById('id_search_scope');
  const hint=document.getElementById('scope-hint');
  const explainScope=()=>{if(!scope||!hint)return;hint.textContent=({field:'Search your chosen career field and additional work categories.',roles:'Only the role names you enter are used for relevance. Your degree does not restrict a career switch.',education:'Your degree and major guide related categories. Enter your education above.',combined:'Include roles related to your education OR roles/categories you selected. Both paths are welcome.'})[scope.value]||'';};
  if(scope)scope.addEventListener('change',explainScope);explainScope();
  const errors=document.querySelector('form .alert.error');if(errors){errors.focus();errors.scrollIntoView({block:'center'});}
  if (document.body.dataset.poll !== 'true') return;
  let attempts=0;
  const status=document.getElementById('poll-status');
  const poll=async()=>{
    if(++attempts>240){if(status)status.textContent='Still running. You can refresh later or continue browsing.';return;}
    let done=false;
    try{
      const response=await fetch(document.body.dataset.pollUrl,{credentials:'same-origin',headers:{'Accept':'application/json'}});
      if(!response.ok)throw new Error('Status unavailable');
      const data=await response.json();
      const pending=typeof data.pending_count==='number'?data.pending_count>0:data.tasks.some(task=>['queued','running'].includes(task.status));
      if(!pending){done=true;window.location.reload();return;}
      const running=data.tasks.find(task=>task.status==='running');
      if(status&&running)status.textContent=running.kind==='tailor'?'AI is composing and verifying your draft…':running.kind==='analysis'?'AI is comparing the selected resume with this posting…':'Working in the background…';
    }catch(_){if(status)status.textContent='Connection interrupted. Retrying status automatically…';}
    finally{if(!done)window.setTimeout(poll,document.hidden?8000:3000);}
  };
  window.setTimeout(poll,1500);
})();
