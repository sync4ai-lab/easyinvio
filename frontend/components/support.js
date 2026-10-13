// EasyInvio Help Centre. Search and email drafts stay separate from booking actions.
(() => {
  const search = document.getElementById('supportSearch');
  const form = document.getElementById('support-search-form');
  const results = document.getElementById('support-search-results');
  const list = document.getElementById('support-results-list');
  const status = document.getElementById('support-search-status');
  const clear = document.getElementById('support-search-clear');
  const normalise = value => value.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  let guides = [];
  let ready = false;
  let unavailable = false;

  if (form && search) {
    const ask = document.createElement('button');
    ask.type = 'button';
    ask.className = 'button-link';
    ask.textContent = 'Ask the help assistant';
    const note = document.createElement('p');
    note.className = 'assistant-note';
    note.textContent = 'Ask about using EasyInvio. Keep personal and order details out of your question.';
    const answer = document.createElement('section');
    answer.id = 'support-agent-answer';
    answer.className = 'support-answer';
    answer.setAttribute('aria-live', 'polite');
    answer.setAttribute('aria-labelledby', 'support-answer-question');
    answer.hidden = true;
    form.insertAdjacentElement('afterend', note);
    note.insertAdjacentElement('afterend', ask);
    form.closest('.help-hero').insertAdjacentElement('afterend', answer);
    let controller;

    function frame(question, label) {
      answer.replaceChildren();
      answer.hidden = false;
      const header = document.createElement('div');
      header.className = 'support-answer-header';
      const name = document.createElement('span');
      name.className = 'support-answer-name';
      name.textContent = 'EasyInvio help';
      const badge = document.createElement('span');
      badge.className = 'support-answer-badge';
      badge.textContent = label;
      header.append(name, badge);
      const heading = document.createElement('h2');
      heading.id = 'support-answer-question';
      heading.textContent = question;
      answer.append(header, heading);
    }

    function paragraph(text, className = '') {
      const element = document.createElement('p');
      element.className = className;
      element.textContent = text;
      answer.append(element);
      return element;
    }

    function safeLink(source) {
      if (!source || typeof source.url !== 'string' || typeof source.title !== 'string') return null;
      try {
        const url = new URL(source.url, location.origin);
        if (url.origin !== location.origin || !url.pathname.startsWith('/help/')) return null;
        const link = document.createElement('a');
        link.href = url.pathname + url.hash;
        link.textContent = source.title;
        return link;
      } catch { return null; }
    }

    ask.addEventListener('click', async () => {
      const question = search.value.trim();
      frame(question || 'Ask a question', 'Help assistant');
      if (question.length < 3) {
        paragraph('Enter your question in the search box first.');
        search.focus();
        return;
      }
      let token;
      try { token = JSON.parse(localStorage.getItem('easyinvio.session') || 'null')?.access_token; }
      catch { token = null; }
      if (!token) {
        paragraph('Sign in to ask the help assistant. You can browse and search all guides without signing in.');
        return;
      }
      controller?.abort();
      const active = new AbortController();
      controller = active;
      const timeout = setTimeout(() => active.abort(), 25000);
      ask.disabled = true;
      results.hidden = true;
      answer.setAttribute('aria-busy', 'true');
      paragraph('Finding guidance in the EasyInvio Help Centre?', 'support-answer-loading');
      try {
        const response = await fetch('/api/v1/help/search-agent', {
          method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + token},
          body: JSON.stringify({query: question}), signal: active.signal
        });
        if (!response.ok) throw Error(response.status === 401 || response.status === 403 ? 'Sign in again to ask the assistant.' : 'Assistance is unavailable. Browse the search results or contact support.');
        const data = await response.json();
        if (typeof data.answer !== 'string' || !Array.isArray(data.sources)) throw Error('Assistance is unavailable. Browse the guides below.');
        if (search.value.trim() !== question) return;
        const generated = data.mode === 'AI_CITED_ANSWER';
        frame(question, generated ? 'AI answer' : 'Related guides');
        if (generated || data.mode === 'NO_EVIDENCE') {
          const content = document.createElement('div');
          content.className = 'support-answer-body';
          for (const block of data.answer.trim().split(/\n\s*\n/).slice(0, 12)) {
            const text = document.createElement('p');
            text.textContent = block.trim();
            content.append(text);
          }
          answer.append(content);
        } else {
          paragraph(data.fallback_reason === 'AI_NOT_CONFIGURED'
            ? 'AI answers are not enabled on this server yet. These guides can still help.'
            : data.fallback_reason === 'INSUFFICIENT_EVIDENCE'
              ? 'The guides do not contain enough information for a reliable answer. You can check these related topics or contact support.'
              : 'The assistant could not respond just now. You can continue with these guides.', 'support-answer-notice');
        }
        const references = document.createElement('div');
        references.className = generated ? 'support-answer-sources' : 'support-answer-guides';
        if (generated && data.sources.length) {
          const title = document.createElement('h3');
          title.textContent = 'Read the source';
          references.append(title);
        }
        const seen = new Set();
        const sources = !generated && Array.isArray(data.excerpts) && data.excerpts.length ? data.excerpts : data.sources;
        for (const source of sources.slice(0, 4)) {
          const link = safeLink(source);
          if (!link || seen.has(link.href)) continue;
          seen.add(link.href);
          const item = document.createElement('div');
          item.className = 'support-answer-source';
          item.append(link);
          if (!generated && typeof source.text === 'string') {
            const preview = document.createElement('p');
            preview.textContent = source.text.slice(0, 280);
            item.append(preview);
          }
          references.append(item);
        }
        answer.append(references);
        const footer = document.createElement('div');
        footer.className = 'support-answer-footer';
        const caption = document.createElement('span');
        caption.textContent = generated ? 'Based on EasyInvio guides. Check the source before acting.' : 'Still need help?';
        const contact = safeLink({url: '/help/contact', title: 'Contact support'});
        footer.append(caption, contact);
        answer.append(footer);
      } catch (error) {
        if (search.value.trim() !== question) return;
        frame(question, 'Help assistant');
        paragraph(error.name === 'AbortError' ? 'Assistance took too long. Use the guides below or try again.' : error.message, 'support-answer-notice');
      } finally {
        clearTimeout(timeout);
        answer.setAttribute('aria-busy', 'false');
        ask.disabled = false;
      }
    });
    search.addEventListener('input', () => {
      controller?.abort();
      answer.hidden = true;
    });
    clear?.addEventListener('click', () => {
      controller?.abort();
      answer.hidden = true;
    });
  }

  function renderSearch() {
    const query = search.value.trim().slice(0, 160);
    results.hidden = query.length === 0;
    clear.hidden = query.length === 0;
    list.replaceChildren();
    if (!query) return;
    if (unavailable) {
      status.textContent = 'Search is temporarily unavailable. Browse the topics below or contact support.';
      return;
    }
    if (!ready) {
      status.textContent = 'Loading help topics...';
      return;
    }
    const words = normalise(query).split(' ').filter(Boolean);
    const matches = words.length ? guides.filter(guide => {
      const text = normalise([guide.title, guide.summary, guide.category, guide.keywords].join(' '));
      return words.every(word => text.includes(word));
    }).sort((a, b) => Number(b.prepared) - Number(a.prepared)) : [];
    status.textContent = matches.length ? `${matches.length} ${matches.length === 1 ? 'guide' : 'guides'} found. Feature guides being prepared are labelled.` : 'No matching guide yet. Try a shorter search, browse the topics below, or contact support.';
    for (const guide of matches) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = guide.url;
      link.textContent = guide.title;
      const description = document.createElement('p');
      description.textContent = guide.summary;
      item.append(link, description);
      if (!guide.prepared) {
        const badge = document.createElement('span');
        badge.className = 'status';
        badge.textContent = 'Guide being prepared';
        item.append(badge);
      }
      list.append(item);
    }
    if (!matches.length) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = '/help/contact';
      link.textContent = 'Ask EasyInvio support';
      item.append(link);
      list.append(item);
    }
  }

  if (search && form && results && list && status && clear) {
    search.value = (new URLSearchParams(window.location.search).get('q') || '').slice(0, 160);
    search.addEventListener('input', renderSearch);
    form.addEventListener('submit', event => {
      event.preventDefault();
      renderSearch();
    });
    clear.addEventListener('click', () => {
      search.value = '';
      renderSearch();
      search.focus();
    });
    search.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        search.value = '';
        renderSearch();
      }
    });
    renderSearch();
    fetch('/help/search-index.json', {credentials: 'omit'})
      .then(response => {
        if (!response.ok) throw Error('Help index unavailable');
        return response.json();
      })
      .then(index => {
        if (!Array.isArray(index.guides)) throw Error('Invalid help index');
        guides = index.guides;
        ready = true;
        renderSearch();
      })
      .catch(() => {
        unavailable = true;
        renderSearch();
      });
  }

  const contact = document.getElementById('help-contact-form');
  if (contact) {
    contact.addEventListener('submit', event => {
      event.preventDefault();
      if (!contact.reportValidity()) return;
      const topic = contact.elements.topic.value;
      const reference = contact.elements.reference.value.trim().replace(/[\r\n]/g, ' ');
      const message = contact.elements.message.value.trim();
      if (message.length < 10) {
        document.getElementById('help-contact-status').textContent = 'Please describe the problem in at least 10 characters.';
        contact.elements.message.focus();
        return;
      }
      const subject = 'EasyInvio support: ' + topic + (reference ? ' - ' + reference : '');
      const body = 'Topic: ' + topic + '\nReference: ' + (reference || 'Not provided') + '\n\n' + message;
      let draft = document.getElementById('help-email-draft');
      if (!draft) {
        draft = document.createElement('a');
        draft.id = 'help-email-draft';
        draft.className = 'button-link';
        draft.textContent = 'Open your email app';
        contact.append(draft);
      }
      draft.href = 'mailto:support@easyinvio.com?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
      document.getElementById('help-contact-status').textContent = 'Your draft is ready. Open your email app using the link below, review it and send it there. If no email app opens, email support@easyinvio.com directly. Nothing has been sent yet.';
      draft.focus();
    });
  }
})();
