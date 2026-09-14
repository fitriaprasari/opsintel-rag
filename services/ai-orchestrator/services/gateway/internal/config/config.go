// Config loads gateway configuration from environment variables.
// No hard-coded defaults for secrets.
package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
)

// Config holds all gateway runtime configuration.
type Config struct {
	Port        int
	UpstreamURL string

	// OIDC
	OIDCEnabled bool
	OIDCIssuer  string
	OIDCAudience string
	OIDCJWKSURI  string

	// Upstream service
	UpstreamTimeoutSeconds int
}

// Load reads all values from environment, returns error on missing required values.
func Load() (*Config, error) {
	upstreamURL := os.Getenv("GATEWAY_UPSTREAM_URL")
	if upstreamURL == "" {
		return nil, errors.New("GATEWAY_UPSTREAM_URL is required")
	}

	port := 8080
	if raw := os.Getenv("GATEWAY_PORT"); raw != "" {
		p, err := strconv.Atoi(raw)
		if err != nil {
			return nil, fmt.Errorf("invalid GATEWAY_PORT: %w", err)
		}
		port = p
	}

	oidcEnabled := os.Getenv("OIDC_ENABLED") == "true"
	timeoutSecs := 120
	if raw := os.Getenv("GATEWAY_TIMEOUT_SECONDS"); raw != "" {
		t, err := strconv.Atoi(raw)
		if err == nil {
			timeoutSecs = t
		}
	}

	return &Config{
		Port:                   port,
		UpstreamURL:            upstreamURL,
		OIDCEnabled:            oidcEnabled,
		OIDCIssuer:             os.Getenv("OIDC_ISSUER"),
		OIDCAudience:           os.Getenv("OIDC_AUDIENCE"),
		OIDCJWKSURI:            os.Getenv("OIDC_JWKS_URI"),
		UpstreamTimeoutSeconds: timeoutSecs,
	}, nil
}
