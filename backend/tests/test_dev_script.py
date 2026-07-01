from pathlib import Path


def test_windows_dev_script_passes_root_env_file_to_uvicorn() -> None:
    script = (Path(__file__).parents[2] / "scripts" / "dev.ps1").read_text(
        encoding="utf-8"
    )

    assert '$EnvFile = Join-Path $Root ".env"' in script
    assert '"--env-file", $EnvFile' in script
