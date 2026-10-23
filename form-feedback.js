/* Accessible validation for static and dynamically inserted forms. */
(() => {
  'use strict';
  const fields = 'input,select,textarea';
  const tracked = new WeakMap();
  let sequence = 0;
  let pending = false;

  function label(field) {
    const explicit = field.getAttribute('aria-label');
    if (explicit) return explicit;
    const source = field.labels?.[0];
    if (source) {
      const copy = source.cloneNode(true);
      copy.querySelectorAll('input,select,textarea,button,small,.form-field-error').forEach(node => node.remove());
      const text = copy.textContent.replace(/\s+/g, ' ').trim();
      if (text) return text;
    }
    return (field.name || field.id || 'this field').replace(/[_-]/g, ' ');
  }

  function trimConstraint(field) {
    if (field.dataset.spaceValidation === 'true') {
      field.setCustomValidity('');
      delete field.dataset.spaceValidation;
    }
    if (field.willValidate && field.required && !field.validity.customError &&
        ['text', 'search', 'tel', 'email', 'url', 'textarea'].includes(field.type) &&
        field.value && !field.value.trim()) {
      field.setCustomValidity('Enter ' + label(field) + '; spaces alone are not a value.');
      field.dataset.spaceValidation = 'true';
    }
  }

  function message(field) {
    const name = label(field);
    const validity = field.validity;
    if (validity.customError) return field.validationMessage;
    if (validity.valueMissing) {
      if (field.type === 'checkbox' || field.type === 'radio') return 'Please confirm: ' + name + '.';
      return (field.type === 'file' || field.tagName === 'SELECT' ? 'Choose ' : 'Enter ') + name + '.';
    }
    if (validity.typeMismatch && field.type === 'email') return 'Enter a valid email address for ' + name + '.';
    if (validity.rangeUnderflow) return name + ' must be at least ' + field.min + '.';
    if (validity.rangeOverflow) return name + ' must be no more than ' + field.max + '.';
    if (validity.tooShort) return name + ' needs at least ' + field.minLength + ' characters.';
    if (validity.tooLong) return name + ' allows no more than ' + field.maxLength + ' characters.';
    return name + ': ' + field.validationMessage;
  }

  function reveal(field) {
    for (let node = field.parentElement; node; node = node.parentElement) {
      if (node.tagName === 'DETAILS') node.open = true;
    }
  }

  function clear(field) {
    const record = tracked.get(field);
    if (!record) return;
    record.node.remove();
    const described = (field.getAttribute('aria-describedby') || '').split(/\s+/).filter(id => id && id !== record.node.id);
    if (described.length) field.setAttribute('aria-describedby', described.join(' '));
    else field.removeAttribute('aria-describedby');
    if (record.previousInvalid === null) field.removeAttribute('aria-invalid');
    else field.setAttribute('aria-invalid', record.previousInvalid);
    delete field.dataset.validationError;
    tracked.delete(field);
  }

  function show(field) {
    reveal(field);
    let record = tracked.get(field);
    if (!record) {
      const node = document.createElement('p');
      node.className = 'form-field-error';
      node.id = 'form-field-error-' + (++sequence);
      record = {node, previousInvalid: field.getAttribute('aria-invalid')};
      tracked.set(field, record);
      field.after(node);
      field.setAttribute('aria-describedby', [field.getAttribute('aria-describedby'), node.id].filter(Boolean).join(' '));
    }
    record.node.textContent = message(field);
    field.setAttribute('aria-invalid', 'true');
    field.dataset.validationError = 'true';
  }

  function invalidFields(form) {
    return [...form.elements].filter(field => field.matches?.(fields) && field.willValidate && !field.validity.valid);
  }

  function summary(form, announce = false) {
    const invalid = invalidFields(form);
    form.querySelectorAll('[data-validation-error]').forEach(field => {
      if (!invalid.includes(field)) clear(field);
    });
    let panel = [...form.children].find(node => node.classList.contains('form-validation-summary'));
    if (!invalid.length) {
      panel?.remove();
      return;
    }
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'form-validation-summary';
      panel.setAttribute('role', 'alert');
      panel.setAttribute('aria-live', 'polite');
      form.prepend(panel);
    }
    const title = document.createElement('strong');
    title.textContent = 'Please check ' + invalid.length + (invalid.length === 1 ? ' field' : ' fields') + ' before continuing.';
    const list = document.createElement('ul');
    for (const field of invalid) {
      show(field);
      const item = document.createElement('li');
      const link = document.createElement('button');
      link.type = 'button';
      link.textContent = message(field);
      link.addEventListener('click', () => { reveal(field); field.focus(); field.scrollIntoView({block: 'center'}); });
      item.append(link);
      list.append(item);
    }
    panel.replaceChildren(title, list);
    if (announce) {
      // The app toast supplements the persistent summary and field messages.
      // Standalone tracking/help pages use the same accessible summary.
      if (typeof notify === 'function') notify(message(invalid[0]), true);
    }
  }

  function validate(form) {
    if (!(form instanceof HTMLFormElement) || form.noValidate) return true;
    [...form.elements].forEach(field => { if (field.matches?.(fields)) trimConstraint(field); });
    const invalid = invalidFields(form);
    if (!invalid.length) { summary(form); return true; }
    form.dataset.validationAttempted = 'true';
    summary(form, true);
    reveal(invalid[0]);
    invalid[0].focus();
    invalid[0].scrollIntoView({block: 'center'});
    return false;
  }

  document.addEventListener('click', event => {
    const button = event.target.closest?.('button,input[type="submit"],input[type="image"]');
    if (!button || button.disabled || !button.form || button.formNoValidate ||
        !['submit', 'image'].includes(button.type)) return;
    if (!validate(button.form)) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);

  document.addEventListener('submit', event => {
    if (event.submitter?.formNoValidate) return;
    if (!validate(event.target)) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);

  document.addEventListener('invalid', event => {
    const field = event.target;
    const form = field.form;
    if (!form) return;
    form.dataset.validationAttempted = 'true';
    show(field);
    if (!pending) {
      pending = true;
      queueMicrotask(() => { pending = false; if (form.isConnected) summary(form, true); });
    }
  }, true);

  function changed(event) {
    const field = event.target;
    if (!field.matches?.(fields)) return;
    trimConstraint(field);
    queueMicrotask(() => {
      if (!field.isConnected || field.form?.dataset.validationAttempted !== 'true') return;
      summary(field.form);
    });
  }
  document.addEventListener('input', changed, true);
  document.addEventListener('change', changed, true);
  document.addEventListener('reset', event => {
    const form = event.target;
    form.querySelectorAll('[data-validation-error]').forEach(clear);
    form.querySelector('.form-validation-summary')?.remove();
    form.querySelectorAll('[data-space-validation]').forEach(field => {
      field.setCustomValidity(''); delete field.dataset.spaceValidation;
    });
    delete form.dataset.validationAttempted;
  }, true);

  function formatErrors(errors) {
    const lookup = {weights_kg: 'weight_kg', currency: 'currency', cargo_type: 'cargo-type'};
    return errors.map(error => {
      if (!error || typeof error !== 'object') return 'Check the request details.';
      const parts = (Array.isArray(error.loc) ? error.loc : []).filter(part => typeof part === 'string' && !['body', 'query', 'path'].includes(part));
      const reason = typeof error.msg === 'string' ? error.msg : 'Check this value.';
      let field = null;
      if (['origin', 'destination'].includes(parts[0])) field = document.getElementById(parts.slice(0, 2).join('-'));
      else if (parts[0] === 'dimensions') field = document.getElementById(parts[1]);
      else field = document.getElementById(lookup[parts[0]] || '') || [...document.querySelectorAll(fields)].find(node => node.name === parts[parts.length - 1]);
      const name = field ? label(field) : parts.join(' ').replace(/_/g, ' ') || 'Request details';
      if (error.type === 'missing' || error.type === 'string_too_short' || /cannot be blank/i.test(reason)) return 'Enter ' + name + '.';
      if (parts[parts.length - 1] === 'phone') return name + ' must include + and the country code, for example +447700900123.';
      if (parts[parts.length - 1] === 'email') return 'Enter a valid email address for ' + name + '.';
      return name + ': ' + reason.replace(/^Value error,\s*/i, '');
    }).join(' ');
  }
  window.easyinvioFormFeedback = {validate, formatErrors};
})();
