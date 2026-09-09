// Middleware package — composable HTTP middleware for the gateway.
package middleware

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/opsintel/gateway/internal/config"
)

// contextKey is unexported to prevent collisions with other packages.
type contextKey string

const (
	ContextKeyRequestID contextKey = "request_id"
	ContextKeyPrincipal contextKey = "principal"
)

// Chain wraps a handler with a sequence of middleware (applied outermost first).
func Chain(h http.Handler, middlewares ...func(http.Handler) http.Handler) http.Handler {
	// Apply in reverse so first in list is outermost.
	for i := len(middlewares) - 1; i >= 0; i-- {
		h = middlewares[i](h)
	}
	return h
}

// ── RequestID ─────────────────────────────────────────────────────────────────

// RequestID injects a unique X-Request-ID header into every request/response.
func RequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-ID")
		if id == "" {
			id = uuid.New().String()
		}
		ctx := context.WithValue(r.Context(), ContextKeyRequestID, id)
		w.Header().Set("X-Request-ID", id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// ── Logger ────────────────────────────────────────────────────────────────────

type responseWriter struct {
	http.ResponseWriter
	status int
}

func (rw *responseWriter) WriteHeader(code int) {
	rw.status = code
	rw.ResponseWriter.WriteHeader(code)
}

// Logger logs method, path, status, and latency for every request.
func Logger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rw, r)
		slog.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", rw.status,
			"duration_ms", time.Since(start).Milliseconds(),
			"request_id", r.Context().Value(ContextKeyRequestID),
			"remote_addr", r.RemoteAddr,
		)
	})
}

// ── Auth ──────────────────────────────────────────────────────────────────────

// Principal holds the authenticated user's claims.
type Principal struct {
	Subject  string
	Email    string
	Roles    []string
	TenantID string
}

// Auth returns a middleware that validates JWT bearer tokens when OIDC is enabled.
// When OIDC_ENABLED=false, the request passes through with a dev principal.
func Auth(cfg *config.Config) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Skip auth on health and metrics endpoints
			if r.URL.Path == "/health" || r.URL.Path == "/ready" || r.URL.Path == "/metrics" {
				next.ServeHTTP(w, r)
				return
			}

			if !cfg.OIDCEnabled {
				// Development mode — inject dev principal and pass through.
				devPrincipal := &Principal{
					Subject:  "dev-admin",
					Email:    "admin@opsintel.local",
					Roles:    []string{"admin", "operator", "viewer"},
					TenantID: "default",
				}
				ctx := context.WithValue(r.Context(), ContextKeyPrincipal, devPrincipal)
				next.ServeHTTP(w, r.WithContext(ctx))
				return
			}

			// Production: validate bearer JWT.
			// Full JWKS validation is implemented in Milestone 3.
			// For now, reject requests without a bearer token.
			authHeader := r.Header.Get("Authorization")
			if authHeader == "" {
				http.Error(w, `{"detail":"missing authorization header"}`, http.StatusUnauthorized)
				return
			}
			// Forward the Authorization header upstream — the AI Orchestrator
			// validates the JWT independently using its own JWKS fetch.
			next.ServeHTTP(w, r)
		})
	}
}
