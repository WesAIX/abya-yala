// Расшифровка терминов на страницах глав: при наведении, фокусе с клавиатуры или
// касании показывается краткое определение из глоссария и ссылка на полную статью.
// Без JavaScript термин остаётся обычной ссылкой на глоссарий.
(() => {
  const terms = document.querySelectorAll('a.term');
  if (!terms.length) return;
  const pop = document.createElement('div');
  pop.className = 'term-pop';
  pop.id = 'term-pop';
  pop.setAttribute('role', 'tooltip');
  pop.hidden = true;
  document.body.append(pop);
  // тип указателя берётся из самого события: устройство может иметь и мышь, и сенсорный экран
  let current = null, timer = 0, lastPointer = 'mouse';

  function place(a){
    const r = a.getBoundingClientRect();
    const w = Math.min(340, innerWidth - 16);
    pop.style.width = w + 'px';
    pop.style.left = Math.min(Math.max(8, r.left), innerWidth - w - 8) + 'px';
    pop.style.top = (r.bottom + 6) + 'px';
    const h = pop.offsetHeight;
    if (r.bottom + 6 + h > innerHeight - 8) pop.style.top = Math.max(8, r.top - h - 6) + 'px';
  }
  function show(a){
    clearTimeout(timer);
    if (current && current !== a) current.removeAttribute('aria-describedby');
    current = a;
    pop.replaceChildren();
    const b = document.createElement('b'); b.textContent = a.dataset.title;
    const p = document.createElement('p'); p.textContent = a.dataset.def;
    const more = document.createElement('a'); more.href = a.href; more.textContent = 'Подробнее в глоссарии →';
    pop.append(b, p, more);
    pop.hidden = false;
    a.setAttribute('aria-describedby', 'term-pop');
    place(a);
  }
  function hide(now){
    clearTimeout(timer);
    const go = () => { pop.hidden = true; if (current) current.removeAttribute('aria-describedby'); current = null; };
    if (now) go(); else timer = setTimeout(go, 150);
  }
  document.addEventListener('pointerdown', e => { lastPointer = e.pointerType; }, {capture: true});
  terms.forEach(a => {
    a.addEventListener('pointerenter', e => { if (e.pointerType === 'mouse') show(a); });
    a.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') hide(); });
    a.addEventListener('focus', () => show(a));
    a.addEventListener('blur', () => hide());
    // при касании первое нажатие показывает определение, второе — переходит в глоссарий
    a.addEventListener('click', e => {
      if (lastPointer !== 'mouse' && current !== a) { e.preventDefault(); show(a); }
    });
  });
  pop.addEventListener('pointerenter', () => clearTimeout(timer));
  pop.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') hide(); });
  pop.addEventListener('focusin', () => clearTimeout(timer));
  pop.addEventListener('focusout', () => hide());
  document.addEventListener('click', e => { if (!e.target.closest('a.term, .term-pop')) hide(true); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') hide(true); });
  addEventListener('scroll', () => { if (current && !pop.hidden) place(current); }, {passive: true});
})();
