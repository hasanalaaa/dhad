import {
  CACHE_VERSION,
  OPTIONAL_NEURAL_ASSETS,
  PRECACHE_ASSETS,
  PRECACHE_NAME,
  SHELL_CACHE_NAME,
  classifyRequest,
} from "./pwa/cache-policy.js";

async function atomicPrecache() {
  const cache = await caches.open(PRECACHE_NAME);
  await cache.addAll(PRECACHE_ASSETS);
}

self.addEventListener("install", (event) => {
  event.waitUntil(atomicPrecache());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([PRECACHE_NAME, SHELL_CACHE_NAME]);
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((name) => name.startsWith("dhad-") && !keep.has(name))
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

function canonicalImmutableUrl(requestOrUrl) {
  const url = new URL(
    typeof requestOrUrl === "string" ? requestOrUrl : requestOrUrl.url,
    self.location.href,
  );
  url.search = "";
  url.hash = "";
  return url.href;
}

async function cacheFirst(request) {
  const cache = await caches.open(PRECACHE_NAME);
  const cacheKey = canonicalImmutableUrl(request);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) await cache.put(cacheKey, response.clone());
  return response;
}

async function warmOptionalNeuralAssets() {
  const cache = await caches.open(PRECACHE_NAME);
  const results = await Promise.allSettled(
    OPTIONAL_NEURAL_ASSETS.map(async (asset) => {
      const cacheKey = canonicalImmutableUrl(asset);
      if (await cache.match(cacheKey)) return { asset, cached: true };
      const response = await fetch(cacheKey, {
        credentials: "same-origin",
        cache: "reload",
      });
      if (!response.ok) throw new Error(`optional asset fetch failed (${response.status}): ${asset}`);
      await cache.put(cacheKey, response.clone());
      return { asset, cached: false };
    }),
  );
  return Object.freeze({
    total: results.length,
    ready: results.filter((result) => result.status === "fulfilled").length,
    failed: results.filter((result) => result.status === "rejected").length,
  });
}

async function staleWhileRevalidate(request, { navigation = false, event = null } = {}) {
  const runtime = await caches.open(SHELL_CACHE_NAME);
  const precache = await caches.open(PRECACHE_NAME);
  const cached =
    (await runtime.match(request, { ignoreSearch: navigation })) ??
    (await precache.match(request, { ignoreSearch: navigation }));
  const refreshed = fetch(request)
    .then(async (response) => {
      if (response.ok) await runtime.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  if (cached) {
    event?.waitUntil?.(refreshed);
    return cached;
  }
  const response = await refreshed;
  if (response) return response;
  if (navigation) {
    return (await precache.match("./index.html")) ?? (await precache.match("./offline.html"));
  }
  return new Response("Offline asset unavailable", { status: 503 });
}

self.addEventListener("fetch", (event) => {
  const route = classifyRequest(event.request, self.location.origin);
  if (route === "immutable") {
    event.respondWith(cacheFirst(event.request));
  } else if (route === "shell") {
    event.respondWith(staleWhileRevalidate(event.request, { event }));
  } else if (route === "navigation") {
    event.respondWith(staleWhileRevalidate(event.request, { navigation: true, event }));
  }
});

self.addEventListener("sync", (event) => {
  if (event.tag !== "dhad-outbox-sync") return;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) client.postMessage({ type: "dhad:outbox-sync" });
    }),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "dhad:activate-update" && CACHE_VERSION) {
    event.waitUntil?.(self.skipWaiting());
    return;
  }
  if (event.data?.type === "dhad:warm-neural-cache") {
    event.waitUntil?.(
      warmOptionalNeuralAssets().then((status) => {
        event.source?.postMessage?.({ type: "dhad:neural-cache-status", status });
      }),
    );
  }
});
