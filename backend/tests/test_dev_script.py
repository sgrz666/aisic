from pathlib import Path


def test_windows_dev_script_passes_root_env_file_to_uvicorn() -> None:
    script = (Path(__file__).parents[2] / "scripts" / "dev.ps1").read_text(
        encoding="utf-8"
    )

    assert '$EnvFile = Join-Path $Root ".env"' in script
    assert '"--env-file", $EnvFile' in script


def test_web_port_defaults_to_5174_and_is_configurable_everywhere() -> None:
    root = Path(__file__).parents[2]
    script = (root / "scripts" / "dev.ps1").read_text(encoding="utf-8")
    vite = (root / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    playwright = (root / "frontend" / "playwright.config.ts").read_text(
        encoding="utf-8"
    )
    compose = (root / "compose.yaml").read_text(encoding="utf-8")
    env_example = (root / ".env.example").read_text(encoding="utf-8")

    assert '$env:WEB_PORT' in script
    assert 'else { "5174" }' in script
    assert '"--port", $WebPort' in script
    assert 'http://127.0.0.1:$WebPort' in script
    assert "process.env.WEB_PORT ?? '5174'" in vite
    assert "process.env.WEB_PORT ?? '5174'" in playwright
    assert '"${WEB_PORT:-5174}:80"' in compose
    assert "WEB_PORT=5174" in env_example
