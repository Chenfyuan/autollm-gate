import './style.css'
const root=document.documentElement
const saved=localStorage.getItem('theme')
if(saved==='dark'||(!saved&&matchMedia('(prefers-color-scheme: dark)').matches))root.classList.add('dark')
document.getElementById('theme').onclick=()=>{root.classList.toggle('dark');localStorage.setItem('theme',root.classList.contains('dark')?'dark':'light')}
document.getElementById('year').textContent=new Date().getFullYear()
const tabs=document.querySelectorAll('[data-shot]'),img=document.getElementById('shot'),cap=document.getElementById('shotcap')
tabs.forEach(t=>t.onclick=()=>{tabs.forEach(x=>x.setAttribute('aria-selected','false'));t.setAttribute('aria-selected','true');img.src=t.dataset.shot;img.alt=t.textContent;cap.textContent=t.dataset.cap})
