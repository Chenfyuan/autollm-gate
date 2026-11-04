import './style.css'
const root=document.documentElement
const saved=localStorage.getItem('theme')
if(saved==='dark'||(!saved&&matchMedia('(prefers-color-scheme: dark)').matches))root.classList.add('dark')
document.getElementById('theme').onclick=()=>{root.classList.toggle('dark');localStorage.setItem('theme',root.classList.contains('dark')?'dark':'light')}
document.getElementById('year').textContent=new Date().getFullYear()
const tabs=document.querySelectorAll('[data-shot]'),img=document.getElementById('shot'),cap=document.getElementById('shotcap')
tabs.forEach(t=>t.onclick=()=>{tabs.forEach(x=>x.setAttribute('aria-selected','false'));t.setAttribute('aria-selected','true');img.src=import.meta.env.BASE_URL+t.dataset.shot.replace(/^\//,'');img.alt=t.textContent;cap.textContent=t.dataset.cap})

const ctabs=document.querySelectorAll('[data-code]'),panels=document.querySelectorAll('[data-panel]')
ctabs.forEach(t=>t.onclick=()=>{ctabs.forEach(x=>x.setAttribute('aria-selected',String(x===t)));panels.forEach(p=>p.classList.toggle('hidden',p.dataset.panel!==t.dataset.code))})
const copy=document.getElementById('copy')
if(copy)copy.onclick=async()=>{const p=[...panels].find(p=>!p.classList.contains('hidden'));try{await navigator.clipboard.writeText(p.innerText);copy.textContent='已复制';setTimeout(()=>copy.textContent='复制',1500)}catch(e){}}
const els=document.querySelectorAll('.reveal')
if('IntersectionObserver' in window){const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{rootMargin:'0px 0px -40px 0px'});els.forEach(e=>io.observe(e))}else els.forEach(e=>e.classList.add('in'))

// 邮箱运行时拼接，源码不出现完整地址
const addr=['chenfyuanl','gmail.com'].join('@')
document.querySelectorAll('[data-mail]').forEach(a=>{a.href='mailto:'+addr+'?subject='+encodeURIComponent(a.dataset.subj||'AutoLLM Gate 咨询')})
document.querySelectorAll('[data-mailtext]').forEach(e=>{e.innerHTML='';const a=document.createElement('a');a.href='mailto:'+addr;a.textContent=addr;a.className='underline';e.appendChild(a)})

// 成本估算：单价来自 core/autollm_gate/scoring.yaml（美元 / 百万 tokens）
const PRICES={'gpt-4o':[2.5,10],'gpt-4o-mini':[0.15,0.6],'claude-sonnet-4-5':[3,15],'claude-haiku-4-5':[1,5],'gemini-2.5-pro':[1.25,10],'gemini-2.5-flash':[0.3,2.5],'deepseek-chat':[0.27,1.1],'deepseek-reasoner':[0.55,2.19]}
const f=document.getElementById('calcf')
if(f){const sel=f.m;Object.keys(PRICES).forEach(k=>sel.add(new Option(k,k)));sel.value='gpt-4o-mini'
const usd=v=>'US$'+v.toLocaleString('en-US',{maximumFractionDigits:2,minimumFractionDigits:2})
const run=()=>{const n=+f.n.value||0,i=+f.i.value||0,o=+f.o.value||0,k=+f.k.value||0,[pi,po]=PRICES[sel.value];const cost=n*(i*pi+o*po)/1e6,price=cost*(1+k/100);document.getElementById('c-cost').textContent=usd(cost);document.getElementById('c-price').textContent=usd(price);document.getElementById('c-gross').textContent=usd(price-cost)}
f.addEventListener('input',run);run()}
