from pathlib import Path


def refresh(inputs, context):
    shared_dir = Path(context["config_path"]).resolve().parent
    return {
        "settings_path": str(shared_dir / "shared.yaml"),
        "settings": {"settings": inputs["desired.settings"]},
        "features_path": str(shared_dir / "generated_features.yaml"),
        "features": {"features": inputs["desired.features"]},
    }
