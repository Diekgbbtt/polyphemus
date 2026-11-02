
(() => {
  const MAXC = 500;
  const out = {url: location.href, title: document.title, ready: document.readyState,
               generation: String(performance.timeOrigin), elements: [], groups: [], notes: []};
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  const txt = (el, n) => {
    const v = (el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('placeholder'))) || el.innerText || el.value || '';
    return String(v).replace(/\s+/g, ' ').trim().slice(0, n || 120);
  };
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return ''; } };
  const same = (u) => { try { return new URL(u, location.href).origin === location.origin; } catch (e) { return false; } };
  const visible = (el) => {
    try {
      if (!el || el.nodeType !== 1) return false;
      if (el.hidden) return false;
      if (el.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
      const s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    } catch (e) { return false; }
  };
  const attr = (v) => String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const unique = (sel) => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };
  const path = (el) => {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) {
      const s = '#' + esc(el.id);
      if (unique(s)) return s;
    }
    const tag = el.tagName.toLowerCase();
    if (tag === 'form') {
      const forms = [...document.querySelectorAll('form')];
      return forms.length === 1 ? 'form' : `form:nth-of-type(${forms.indexOf(el) + 1})`;
    }
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      const ph = el.getAttribute('placeholder');
      if (ph) {
        const s = `${tag}[placeholder="${attr(ph)}"]`;
        if (unique(s)) return s;
      }
      const name = el.getAttribute('name');
      if (name) {
        const s = `${tag}[name="${attr(name)}"]`;
        if (unique(s)) return s;
      }
    }
    if (tag === 'button') {
      const form = el.closest('form');
      if (form) {
        const btns = [...form.querySelectorAll('button')];
        if (btns.length === 1) return 'form button';
        const idx = btns.indexOf(el);
        if (idx >= 0) return `form button:nth-of-type(${idx + 1})`;
      }
      const dialog = el.closest('[role="dialog"],dialog');
      if (dialog) {
        const btns = [...dialog.querySelectorAll('button')];
        if (btns.length === 1) return '[role="dialog"] button';
        const idx = btns.indexOf(el);
        if (idx >= 0) return `[role="dialog"] button:nth-of-type(${idx + 1})`;
      }
      if (document.querySelectorAll('button').length === 1) return 'button';
    }
    const parts = [];
    let n = el;
    for (let i = 0; i < 6 && n && n.nodeType === 1 && n !== document.body; i++) {
      let p = n.nodeName.toLowerCase();
      if (n.parentElement) {
        const sibs = [...n.parentElement.children].filter(c => c.nodeName === n.nodeName);
        if (sibs.length > 1) p += ':nth-of-type(' + (sibs.indexOf(n) + 1) + ')';
      }
      parts.unshift(p);
      n = n.parentElement;
    }
    return parts.join(' > ');
  };
  const fp = (s) => {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return ('00000000' + (h >>> 0).toString(16)).slice(-8);
  };
  const ext = /\.(pdf|txt|zip|png|jpe?g|gif|csv|xlsx?|docx?|gz|tar|mp3|mp4|woff2?|ttf|svg)$/i;
  const fieldSel = 'input,select,textarea,[contenteditable="true"],[contenteditable=""]';
  const isField = (el) => el.matches && el.matches(fieldSel);
  const fieldRoles = new Set(['textbox','searchbox','combobox','checkbox','radio','switch','slider','spinbutton','option','listbox']);
  const submitText = (t) => {
    const s = String(t || '').toLowerCase();
    const n = s.replace(/\s+/g, '');
    return ['注册','登录','提交','保存','确定','添加','创建','发布','搜索','submit','save','add','create','register','login','log in','sign in','send','publish','ok','confirm','apply','search','update']
      .some(w => s.includes(w) || n.includes(w.replace(/\s+/g, '')));
  };
  const fieldInfo = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'textarea' ? 'textarea' : tag)).toLowerCase();
    let label = '';
    try {
      const l = el.labels && el.labels[0];
      if (l) label = txt(l, 80);
      if (!label && el.getAttribute('aria-labelledby')) {
        const n = document.getElementById(el.getAttribute('aria-labelledby'));
        if (n) label = txt(n, 80);
      }
    } catch (e) {}
    const options = tag === 'select' ? [...el.options].map(o => ({value: o.value, text: txt(o, 80)})).slice(0, 30) : [];
    return {tag, type, name: el.getAttribute('name') || '', id: el.id || '',
            placeholder: el.getAttribute('placeholder') || '', label,
            selector: path(el), visible: visible(el), required: !!el.required,
            pattern: el.getAttribute('pattern') || '', min: el.getAttribute('min') || '',
            max: el.getAttribute('max') || '', value: el.value || '', checked: !!el.checked,
            options, disabled: !!el.disabled, readonly: !!el.readOnly,
            fingerprint: fp([tag, type, el.getAttribute('name') || '', el.id || '',
                             el.getAttribute('placeholder') || '', label, path(el)].join('|'))};
  };
  const fieldsIn = (root) => [...root.querySelectorAll(fieldSel)].filter(f => !f.closest('[hidden],[inert]')).map(fieldInfo);
  const addElement = (el, type, channel, extra) => {
    if (!el || out.elements.length >= MAXC) return null;
    const o = {id: 'cand_' + out.elements.length, type, channel,
               tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '',
               name: txt(el), text: txt(el, 160), selector: path(el),
               visible: visible(el), disabled: !!el.disabled, href: '', action: '', method: '',
               target: '', controls: [], expanded: el.getAttribute('aria-expanded') || '',
               handler: '', fingerprint: '',
               dom_path: path(el)};
    Object.assign(o, extra || {});
    o.fingerprint = fp([o.type, o.tag, o.role, o.name, o.href, o.action, o.method, o.dom_path].join('|'));
    out.elements.push(o);
    return o;
  };
  const typeFor = (el) => {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (tag === 'a') {
      const href = el.getAttribute('href') || '';
      if (!href || href.startsWith('#') || /^(javascript|mailto|tel|data|blob):/i.test(href)) return null;
      const full = abs(href);
      if (!/^https?:/i.test(full)) return null;
      if (!same(full)) return 'EXTERNAL_LINK';
      if (el.hasAttribute('download') || ext.test(new URL(full).pathname)) return 'DOWNLOAD';
      return 'LINK';
    }
    if (tag === 'area') {
      const href = el.getAttribute('href') || '';
      if (!href || !/^https?:/i.test(abs(href))) return null;
      return same(abs(href)) ? 'AREA' : 'EXTERNAL_AREA';
    }
    if (tag === 'form') {
      const action = el.getAttribute('action') || '';
      return (!action || same(abs(action))) ? 'FORM' : 'EXTERNAL_FORM';
    }
    if (tag === 'button') {
      if (el.closest('form') && (el.getAttribute('type') || '').toLowerCase() === 'submit') return null;
      return 'BUTTON';
    }
    if (tag === 'summary') return 'DISCLOSURE';
    if (tag === 'iframe') {
      const src = el.getAttribute('src') || '';
      return src && !same(abs(src)) ? 'EXTERNAL_IFRAME' : 'IFRAME';
    }
    if (tag === 'frame') return 'FRAME';
    if (tag === 'meta' && /refresh/i.test(el.getAttribute('http-equiv') || '')) return 'META_REFRESH';
    if (tag === 'dialog' || role === 'dialog' || el.getAttribute('aria-modal') === 'true') return 'DIALOG_STATE';
    if (role === 'button') return 'ROLE_BUTTON';
    if (role === 'link') return 'ROLE_LINK';
    if (role === 'tab') return 'TAB';
    if (['menuitem','menuitemcheckbox','menuitemradio'].includes(role)) return 'MENU_ITEM';
    if (role === 'treeitem') return 'TREE_ITEM';
    if (fieldRoles.has(role)) return null;
    if (el.getAttribute('draggable') === 'true') return 'DRAGGABLE';
    if (el.hasAttribute('onclick') || el.hasAttribute('onmouseover') || el.hasAttribute('oncontextmenu')) return 'CLICKABLE';
    if ((tag === 'svg' || tag === 'canvas') && (el.hasAttribute('onclick') || role === 'button')) return 'CLICKABLE';
    if (tag.includes('-') && (role || el.hasAttribute('tabindex') || el.hasAttribute('onclick'))) return 'CUSTOM';
    if (role && role !== 'presentation' && role !== 'none' && role !== 'generic') return 'CUSTOM';
    if (el.hasAttribute('tabindex')) return 'CUSTOM';
    return null;
  };
  const channelFor = (t) => {
    if (!t) return 'ignore';
    if (t.startsWith('EXTERNAL_')) return 'ignore';
    if (t === 'DOWNLOAD') return 'collect';
    if (t === 'DIALOG_STATE') return 'ignore';
    return 'offer';
  };
  const impactFor = (t, el) => {
    if (!t) return 'observe';
    if (t === 'DOWNLOAD') return 'download';
    if (t.startsWith('EXTERNAL_')) return 'external';
    if (t === 'FORM') {
      const m = (el.getAttribute('method') || 'get').toUpperCase();
      return m === 'GET' ? 'navigate' : 'write';
    }
    if (t === 'LINK' || t === 'AREA' || t === 'IFRAME' || t === 'FRAME' || t === 'META_REFRESH') return 'navigate';
    if (t === 'MENU_ITEM') return el.getAttribute('aria-expanded') !== null ? 'local_state' : 'navigate';
    return 'local_state';
  };
  const addFieldsGroup = (root, kind, el) => {
    const native = !!(el && el.tagName.toLowerCase() === 'form');
    const allFields = fieldsIn(root);
    const fields = native ? allFields : allFields.filter(f => f.visible);
    if (!fields.length) return null;
    if (!native) {
      if (fields.length > 12) return null;
      const types = new Set(fields.map(f => f.type));
      if ([...types].every(t => t === 'checkbox' || t === 'radio')) return null;
      if (['TABLE', 'TBODY', 'TR', 'THEAD', 'UL', 'OL'].includes(root.tagName)) return null;
    }
    const buttons = [...root.querySelectorAll('button,[role="button"],input[type="submit"],input[type="button"]')]
      .filter(b => visible(b) && submitText(txt(b, 80) || b.value || ''));
    const submit = buttons[0];
    const action = el && el.tagName.toLowerCase() === 'form' ? abs(el.getAttribute('action') || location.href) : '';
    const method = el && el.tagName.toLowerCase() === 'form' ? (el.getAttribute('method') || 'get').toUpperCase() : '';
    const enctype = el && el.tagName.toLowerCase() === 'form' ? (el.getAttribute('enctype') || 'application/x-www-form-urlencoded') : '';
    const g = {id: 'group_' + out.groups.length, kind, synthetic: !native,
               action, method, enctype, selector: el ? path(el) : '', root_selector: el ? path(el) : '',
               submit_selector: submit ? path(submit) : '', submit_text: submit ? txt(submit, 60) : '',
               fields, text: el ? txt(el, 200) : '',
               fingerprint: fp(['FORM', kind, action, method, fields.map(f => f.name + ':' + f.type + ':' + f.placeholder).join(',')].join('|'))};
    out.groups.push(g);
    return g;
  };
  // native forms
  [...document.querySelectorAll('form')].forEach(f => {
    if (!visible(f)) return;
    addFieldsGroup(f, 'native', f);
  });
  // synthetic groups: fields outside forms, nearest ancestor with a submit control
  const outside = [...document.querySelectorAll(fieldSel)].filter(f => !f.closest('form') && visible(f));
  const seenRoots = new Set();
  outside.forEach(f => {
    let n = f.parentElement;
    for (let i = 0; i < 8 && n && n !== document.body; i++, n = n.parentElement) {
      const btns = [...n.querySelectorAll('button,[role="button"],input[type="submit"],input[type="button"]')]
        .filter(b => visible(b) && submitText(txt(b, 80) || b.value || ''));
      if (btns.length && !seenRoots.has(path(n))) {
        seenRoots.add(path(n));
        addFieldsGroup(n, 'synthetic', n);
        break;
      }
    }
  });
  // visible dialog groups
  [...document.querySelectorAll('[role="dialog"],[aria-modal="true"],dialog')].forEach(d => {
    if (!visible(d)) return;
    const p = path(d);
    if (seenRoots.has(p)) return;
    seenRoots.add(p);
    addFieldsGroup(d, 'dialog', d);
  });
  // element candidates
  const groupSubmitSelectors = new Set(out.groups.map(g => g.submit_selector).filter(Boolean));
  const groupImpact = (g) => {
    const t = String(g.submit_text || '').toLowerCase();
    if (t.includes('搜索') || t.includes('search') || t.includes('query')) return 'read';
    if (g.method === 'GET') return 'navigate';
    return 'write';
  };
  const sel = 'a[href],area[href],button,summary,iframe,frame,dialog,[role],[onclick],[tabindex],[draggable="true"],[onmouseover],[oncontextmenu],meta[http-equiv="refresh"],svg[onclick],canvas[onclick]';
  [...document.querySelectorAll(sel)].forEach(el => {
    if (out.elements.length >= MAXC) return;
    if (isField(el)) return;
    if (el.closest('form') && el.tagName.toLowerCase() !== 'form') return;
    if (el.tagName.toLowerCase() === 'button' && groupSubmitSelectors.has(path(el))) return;
    const t = typeFor(el);
    if (!t) return;
    if (t === 'FORM') return; // groups handle forms
    if ((t === 'CUSTOM' || t === 'CLICKABLE') &&
        (txt(el, 400).length > 220 ||
         el.querySelectorAll('a[href],button,[role],[onclick],[tabindex]').length > 6)) return;
    const ch = channelFor(t);
    if (ch === 'ignore' && t !== 'EXTERNAL_LINK' && t !== 'EXTERNAL_FORM' && t !== 'EXTERNAL_IFRAME') return;
    const extra = {href: '', action: '', method: '', target: ''};
    if (t === 'LINK' || t === 'DOWNLOAD' || t === 'EXTERNAL_LINK' || t === 'AREA') extra.href = abs(el.getAttribute('href') || '');
    if (t === 'IFRAME' || t === 'FRAME' || t === 'EXTERNAL_IFRAME') extra.href = abs(el.getAttribute('src') || '');
    if (t === 'MENU_ITEM' && el.getAttribute('aria-controls')) extra.controls = [el.getAttribute('aria-controls')];
    if (el.getAttribute('aria-controls')) extra.controls = (extra.controls || []).concat(el.getAttribute('aria-controls').split(/\s+/));
    if (el.getAttribute('aria-expanded') !== null) extra.expanded = el.getAttribute('aria-expanded');
    if (el.hasAttribute('onclick')) extra.handler = 'onclick';
    else if (el.tagName.toLowerCase() === 'a') extra.handler = 'href';
    const o = addElement(el, t, ch, extra);
    if (o) {
      o.impact = impactFor(t, el);
      o.capture = (t === 'FORM') ? 'network' : (t === 'LINK' || t === 'IFRAME' || t === 'AREA' || t === 'META_REFRESH' ? 'navigation' : (o.channel === 'offer' ? 'dom' : 'none'));
    }
  });
  // add group candidates as elements too
  out.groups.forEach(g => {
    if (out.elements.length >= MAXC) return;
    const o = {id: 'cand_' + out.elements.length, type: 'FORM', channel: 'offer',
               tag: g.synthetic ? 'div' : 'form', role: '', name: g.submit_text || g.text.slice(0, 80),
               text: g.text, selector: g.selector, visible: true, disabled: false,
               href: '', action: g.action, method: g.method, enctype: g.enctype,
               target: '', controls: [], expanded: '', handler: g.synthetic ? 'click' : 'onsubmit',
               fingerprint: g.fingerprint, dom_path: g.selector, synthetic: g.synthetic,
               group_id: g.id, impact: groupImpact(g),
               capture: 'network'};
    out.elements.push(o);
    g.element_id = o.id;
  });
  out.signature = fp([location.href, document.title,
                      document.body ? document.body.innerText.length : 0,
                      document.querySelectorAll('*').length].join('|'));
  out.forms = out.groups.length;
  out.native_forms = out.groups.filter(g => !g.synthetic).length;
  out.synthetic_forms = out.groups.filter(g => g.synthetic).length;
  out.fields = out.groups.reduce((n, g) => n + g.fields.length, 0);
  return JSON.stringify(out);
})()
