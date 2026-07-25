const UPSTREAM_ORIGIN = "https://mayakofm.dataonfire.cn";

const allowedApiPath =
  /^\/api\/customer-chat\/(?:login|me|query|change-password|admin\/(?:history|question-summary|accounts(?:\/[A-Za-z0-9._-]+)?)|(?:products|parts)\/[0-9]+\/image|products\/[0-9]+\/images\/[0-9]+|catalog\/(?:products|parts)\/export\.xlsx|catalog\/orders\/summary|catalog\/(?:orders|products|parts)(?:\/[0-9]+)?)$/;

const allowedAppPath =
  /^\/customer-chat(?:\/(?:orders|products|parts)(?:\/[0-9]+)?|\/account\/password|\/settings(?:\/(?:appearance|password))?|\/admin\/(?:analytics|accounts))?$/;

function withSecurityHeaders(response, cacheControl) {
  const headers = new Headers(response.headers);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  if (cacheControl) headers.set("Cache-Control", cacheControl);

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

function textResponse(body, status, headers = {}) {
  return withSecurityHeaders(
    new Response(body, {
      status,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        ...headers
      }
    })
  );
}

async function proxyCustomerApi(request, url) {
  const upstreamUrl = new URL(`${url.pathname}${url.search}`, UPSTREAM_ORIGIN);
  const upstreamRequest = new Request(upstreamUrl, request);
  const upstreamResponse = await fetch(upstreamRequest);
  return withSecurityHeaders(upstreamResponse, "no-store");
}

async function serveCustomerApp(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return textResponse("Method Not Allowed\n", 405, { Allow: "GET, HEAD" });
  }

  const assetUrl = new URL("/customer.html", request.url);
  const response = await env.ASSETS.fetch(
    new Request(assetUrl, {
      method: request.method,
      headers: request.headers
    })
  );
  return withSecurityHeaders(response, "no-store");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/healthz") {
      return textResponse("ok\n", 200);
    }

    if (url.pathname === "/") {
      return withSecurityHeaders(
        Response.redirect(new URL("/customer-chat", request.url), 302),
        "no-store"
      );
    }

    if (url.pathname === "/customer-chat/") {
      return withSecurityHeaders(
        Response.redirect(new URL("/customer-chat", request.url), 308),
        "no-store"
      );
    }

    if (url.pathname.startsWith("/api/")) {
      if (!allowedApiPath.test(url.pathname)) {
        return textResponse("Not Found\n", 404);
      }
      return proxyCustomerApi(request, url);
    }

    if (allowedAppPath.test(url.pathname)) {
      return serveCustomerApp(request, env);
    }

    if (url.pathname.startsWith("/assets/")) {
      const response = await env.ASSETS.fetch(request);
      return withSecurityHeaders(
        response,
        response.ok ? "public, max-age=31536000, immutable" : "no-store"
      );
    }

    return textResponse("Not Found\n", 404);
  }
};
