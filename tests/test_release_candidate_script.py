from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_femag_release.ps1"


def test_candidate_syncs_dependencies_before_local_validation() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    sync_call = "Sync-LocalDependencies"
    validation_call = "Invoke-LocalValidation"
    build_call = "Invoke-ProductionBuild"

    publish_block = content.split("function Publish-Candidate", 1)[1]
    assert sync_call in publish_block
    assert validation_call in publish_block
    assert build_call in publish_block
    assert publish_block.index(sync_call) < publish_block.index(validation_call) < publish_block.index(build_call)


def test_dependency_sync_uses_release_requirements_with_same_python() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert "requirements-build.txt" in content
    assert "'.venv\\Scripts\\python.exe'" in content
    assert "'-m', 'pip', 'install'" in content
    assert "'--disable-pip-version-check'" in content
