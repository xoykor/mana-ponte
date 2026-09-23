const DEFAULT_ORIGIN = "http://168-138-250-53.sslip.io";

function originFrom(env) {
  const origin = new URL(env.MANAPONTE_ORIGIN || DEFAULT_ORIGIN);
  if (origin.protocol !== "http:" && origin.protocol !== "https:") {
    throw new Error("MANAPONTE_ORIGIN must use http:// or https://");
  }
  return origin;
}

export default {
  async fetch(request, env) {
    const origin = originFrom(env);
    const incoming = new URL(request.url);
    const target = new URL(incoming.pathname + incoming.search, origin);

    const headers = new Headers(request.headers);
    headers.delete("Host");
    headers.set("X-Forwarded-Host", incoming.host);
    headers.set("X-Forwarded-Proto", incoming.protocol.slice(0, -1));

    const clientIp = request.headers.get("CF-Connecting-IP");
    if (clientIp) {
      headers.set("X-ManaPonte-Client-IP", clientIp);
    }

    const init = {
      method: request.method,
      headers,
      redirect: "manual",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
    }

    const upstream = await fetch(target, init);
    const responseHeaders = new Headers(upstream.headers);

    const location = responseHeaders.get("Location");
    if (location) {
      try {
        const redirect = new URL(location, target);
        if (redirect.origin === origin.origin) {
          redirect.protocol = incoming.protocol;
          redirect.host = incoming.host;
          responseHeaders.set("Location", redirect.toString());
        }
      } catch {
        // Mantém Location original caso a origem envie um valor não-URL.
      }
    }

    responseHeaders.set("X-ManaPonte-Proxy", "cloudflare-worker");

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  },
};
