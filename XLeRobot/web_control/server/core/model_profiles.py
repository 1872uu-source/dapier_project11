"""Named NOMI model pairings shared by the Web Control model switch API."""

MODEL_PROFILES = {
    "qwen_hermes": {
        "label": "Qwen + Hermes",
        "provider": "Ollama",
        "router_provider": "ollama",
        "router_model": "qwen2.5:7b",
        "worker_provider": "ollama",
        "worker_model": "hermes3:8b",
    },
    "qwen35_single": {
        "label": "Qwen3.5 9B (Single)",
        "provider": "Ollama",
        "router_provider": "ollama",
        "router_model": "qwen3.5:9b",
        "worker_provider": "ollama",
        "worker_model": "qwen3.5:9b",
    },
    "doubao_pro": {
        "label": "Doubao Pro + Doubao Pro",
        "provider": "Ark",
        "router_provider": "ark",
        "router_model": "doubao-seed-2-0-pro-260215",
        "worker_provider": "ark",
        "worker_model": "doubao-seed-2-0-pro-260215",
    },
    "qwen_doubao": {
        "label": "Qwen Router + Doubao Worker",
        "provider": "Ollama + Ark",
        "router_provider": "ollama",
        "router_model": "qwen2.5:7b",
        "worker_provider": "ark",
        "worker_model": "doubao-seed-2-0-pro-260215",
    },
    "doubao_hermes": {
        "label": "Doubao Router + Hermes Worker",
        "provider": "Ark + Ollama",
        "router_provider": "ark",
        "router_model": "doubao-seed-2-0-pro-260215",
        "worker_provider": "ollama",
        "worker_model": "hermes3:8b",
    },
}
