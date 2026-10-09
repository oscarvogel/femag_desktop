from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_femag_release.ps1"


def test_release_script_exposes_bootstrap_mode() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert "[ValidateSet('candidate', 'promote', 'bootstrap')]" in content
    assert "function Publish-LegacyBootstrap" in content
    assert "elseif ($Mode -eq 'bootstrap')" in content


def test_legacy_bootstrap_keeps_version_and_sha_and_only_changes_transport() -> None:
    content = SCRIPT.read_text(encoding="utf-8")
    block = content.split("function Publish-LegacyBootstrap", 1)[1].split("function Publish-Candidate", 1)[0]

    assert "Assert-Manifest $latest 'latest'" in block
    assert "Get-FileHash -LiteralPath $installer -Algorithm SHA256" in block
    assert "El instalador local no coincide con latest.json" in block
    assert "raw.githubusercontent.com/$ReleaseRepo/main/$bootstrapRelative" in block
    assert "$updated = Copy-Manifest $latest" in block
    assert "$updated['download_url'] = $bootstrapUrl" in block
    assert "$updated['bootstrap_transport'] = 'raw-github'" in block


def test_legacy_bootstrap_stages_only_manifest_and_bootstrap_installer() -> None:
    content = SCRIPT.read_text(encoding="utf-8")
    block = content.split("function Publish-LegacyBootstrap", 1)[1].split("function Publish-Candidate", 1)[0]

    assert "'apps/femag/latest.json', $bootstrapRelative" in block
    assert "El bootstrap intentó modificar archivos inesperados" in block
