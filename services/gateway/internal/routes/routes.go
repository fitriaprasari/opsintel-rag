// Routes registers all gateway HTTP routes.
package routes

import (
	"encoding/json"
	"net/http"
	"net/http/httputil"

	"github.com/opsintel/gateway/internal/config"
)

// Register wires routes to the given mux.
func Register(mux *http.ServeMux, upstream *httputil.ReverseProxy, cfg *config.Config) {
	// ── Gateway health endpoints ──────────────────────────────────────────
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/ready", readyHandler)

	// ── Proxy all /api/* to upstream AI Orchestrator ──────────────────────
	mux.Handle("/api/", upstream)

	// ── Default: 404 ─────────────────────────────────────────────────────
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail":"not found"}`))
	})
}

type healthPayload struct {
	Status  string `json:"status"`
	Service string `json:"service"`
	Version string `json:"version"`
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(healthPayload{
		Status:  "ok",
		Service: "gateway",
		Version: "0.1.0",
	})
}

func readyHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"status":"ready"}`))
}
