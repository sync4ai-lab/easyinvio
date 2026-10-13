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
