// Reverse proxy — forwards all matched requests to the upstream AI Orchestrator.
package proxy

import (
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
)

// NewReverseProxy creates an httputil.ReverseProxy pointing at upstreamURL.
func NewReverseProxy(upstreamURL string) *httputil.ReverseProxy {
	target, err := url.Parse(upstreamURL)
	if err != nil {
		slog.Error("invalid upstream URL", "url", upstreamURL, "error", err)
		panic(err)
	}

	proxy := httputil.NewSingleHostReverseProxy(target)

	// Custom error handler — avoid exposing internal errors verbatim.
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		slog.Error("proxy error", "path", r.URL.Path, "error", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(`{"detail":"upstream service unavailable"}`))
	}

	return proxy
}
