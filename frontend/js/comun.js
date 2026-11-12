/* Utilidades compartidas por index.html, admin.html y monitor.html */
(function () {
  const w = window;
  // La API siempre se consulta a través del gateway. Orden para decidir la dirección:
  //   1. ?api=<dirección> en el enlace (se recuerda en este navegador; ?api=reset la olvida).
  //   2. En localhost/127.0.0.1: http://localhost:8000.
  //   3. Frontend publicado (Vercel): la dirección del túnel que iniciar_publico.bat sube a GitHub (tunel.json).
  //   4. Si GitHub no responde: la última dirección guardada en este navegador.
  const TUNEL_JSON = 'https://api.github.com/repos/sebas25-cell/sistema-de-pedidos/contents/tunel.json?ref=main';
  const limpiar = u => String(u || '').trim().replace(/\/+$/, '');
  const q = new URLSearchParams(location.search).get('api');
  const esLocal = ['localhost', '127.0.0.1', ''].includes(location.hostname);
  const guardar = v => { try { v ? localStorage.setItem('api', v) : localStorage.removeItem('api'); } catch (e) {} };
  const guardado = (() => { try { return localStorage.getItem('api'); } catch (e) { return null; } })();
  if (q === 'reset') guardar(null);
  else if (q) guardar(limpiar(q));

  w.API = (q && q !== 'reset') ? limpiar(q) : (esLocal ? 'http://localhost:8000' : '');
  // Dirección publicada en GitHub por iniciar_publico.bat ('' si no se pudo leer)
  const publicada = () => fetch(TUNEL_JSON, {headers: {Accept: 'application/vnd.github.raw+json'}, cache: 'no-store'})
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(d => { const u = limpiar(d.api); return /^https:\/\//.test(u) ? u : ''; })
    .catch(() => '');
  // apiLista: promesa que se resuelve cuando ya se conoce la dirección del servidor
  w.apiLista = w.API ? Promise.resolve(w.API) :
    publicada().then(u => { if (u) guardar(u); return (w.API = u || (q === 'reset' ? '' : guardado) || ''); });
  // Si la dirección actual no responde (túnel viejo), se cambia a la publicada en GitHub
  w.corregirApi = async function () {
    if (esLocal) return false;
    const u = await publicada();
    if (!u || u === w.API) return false;
    guardar(u); w.API = u; w.apiLista = Promise.resolve(u);
    if (q) history.replaceState(null, '', location.pathname + location.hash);  // quita el ?api= viejo del enlace
    return true;
  };

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
      await w.apiLista;
      if (!API) throw new Error('No se encontró la dirección del servidor. Ejecuta iniciar_publico.bat en el computador del servidor y recarga la página en 1 minuto.');
      const pedir = () => fetch(API + ruta, {...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined});
      try { r = await pedir(); }
      catch (e) {
        let ok = false;
        if (await w.corregirApi()) { try { r = await pedir(); ok = true; } catch (e2) {} }
        if (!ok) throw new Error('No hay conexión con el servidor (' + API + '). ¿Está corriendo iniciar_publico.bat en el computador del servidor?');
      }
      const d = await r.json().catch(() => ({}));
      if (r.status === 401 && s) { alSesionVencida(); throw new Error('Tu sesión venció, inicia sesión de nuevo'); }
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : (Array.isArray(d.detail) ? 'Revisa los datos del formulario' : 'Error ' + r.status));
      return d;
    };
  };
})();
