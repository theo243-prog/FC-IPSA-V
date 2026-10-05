/* Service worker du FC IPSA V.
   Rôle unique : recevoir les notifications push et les afficher, même quand le site est fermé.
   Il ne met RIEN en cache et n'intercepte aucune requête : le site se comporte exactement comme avant. */

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; }
  catch (e) { data = { body: event.data ? event.data.text() : '' }; }
  const title = data.title || 'FC IPSA V';
  const options = {
    body: data.body || '',
    icon: data.icon || '/icons/icon-192.png',
    badge: data.badge || '/icons/badge-96.png',
    lang: 'fr',
    data: { url: data.url || '/' },
  };
  if (data.tag) { options.tag = data.tag; options.renotify = true; }     // une notification de même type remplace la précédente
  // Toujours afficher une notification : les navigateurs (surtout Safari sur iPhone) l'exigent à chaque message.
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  // Seules les pages du club sont ouvertes : une adresse d'un autre site est remplacée par l'accueil.
  let target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin);
  if (target.origin !== self.location.origin) target = new URL('/', self.location.origin);
  const tab = (target.hash || '').replace('#', '');
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === target.origin) {          // le site est déjà ouvert : on le met devant et on change d'onglet
        await client.focus();
        client.postMessage({ type: 'open-tab', tab });
        return;
      }
    }
    await self.clients.openWindow(target.href);                     // sinon on l'ouvre directement sur le bon onglet
  })());
});
