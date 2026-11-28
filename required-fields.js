/* Display required markers from existing constraints; never change validation. */
(() => {
  'use strict';
  const markers = new Map();
  let pending = false;
  function refresh() {
    pending = false;
    for (const [field, record] of markers) {
      if (!field.isConnected || field.matches(':disabled') || field.type === 'hidden' ||
          !(field.required || field.getAttribute('aria-required') === 'true') ||
          field.labels?.[0] !== record.label || !record.node.isConnected) {
        record.node.remove(); markers.delete(field);
      }
    }
    for (const field of document.querySelectorAll('input,select,textarea')) {
      if (markers.has(field) || field.matches(':disabled') || field.type === 'hidden' ||
          !(field.required || field.getAttribute('aria-required') === 'true')) continue;
      const label = field.labels?.[0];
      if (!label) continue;
      const node = document.createElement('span');
      node.className = 'required-indicator'; node.textContent = '*';
      node.setAttribute('aria-hidden','true');
      if (label.contains(field) && !['checkbox','radio'].includes(field.type)) {
        let control = field;
        while (control.parentElement !== label) control = control.parentElement;
        label.insertBefore(node,control);
      } else label.append(node);
      markers.set(field,{label,node});
    }
  }
  const observer = new MutationObserver(() => {
    if (!pending) { pending = true; queueMicrotask(refresh); }
  });
  function positionHelp(event) {
    const info = event.target.closest?.('.field-info');
    const tip = info?.querySelector('[role=tooltip]');
    const button = info?.querySelector('button');
    if (!tip || !button) return;
    if (event.type === 'focusin' || !info.contains(event.relatedTarget)) delete info.dataset.helpDismissed;
    const box = button.getBoundingClientRect();
    const size = tip.getBoundingClientRect();
    tip.style.left = Math.max(16, Math.min(box.left, innerWidth - size.width - 16)) + 'px';
    tip.style.top = Math.max(16, Math.min(box.bottom + 8, innerHeight - size.height - 16)) + 'px';
  }
  document.addEventListener('mouseover', positionHelp);
  document.addEventListener('focusin', positionHelp);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && event.target.closest?.('.field-info')) {
      event.target.closest('.field-info').dataset.helpDismissed = 'true';
      event.target.blur();
    }
  });
  refresh();
  observer.observe(document.documentElement,{subtree:true,childList:true,
    attributes:true,attributeFilter:['required','aria-required','disabled','type','for','id']});
})();
