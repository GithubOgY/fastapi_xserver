const CACHE_NAME = 'xstock-v1';
const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/offline'
];

// Install: Cache static assets
self.addEventListener('install', (event) => {
  console.log('[SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[SW] Caching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate: Clean up old caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('[SW] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: Network First strategy (always try network, fallback to cache)
self.addEventListener('fetch', (event) => {
  // Skip non-GET requests
  if (event.request.method !== 'GET') return;
  
  // Skip API requests (we don't want to cache dynamic data)
  if (event.request.url.includes('/api/')) return;
  
  // Skip external resources
  if (!event.request.url.startsWith(self.location.origin)) return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Clone response to store in cache
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          // Only cache successful responses
          if (response.status === 200) {
            cache.put(event.request, responseClone);
          }
        });
        return response;
      })
      .catch(() => {
        // Network failed, try cache
        return caches.match(event.request)
          .then(cachedResponse => {
            if (cachedResponse) {
              return cachedResponse;
            }
            // If nothing in cache, show offline page for navigation requests
            if (event.request.mode === 'navigate') {
              return caches.match('/offline');
            }
            // Return empty response for other requests
            return new Response('', { status: 503, statusText: 'Service Unavailable' });
          });
      })
  );
});
