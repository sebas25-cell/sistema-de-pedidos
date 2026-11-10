/* Utilidades compartidas por index.html, admin.html y monitor.html */
(function () {
  const w = window;
  // La API siempre se consulta a través del gateway. Se puede cambiar con ?api=http://host:8000 (se recuerda).
  const q = new URLSearchParams(location.search).get('api');
  const guardado = (() => { try { return localStorage.getItem('api'); } catch (e) { return null; } })();
  if (q) { try { localStorage.setItem('api', q); } catch (e) {} }
    // URL pública del gateway (backend) para cuando el frontend está en Vercel
  const API_PUBLICA = 'https://thursday-railway-devel-kent.trycloudflare.com';
  w.API = q || guardado || (['localhost', '127.0.0.1', ''].includes(location.hostname) ? 'http://localhost:8000' : API_PUBLICA);

  w.$ = id => document.getElementById(id);
  w.esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  w.money = n => Number(n).toLocaleString('es-CO');
  w.save = (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
  w.load = k => { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } };

  w.toast = function (msg, ok) {
    const t = $('toast'); if (!t) return;
    t.textContent = msg; t.className = 'show' + (ok ? ' ok' : '');
    clearTimeout(t._t); t._t = setTimeout(() => t.className = '', 3400);
  };

  /* Tema claro/oscuro: se recuerda; por defecto sigue al sistema */
  const preferido = w.load('tema') || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  document.documentElement.dataset.theme = preferido;
  w.alternarTema = function () {
    const n = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = n; w.save('tema', n);
    const b = $('btnTema'); if (b) b.textContent = n === 'light' ? '🌙' : '☀️';
  };
  document.addEventListener('DOMContentLoaded', () => { const b = $('btnTema'); if (b) b.textContent = document.documentElement.dataset.theme === 'light' ? '🌙' : '☀️'; });

  /* Llamada a la API con el token de la sesión; alSesionVencida se ejecuta si responde 401 con sesión abierta */
  w.crearApi = function (obtenerSesion, alSesionVencida) {
    return async function (ruta, opts = {}) {
      const headers = {'Content-Type': 'application/json'};
      const s = obtenerSesion();
      if (s && s.token) headers.Authorization = 'Bearer ' + s.token;
      let r;
      try { r = await fetch(API + ruta, {...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined}); }
      catch (e) { throw new Error('No hay conexión con el servidor (' + API + '). ¿Está corriendo el gateway?'); }
      const d = await r.json().catch(() => ({}));
      if (r.status === 401 && s) { alSesionVencida(); throw new Error('Tu sesión venció, inicia sesión de nuevo'); }
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : (Array.isArray(d.detail) ? 'Revisa los datos del formulario' : 'Error ' + r.status));
      return d;
    };
  };
})();
