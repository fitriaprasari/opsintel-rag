// Gateway main entry point.
// Starts the HTTP server, registers routes, and wires middleware.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/opsintel/gateway/internal/config"
	"github.com/opsintel/gateway/internal/middleware"
	"github.com/opsintel/gateway/internal/proxy"
	"github.com/opsintel/gateway/internal/routes"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	cfg, err := config.Load()
	if err != nil {
		slog.Error("failed to load config", "error", err)
		os.Exit(1)
	}

	upstreamProxy := proxy.NewReverseProxy(cfg.UpstreamURL)

	mux := http.NewServeMux()
	routes.Register(mux, upstreamProxy, cfg)

	// Middleware chain: logging → request-id → auth → RBAC → proxy
	handler := middleware.Chain(
		mux,
		middleware.RequestID,
		middleware.Logger,
		middleware.Auth(cfg),
	)

	srv := &http.Server{
		Addr:         fmt.Sprintf(":%d", cfg.Port),
		Handler:      handler,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 120 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		slog.Info("Gateway starting", "port", cfg.Port, "upstream", cfg.UpstreamURL)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	slog.Info("Shutting down gateway...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		slog.Error("shutdown error", "error", err)
	}
	slog.Info("Gateway stopped")
}
