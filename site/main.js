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
